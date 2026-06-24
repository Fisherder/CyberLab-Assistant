from __future__ import annotations

import jwt

from fastapi.testclient import TestClient
from sqlalchemy import select

from cla import models
from cla.oracle import sign_oracle_payload
from cla.seed import DEV_IDS
from cla.settings import Settings


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_attempt(client: TestClient, token: str, key: str = "idem-1") -> dict:
    response = client.post(
        f"/api/v1/assignments/{DEV_IDS['assignment']}/attempts",
        headers={**auth(token), "Idempotency-Key": key},
        json={"clientCapabilities": {"terminalBinaryFrames": True, "workspaceTypes": ["TERMINAL"]}},
    )
    assert response.status_code == 202, response.text
    return response.json()


def ensure_session(client: TestClient, token: str, attempt_id: str) -> dict:
    response = client.post(
        f"/api/v1/attempts/{attempt_id}/sessions",
        headers=auth(token),
        json={"workspaceType": "TERMINAL"},
    )
    assert response.status_code == 202, response.text
    return response.json()


def issue_ticket(client: TestClient, token: str, attempt_id: str) -> dict:
    response = client.post(f"/api/v1/attempts/{attempt_id}/terminal-ticket", headers=auth(token))
    assert response.status_code == 200, response.text
    return response.json()


def test_attempt_creation_is_idempotent(
    client: TestClient, student_token: str, other_student_token: str
) -> None:
    first = create_attempt(client, student_token, "same-key")
    second = create_attempt(client, student_token, "same-key")
    assert first["attemptId"] == second["attemptId"]
    assert first["status"] == "PROVISIONING"

    forbidden = client.get(f"/api/v1/attempts/{first['attemptId']}", headers=auth(other_student_token))
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "FORBIDDEN_SCOPE"


