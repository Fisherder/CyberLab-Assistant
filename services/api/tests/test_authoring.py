from __future__ import annotations

from sqlalchemy import func, select
from fastapi.testclient import TestClient

from cla import models
from cla.seed import DEV_IDS

from test_terminal_vertical_slice import auth


def create_draft(
    client: TestClient,
    token: str,
    *,
    key: str = "draft-idem-1",
    constraints: dict | None = None,
) -> dict:
    response = client.post(
        "/api/v1/challenge-drafts",
        headers={**auth(token), "Idempotency-Key": key},
        json={
            "courseId": DEV_IDS["course"],
            "brief": (
                "Create a terminal web SQL injection login practice. Students use curl and "
                "python, validate auth impact, and explain the input trust boundary in 75 minutes."
            ),
            "constraints": constraints or {"internet": False, "maxDifficulty": 3},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_teacher_creates_brief_draft_and_gets_explainable_candidates(
    client: TestClient,
    teacher_token: str,
    student_token: str,
) -> None:
    no_key = client.post(
        "/api/v1/challenge-drafts",
        headers=auth(teacher_token),
        json={"courseId": DEV_IDS["course"], "brief": "Need a terminal web SQLi lab."},
    )
    assert no_key.status_code == 400
    assert no_key.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"

    forbidden = client.post(
        "/api/v1/challenge-drafts",
        headers={**auth(student_token), "Idempotency-Key": "student-draft"},
        json={"courseId": DEV_IDS["course"], "brief": "Need a terminal web SQLi lab."},
    )
    assert forbidden.status_code == 403

    draft = create_draft(client, teacher_token)
    repeated = create_draft(client, teacher_token)
    assert repeated["draftId"] == draft["draftId"]
    assert draft["status"] == "PARSED"
    assert draft["courseIntent"]["category"] == "WEB"
    assert draft["courseIntent"]["workspaceType"] == "TERMINAL"
    assert draft["courseIntent"]["uncertainFields"] == []
    assert draft["courseIntent"]["confidence"] >= 0.9

    student_candidates = client.get(draft["candidatesUrl"], headers=auth(student_token))
    assert student_candidates.status_code == 403

    response = client.get(draft["candidatesUrl"], headers=auth(teacher_token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["draftId"] == draft["draftId"]
    assert body["rejectedCandidates"] == []
    assert body["candidates"]
    candidate = body["candidates"][0]
    assert candidate["candidateId"] == DEV_IDS["challenge_version"]
    assert candidate["constraintsSatisfied"] is True
    assert "category" in candidate["matchReasons"]
    assert "workspaceType" in candidate["matchReasons"]
    assert candidate["validationStatus"] == "PASS"

    with client.app.state.SessionLocal() as db:
        assert db.scalar(select(func.count(models.AgentRun.id))) == 0
        audit = db.scalar(
            select(models.AuditLog).where(
                models.AuditLog.action == "challenge.draft.candidates.read",
                models.AuditLog.resource_id == draft["draftId"],
            )
        )
        assert audit is not None


def test_authoring_hard_constraints_are_not_overridden(
    client: TestClient,
    teacher_token: str,
) -> None:
    draft = create_draft(
        client,
        teacher_token,
        key="draft-remote-desktop",
        constraints={"workspaceType": "REMOTE_DESKTOP", "internet": False},
    )
    response = client.get(draft["candidatesUrl"], headers=auth(teacher_token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["candidates"] == []
    assert body["rejectedCandidates"]
    rejected = body["rejectedCandidates"][0]
    assert rejected["candidateId"] == DEV_IDS["challenge_version"]
    assert any(conflict.startswith("workspaceType:") for conflict in rejected["conflicts"])

    materialize = client.post(
        f"/api/v1/challenge-drafts/{draft['draftId']}/materialize",
        headers=auth(teacher_token),
        json={"selectedCandidateId": DEV_IDS["challenge_version"]},
    )
    assert materialize.status_code == 422
    assert materialize.json()["detail"]["code"] == "AUTHORING_HARD_CONSTRAINT_CONFLICT"


def test_materialize_creates_pending_version_validation_and_requires_approval(
    client: TestClient,
    teacher_token: str,
) -> None:
    draft = create_draft(client, teacher_token, key="draft-materialize")
    materialize = client.post(
        f"/api/v1/challenge-drafts/{draft['draftId']}/materialize",
        headers=auth(teacher_token),
        json={"selectedCandidateId": DEV_IDS["challenge_version"]},
    )
    assert materialize.status_code == 200, materialize.text
    body = materialize.json()
    assert body["draftId"] == draft["draftId"]
    assert body["status"] == "MATERIALIZED"
    assert body["sourceCandidateId"] == DEV_IDS["challenge_version"]
    assert body["challengeVersionId"] != DEV_IDS["challenge_version"]
    assert body["versionStatus"] == "PENDING_APPROVAL"
    assert body["validationStatus"] == "PASS"
    assert body["approvalRequired"] is True

    validation = client.get(body["validationReportUrl"], headers=auth(teacher_token))
    assert validation.status_code == 200, validation.text
    assert validation.json()["challengeVersionId"] == body["challengeVersionId"]
    assert validation.json()["overallStatus"] == "PASS"

    approval = client.post(
        f"/api/v1/challenge-versions/{body['challengeVersionId']}/approve",
        headers=auth(teacher_token),
    )
    assert approval.status_code == 200, approval.text
    assert approval.json()["published"] is True
    assert approval.json()["alreadyPublished"] is False

    repeated = client.post(
        f"/api/v1/challenge-drafts/{draft['draftId']}/materialize",
        headers=auth(teacher_token),
        json={"selectedCandidateId": DEV_IDS["challenge_version"]},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["challengeVersionId"] == body["challengeVersionId"]

    with client.app.state.SessionLocal() as db:
        version = db.get(models.ChallengeVersion, body["challengeVersionId"])
        assert version is not None
        assert version.status == "PUBLISHED"
        assert version.created_by == DEV_IDS["teacher"]
        run = db.get(models.ValidationRun, body["validationRunId"])
        assert run is not None
        assert run.version_id == version.id
        materialized_events = db.scalar(
            select(func.count(models.OutboxEvent.id)).where(
                models.OutboxEvent.aggregate_type == "challenge_version",
                models.OutboxEvent.aggregate_id == version.id,
                models.OutboxEvent.event_type == "challenge.version.materialized",
            )
        )
        assert materialized_events == 1
        assert db.scalar(select(func.count(models.AgentRun.id))) == 0
