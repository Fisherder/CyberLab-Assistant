from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from cla import models
from cla.seed import DEV_IDS
from cla.settings import Settings

from test_terminal_vertical_slice import auth, create_attempt, ensure_session
from test_tutor import append_repeated_failed_commands


def append_monitor_alerts(
    client: TestClient,
    settings: Settings,
    attempt_id: str,
) -> None:
    response = client.post(
        f"/internal/attempts/{attempt_id}/events",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={
            "events": [
                {
                    "sessionEpoch": 1,
                    "source": "cla-env-controller",
                    "type": "lab.resource.throttled",
                    "payload": {
                        "resource": "cpu",
                        "secret_like_terminal_text": "Authorization: Bearer SHOULD_NOT_LEAK",
                    },
                },
                {
                    "sessionEpoch": 1,
                    "source": "cla-env-controller",
                    "type": "lab.egress.denied",
                    "payload": {
                        "destination": "169.254.169.254",
                        "command_redacted": "curl -H 'Authorization: Bearer SHOULD_NOT_LEAK'",
                    },
                },
            ]
        },
    )
    assert response.status_code == 202, response.text


def test_teacher_live_monitor_aggregates_without_raw_terminal_text(
    client: TestClient,
    settings: Settings,
    student_token: str,
    other_student_token: str,
    teacher_token: str,
) -> None:
    attempt = create_attempt(client, student_token, "teacher-live-attempt")
    ensure_session(client, student_token, attempt["attemptId"])
    append_repeated_failed_commands(
        client,
        settings,
        attempt["attemptId"],
        command_redacted="curl -H 'Authorization: Bearer SHOULD_NOT_LEAK' http://target/login",
    )
    first_state = client.get(
        f"/api/v1/attempts/{attempt['attemptId']}/tutor-state",
        headers=auth(student_token),
    )
    second_state = client.get(
        f"/api/v1/attempts/{attempt['attemptId']}/tutor-state",
        headers=auth(student_token),
    )
    assert first_state.status_code == 200
    assert second_state.status_code == 200
    append_monitor_alerts(client, settings, attempt["attemptId"])

    student_forbidden = client.get(
        f"/api/v1/assignments/{DEV_IDS['assignment']}/live",
        headers=auth(student_token),
    )
    assert student_forbidden.status_code == 403

    other_forbidden = client.get(
        f"/api/v1/assignments/{DEV_IDS['assignment']}/live",
        headers=auth(other_student_token),
    )
    assert other_forbidden.status_code == 403

    live = client.get(
        f"/api/v1/assignments/{DEV_IDS['assignment']}/live",
        headers=auth(teacher_token),
    )
    assert live.status_code == 200, live.text
    body = live.json()
    assert body["assignmentId"] == DEV_IDS["assignment"]
    assert body["summary"]["totalAttempts"] == 1
    assert body["summary"]["readySessions"] == 1
    assert body["summary"]["stuckSuspected"] == 1
    assert body["summary"]["resourceAlerts"] == 1
    assert body["summary"]["securityAlerts"] == 1
    session = body["sessions"][0]
    assert session["attemptId"] == attempt["attemptId"]
    assert session["studentDisplayName"] == "Student"
    assert session["sessionStatus"] == "READY"
    assert session["latestAssessment"]["state"] == "CONFIRMED"
    assert session["latestHint"] == {
        "level": "L1",
        "status": "SHOWN",
        "triggerType": "AUTO_STUCK",
    }
    assert session["alerts"] == {"resource": 1, "security": 1}
    encoded = str(body)
    assert "SHOULD_NOT_LEAK" not in encoded
    assert "Authorization" not in encoded
    assert "curl" not in encoded

    with client.app.state.SessionLocal() as db:
        audit = db.scalar(
            select(models.AuditLog).where(
                models.AuditLog.action == "assignment.live.read",
                models.AuditLog.resource_id == DEV_IDS["assignment"],
            )
        )
        assert audit is not None