def test_remote_desktop_is_feature_flag_only(client: TestClient, student_token: str) -> None:
    attempt = create_attempt(client, student_token, "rdp-attempt")
    response = client.post(
        f"/api/v1/attempts/{attempt['attemptId']}/sessions",
        headers=auth(student_token),
        json={"workspaceType": "REMOTE_DESKTOP"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "WORKSPACE_FEATURE_NOT_ENABLED"


def test_terminal_ticket_is_short_lived_bound_and_single_use(
    client: TestClient, settings: Settings, student_token: str
) -> None:
    attempt = create_attempt(client, student_token, "ticket-attempt")
    session = ensure_session(client, student_token, attempt["attemptId"])
    attempt_view = client.get(f"/api/v1/attempts/{attempt['attemptId']}", headers=auth(student_token))
    assert attempt_view.status_code == 200, attempt_view.text
    assert_internal_route_not_leaked(attempt_view.json())
    ticket_response = issue_ticket(client, student_token, attempt["attemptId"])

    assert ticket_response["sessionId"] == session["sessionId"]
    assert_internal_route_not_leaked(ticket_response)
    assert ticket_response["websocketUrl"] == "ws://gateway.test/ws/terminal"

    claims = jwt.decode(
        ticket_response["ticket"],
        settings.terminal_ticket_secret,
        algorithms=["HS256"],
        audience="cla-terminal-gateway",
        issuer="cla-api",
    )
    assert claims["attempt_id"] == attempt["attemptId"]
    assert claims["session_epoch"] == 1
    assert claims["exp"] - claims["iat"] == 60
    assert claims["permissions"] == ["terminal.connect", "terminal.resize"]

    consumed = client.post(
        "/internal/terminal/tickets/consume",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={"ticket": ticket_response["ticket"]},
    )
    assert consumed.status_code == 200, consumed.text
    assert consumed.json()["sessionRoute"]["routeRef"].startswith("route_")
    assert consumed.json()["sessionRoute"]["endpoint"] == "127.0.0.1:7777"
    assert consumed.json()["sessionRoute"]["protocol"] == "tcp-sessionwire"
    assert "endpoint" not in consumed.json()
    assert "routeRef" not in consumed.json()

    replay = client.post(
        "/internal/terminal/tickets/consume",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={"ticket": ticket_response["ticket"]},
    )
    assert replay.status_code == 401
    assert replay.json()["detail"]["code"] == "TERMINAL_TICKET_EXPIRED"
    with client.app.state.SessionLocal() as db:
        replay_audit = db.scalar(
            select(models.AuditLog).where(
                models.AuditLog.action == "terminal.ticket.consume.TERMINAL_TICKET_EXPIRED",
                models.AuditLog.resource_id == attempt["attemptId"],
                models.AuditLog.decision == "DENY",
            )
        )
        assert replay_audit is not None

    tampered = ticket_response["ticket"][:-2] + "aa"
    rejected = client.post(
        "/internal/terminal/tickets/consume",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={"ticket": tampered},
    )
    assert rejected.status_code == 401


def test_session_reset_rotates_epoch_route_and_rejects_old_ticket(
    client: TestClient, settings: Settings, student_token: str
) -> None:
    attempt = create_attempt(client, student_token, "reset-attempt")
    first_session = ensure_session(client, student_token, attempt["attemptId"])
    old_ticket = issue_ticket(client, student_token, attempt["attemptId"])

    reset = client.post(
        f"/api/v1/attempts/{attempt['attemptId']}/sessions/reset",
        headers=auth(student_token),
    )
    assert reset.status_code == 202, reset.text
    second_session = reset.json()
    assert second_session["sessionEpoch"] == first_session["sessionEpoch"] + 1
    assert second_session["sessionId"] != first_session["sessionId"]

    old_consume = client.post(
        "/internal/terminal/tickets/consume",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={"ticket": old_ticket["ticket"]},
    )
    assert old_consume.status_code == 401
    assert old_consume.json()["detail"]["code"] == "TERMINAL_TICKET_EXPIRED"

    new_ticket = issue_ticket(client, student_token, attempt["attemptId"])
    claims = jwt.decode(
        new_ticket["ticket"],
        settings.terminal_ticket_secret,
        algorithms=["HS256"],
        audience="cla-terminal-gateway",
        issuer="cla-api",
    )
    assert claims["session_epoch"] == 2
    assert claims["session_id"] == second_session["sessionId"]

    new_consume = client.post(
        "/internal/terminal/tickets/consume",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={"ticket": new_ticket["ticket"]},
    )
    assert new_consume.status_code == 200, new_consume.text
    assert new_consume.json()["sessionId"] == second_session["sessionId"]

    with client.app.state.SessionLocal() as db:
        labs = list(
            db.scalars(
                select(models.LabSession)
                .where(models.LabSession.attempt_id == attempt["attemptId"])
                .order_by(models.LabSession.epoch)
            )
        )
        assert [lab.status for lab in labs] == ["RESETTING", "READY"]
        assert labs[0].route_ref != labs[1].route_ref
        reset_event = db.scalar(
            select(models.Event).where(
                models.Event.attempt_id == attempt["attemptId"],
                models.Event.type == "lab.reset.requested",
            )
        )
        assert reset_event is not None
        reset_audit = db.scalar(
            select(models.AuditLog).where(
                models.AuditLog.action == "lab_session.reset",
                models.AuditLog.resource_id == attempt["attemptId"],
                models.AuditLog.decision == "ALLOW",
            )
        )
        assert reset_audit is not None


def test_internal_route_registration_updates_gateway_only_route_binding(
    client: TestClient, settings: Settings, student_token: str
) -> None:
    attempt = create_attempt(client, student_token, "route-registry-attempt")
    session = ensure_session(client, student_token, attempt["attemptId"])
    with client.app.state.SessionLocal() as db:
        lab = db.scalar(
            select(models.LabSession).where(
                models.LabSession.attempt_id == attempt["attemptId"],
                models.LabSession.epoch == session["sessionEpoch"],
            )
        )
        assert lab is not None
        route_ref = lab.route_ref
        lab.status = "PROVISIONING"
        lab.route_endpoint = "old-sessiond:7777"
        db.commit()

    endpoint = "workspace-sessiond.lab-a-123-e1.svc.cluster.local:7777"
    student_forbidden = client.post(
        f"/internal/attempts/{attempt['attemptId']}/sessions/{session['sessionEpoch']}/route",
        headers=auth(student_token),
        json={
            "routeRef": route_ref,
            "endpoint": endpoint,
            "protocol": "tcp-sessionwire",
        },
    )
    assert student_forbidden.status_code == 401

    mismatch = client.post(
        f"/internal/attempts/{attempt['attemptId']}/sessions/{session['sessionEpoch']}/route",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={
            "routeRef": "route_wrong",
            "endpoint": endpoint,
            "protocol": "tcp-sessionwire",
        },
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["code"] == "LAB_ROUTE_MISMATCH"

    registered = client.post(
        f"/internal/attempts/{attempt['attemptId']}/sessions/{session['sessionEpoch']}/route",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={
            "routeRef": route_ref,
            "endpoint": endpoint,
            "protocol": "tcp-sessionwire",
        },
    )
    assert registered.status_code == 202, registered.text
    assert registered.json()["status"] == "READY"

    ticket = issue_ticket(client, student_token, attempt["attemptId"])
    assert_internal_route_not_leaked(ticket)
    consumed = client.post(
        "/internal/terminal/tickets/consume",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={"ticket": ticket["ticket"]},
    )
    assert consumed.status_code == 200, consumed.text
    assert consumed.json()["sessionRoute"]["endpoint"] == endpoint
    assert "endpoint" not in consumed.json()

    with client.app.state.SessionLocal() as db:
        lab = db.scalar(
            select(models.LabSession).where(
                models.LabSession.attempt_id == attempt["attemptId"],
                models.LabSession.epoch == session["sessionEpoch"],
            )
        )
        assert lab is not None
        assert lab.status == "READY"
        assert lab.route_endpoint == endpoint
        event = db.scalar(
            select(models.Event).where(
                models.Event.attempt_id == attempt["attemptId"],
                models.Event.type == "lab.route.registered",
            )
        )
        assert event is not None
        assert "endpoint" not in str(event.payload_json)
        assert "routeRef" not in str(event.payload_json)
        audit = db.scalar(
            select(models.AuditLog).where(
                models.AuditLog.action == "lab.route.register",
                models.AuditLog.resource_id == lab.id,
                models.AuditLog.decision == "ALLOW",
            )
        )
        assert audit is not None


def test_internal_route_unregistration_invalidates_terminal_route(
    client: TestClient, settings: Settings, student_token: str
) -> None:
    attempt = create_attempt(client, student_token, "route-unregister-attempt")
    session = ensure_session(client, student_token, attempt["attemptId"])
    ticket = issue_ticket(client, student_token, attempt["attemptId"])
    with client.app.state.SessionLocal() as db:
        lab = db.scalar(
            select(models.LabSession).where(
                models.LabSession.attempt_id == attempt["attemptId"],
                models.LabSession.epoch == session["sessionEpoch"],
            )
        )
        assert lab is not None
        route_ref = lab.route_ref

    unregistered = client.post(
        f"/internal/attempts/{attempt['attemptId']}/sessions/{session['sessionEpoch']}/route/unregister",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={"routeRef": route_ref},
    )
    assert unregistered.status_code == 202, unregistered.text
    assert unregistered.json()["status"] == "TERMINATING"

    rejected = client.post(
        "/internal/terminal/tickets/consume",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={"ticket": ticket["ticket"]},
    )
    assert rejected.status_code == 401
    assert rejected.json()["detail"]["code"] == "TERMINAL_TICKET_EXPIRED"

    with client.app.state.SessionLocal() as db:
        lab = db.scalar(
            select(models.LabSession).where(
                models.LabSession.attempt_id == attempt["attemptId"],
                models.LabSession.epoch == session["sessionEpoch"],
            )
        )
        assert lab is not None
        assert lab.status == "TERMINATING"
        assert lab.route_endpoint == ""
        event = db.scalar(
            select(models.Event).where(
                models.Event.attempt_id == attempt["attemptId"],
                models.Event.type == "lab.route.unregistered",
            )
        )
        assert event is not None
        assert "endpoint" not in str(event.payload_json)


def test_internal_ticket_revocation_rejects_unconsumed_tickets_without_route_payload_leak(
    client: TestClient, settings: Settings, student_token: str
) -> None:
    attempt = create_attempt(client, student_token, "ticket-revoke-attempt")
    session = ensure_session(client, student_token, attempt["attemptId"])
    ticket = issue_ticket(client, student_token, attempt["attemptId"])
    with client.app.state.SessionLocal() as db:
        lab = db.scalar(
            select(models.LabSession).where(
                models.LabSession.attempt_id == attempt["attemptId"],
                models.LabSession.epoch == session["sessionEpoch"],
            )
        )
        assert lab is not None
        route_ref = lab.route_ref
        nonce = db.scalar(
            select(models.TerminalTicketNonce).where(
                models.TerminalTicketNonce.attempt_id == attempt["attemptId"],
                models.TerminalTicketNonce.session_id == lab.id,
            )
        )
        assert nonce is not None
        assert nonce.status == "ISSUED"

    student_forbidden = client.post(
        f"/internal/attempts/{attempt['attemptId']}/sessions/{session['sessionEpoch']}/tickets/revoke",
        headers=auth(student_token),
        json={"routeRef": route_ref},
    )
    assert student_forbidden.status_code == 401

    mismatch = client.post(
        f"/internal/attempts/{attempt['attemptId']}/sessions/{session['sessionEpoch']}/tickets/revoke",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={"routeRef": "route_wrong"},
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["code"] == "LAB_ROUTE_MISMATCH"

    revoked = client.post(
        f"/internal/attempts/{attempt['attemptId']}/sessions/{session['sessionEpoch']}/tickets/revoke",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={"routeRef": route_ref},
    )
    assert revoked.status_code == 202, revoked.text
    assert revoked.json()["revokedCount"] == 1

    rejected = client.post(
        "/internal/terminal/tickets/consume",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={"ticket": ticket["ticket"]},
    )
    assert rejected.status_code == 401
    assert rejected.json()["detail"]["code"] == "TERMINAL_TICKET_EXPIRED"

    with client.app.state.SessionLocal() as db:
        lab = db.scalar(
            select(models.LabSession).where(
                models.LabSession.attempt_id == attempt["attemptId"],
                models.LabSession.epoch == session["sessionEpoch"],
            )
        )
        assert lab is not None
        nonce = db.scalar(
            select(models.TerminalTicketNonce).where(
                models.TerminalTicketNonce.attempt_id == attempt["attemptId"],
                models.TerminalTicketNonce.session_id == lab.id,
            )
        )
        assert nonce is not None
        assert nonce.status == "REVOKED"
        event = db.scalar(
            select(models.Event).where(
                models.Event.attempt_id == attempt["attemptId"],
                models.Event.type == "terminal.tickets.revoked",
            )
        )
        assert event is not None
        assert event.payload_json["revoked_count"] == 1
        assert "endpoint" not in str(event.payload_json)
        assert "routeRef" not in str(event.payload_json)
        audit = db.scalar(
            select(models.AuditLog).where(
                models.AuditLog.action == "terminal.tickets.revoke",
                models.AuditLog.resource_id == lab.id,
                models.AuditLog.decision == "ALLOW",
            )
        )
        assert audit is not None


def assert_internal_route_not_leaked(value: object) -> None:
    encoded = str(value)
    for forbidden in ["route_ref", "routeRef", "endpoint", "127.0.0.1:7777", "sessiond"]:
        assert forbidden not in encoded


def test_oracle_submission_grade_and_appeal_survive_agent_disabled(
    client: TestClient,
    settings: Settings,
    student_token: str,
    other_student_token: str,
    teacher_token: str,
) -> None:
    assert client.get("/healthz").json()["agentRuntimeEnabled"] is False
    attempt = create_attempt(client, student_token, "grade-attempt")
    ensure_session(client, student_token, attempt["attemptId"])

    payload = {
        "oracleVersion": "web-sqli-auth-oracle/1.3.0",
        "passed": True,
        "targetSessionKey": "target-session-boundary-state",
        "evidence": {"predicate": "auth_bypass_observed", "target": "external"},
    }
    oracle = client.post(
        f"/internal/oracle/attempts/{attempt['attemptId']}/observations",
        headers={"X-CLA-Oracle-Signature": sign_oracle_payload(settings, payload)},
        json=payload,
    )
    assert oracle.status_code == 202, oracle.text

    bad_oracle = client.post(
        f"/internal/oracle/attempts/{attempt['attemptId']}/observations",
        headers={"X-CLA-Oracle-Signature": "bad"},
        json=payload,
    )
    assert bad_oracle.status_code == 401

    submitted = client.post(
        f"/api/v1/attempts/{attempt['attemptId']}/submit",
        headers={**auth(student_token), "If-Match": '"attempt-version-1"'},
        json={
            "answers": [
                {
                    "questionId": "root-cause",
                    "format": "MARKDOWN",
                    "content": "根因是登录接口把用户输入直接拼进 SQL，越过了输入信任边界；应使用参数化查询或 prepared statement。",
                    "clientDraftId": "draft-1",
                }
            ],
            "requestOracleCheck": True,
        },
    )
    assert submitted.status_code == 202, submitted.text

    grade = client.get(f"/api/v1/attempts/{attempt['attemptId']}/grade", headers=auth(student_token))
    assert grade.status_code == 200, grade.text
    body = grade.json()
    assert body["totalScore"] == 100.0
    assert body["independenceIndex"] == 1.0
    assert body["rubricVersion"] == "web-sqli-auth-001@1.3.0-rubric.1"
    assert body["graderVersion"] == "cla-deterministic-grader/0.1.0"
    assert len(body["criteria"]) == 2
    assert {criterion["graderType"] for criterion in body["criteria"]} == {
        "DETERMINISTIC_ORACLE",
        "EVENT_PATTERN",
    }
    assert all(criterion["evidenceRefs"] for criterion in body["criteria"])

    forbidden_grade = client.get(
        f"/api/v1/attempts/{attempt['attemptId']}/grade", headers=auth(other_student_token)
    )
    assert forbidden_grade.status_code == 403

    missing_criterion = client.post(
        f"/api/v1/grades/{body['gradeRevisionId']}/appeals",
        headers=auth(student_token),
        json={"reason": "请复核解释项证据引用。"},
    )
    assert missing_criterion.status_code == 422

    unknown_criterion = client.post(
        f"/api/v1/grades/{body['gradeRevisionId']}/appeals",
        headers=auth(student_token),
        json={"criterionId": "not-in-this-revision", "reason": "请复核解释项证据引用。"},
    )
    assert unknown_criterion.status_code == 422
    assert unknown_criterion.json()["detail"]["code"] == "GRADE_CRITERION_NOT_FOUND"

    criterion_id = body["criteria"][1]["criterionId"]
    appeal = client.post(
        f"/api/v1/grades/{body['gradeRevisionId']}/appeals",
        headers=auth(student_token),
        json={"criterionId": criterion_id, "reason": "请复核解释项证据引用。"},
    )
    assert appeal.status_code == 201, appeal.text
    assert appeal.json()["status"] == "OPEN"
    assert appeal.json()["criterionId"] == criterion_id
    with client.app.state.SessionLocal() as db:
        stored = db.scalar(select(models.Appeal).where(models.Appeal.id == appeal.json()["appealId"]))
        assert stored is not None
        assert stored.criterion_id == criterion_id

    student_resolve = client.post(
        f"/api/v1/appeals/{appeal.json()['appealId']}/resolve",
        headers=auth(student_token),
        json={"decision": "UPHOLD_ORIGINAL", "resolution": "维持原判。"},
    )
    assert student_resolve.status_code == 403

    invalid_override = client.post(
        f"/api/v1/appeals/{appeal.json()['appealId']}/resolve",
        headers=auth(teacher_token),
        json={
            "decision": "OVERRIDE_SCORE",
            "resolution": "补充说明不足以支持超分。",
            "criterionOverrides": [
                {
                    "criterionId": criterion_id,
                    "score": 41.0,
                    "explanation": "教师复核覆盖。",
                }
            ],
        },
    )
    assert invalid_override.status_code == 422
    assert invalid_override.json()["detail"]["code"] == "GRADE_SCORE_OUT_OF_RANGE"

    resolved = client.post(
        f"/api/v1/appeals/{appeal.json()['appealId']}/resolve",
        headers=auth(teacher_token),
        json={
            "decision": "OVERRIDE_SCORE",
            "resolution": "采纳申诉，解释项补充材料有效。",
            "criterionOverrides": [
                {
                    "criterionId": criterion_id,
                    "score": 35.0,
                    "explanation": "教师复核后确认解释项部分有效，但缺少回归验证。",
                }
            ],
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "RESOLVED"
    assert resolved.json()["gradeRevisionId"] != body["gradeRevisionId"]

    latest_grade = client.get(
        f"/api/v1/attempts/{attempt['attemptId']}/grade", headers=auth(student_token)
    )
    assert latest_grade.status_code == 200
    latest = latest_grade.json()
    assert latest["revisionNo"] == 2
    assert latest["totalScore"] == 95.0
    assert latest["independenceIndex"] == 1.0
    override = next(
        criterion for criterion in latest["criteria"] if criterion["criterionId"] == criterion_id
    )
    assert override["graderType"] == "TEACHER_OVERRIDE"
    assert override["confidence"] == 1.0
    assert f"appeal:{appeal.json()['appealId']}" in override["evidenceRefs"]
    with client.app.state.SessionLocal() as db:
        revisions = db.scalars(
            select(models.GradeRevision)
            .where(models.GradeRevision.attempt_id == attempt["attemptId"])
            .order_by(models.GradeRevision.revision_no)
        ).all()
        assert [revision.revision_no for revision in revisions] == [1, 2]
        resolved_appeal = db.get(models.Appeal, appeal.json()["appealId"])
        assert resolved_appeal is not None
        assert resolved_appeal.status == "RESOLVED"
        assert resolved_appeal.resolved_by == DEV_IDS["teacher"]
        audit = db.scalar(
            select(models.AuditLog).where(
                models.AuditLog.action == "appeal.resolve",
                models.AuditLog.resource_id == appeal.json()["appealId"],
            )
        )
        assert audit is not None
        assert audit.before_ref == body["gradeRevisionId"]
        assert audit.after_ref == latest["gradeRevisionId"]
