from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from cla import models
from cla.seed import DEV_IDS

from test_terminal_vertical_slice import auth


def test_teacher_creates_course_members_and_published_assignment(
    client: TestClient,
    teacher_token: str,
    student_token: str,
    other_student_token: str,
) -> None:
    student_forbidden = client.post(
        "/api/v1/courses",
        headers={**auth(student_token), "Idempotency-Key": "student-course"},
        json={"code": "WEBSEC-201", "title": "Student Course", "term": "2026-S"},
    )
    assert student_forbidden.status_code == 403

    course_response = client.post(
        "/api/v1/courses",
        headers={**auth(teacher_token), "Idempotency-Key": "course-201"},
        json={"code": "WEBSEC-201", "title": "Advanced Web Security", "term": "2026-S"},
    )
    assert course_response.status_code == 201, course_response.text
    course = course_response.json()
    assert course["code"] == "WEBSEC-201"
    assert course["ownerId"] == DEV_IDS["teacher"]

    repeated_course = client.post(
        "/api/v1/courses",
        headers={**auth(teacher_token), "Idempotency-Key": "course-201"},
        json={"code": "WEBSEC-201", "title": "Advanced Web Security", "term": "2026-S"},
    )
    assert repeated_course.status_code == 201
    assert repeated_course.json()["courseId"] == course["courseId"]

    student_member = client.put(
        f"/api/v1/courses/{course['courseId']}/members/{DEV_IDS['student']}",
        headers=auth(teacher_token),
        json={"role": "STUDENT"},
    )
    assert student_member.status_code == 200, student_member.text
    assert student_member.json() == {
        "courseId": course["courseId"],
        "userId": DEV_IDS["student"],
        "role": "STUDENT",
    }

    ta_member = client.put(
        f"/api/v1/courses/{course['courseId']}/members/{DEV_IDS['other_student']}",
        headers=auth(teacher_token),
        json={"role": "TA"},
    )
    assert ta_member.status_code == 200, ta_member.text

    open_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    due_at = open_at + timedelta(days=7)
    assignment_response = client.post(
        "/api/v1/assignments",
        headers={**auth(other_student_token), "Idempotency-Key": "assignment-201"},
        json={
            "courseId": course["courseId"],
            "challengeVersionId": DEV_IDS["challenge_version"],
            "title": "Week 1 SQLi Auth",
            "openAt": open_at.isoformat(),
            "dueAt": due_at.isoformat(),
            "attemptPolicy": {"maxAttempts": 2, "maxResets": 1},
        },
    )
    assert assignment_response.status_code == 201, assignment_response.text
    assignment = assignment_response.json()
    assert assignment["courseId"] == course["courseId"]
    assert assignment["challengeVersionId"] == DEV_IDS["challenge_version"]
    assert assignment["attemptPolicy"] == {"maxAttempts": 2, "maxResets": 1}

    repeated_assignment = client.post(
        "/api/v1/assignments",
        headers={**auth(other_student_token), "Idempotency-Key": "assignment-201"},
        json={
            "courseId": course["courseId"],
            "challengeVersionId": DEV_IDS["challenge_version"],
            "title": "Week 1 SQLi Auth",
        },
    )
    assert repeated_assignment.status_code == 201
    assert repeated_assignment.json()["assignmentId"] == assignment["assignmentId"]

    attempt = client.post(
        f"/api/v1/assignments/{assignment['assignmentId']}/attempts",
        headers={**auth(student_token), "Idempotency-Key": "new-course-attempt"},
        json={"clientCapabilities": {"terminalBinaryFrames": True, "workspaceTypes": ["TERMINAL"]}},
    )
    assert attempt.status_code == 202, attempt.text

    with client.app.state.SessionLocal() as db:
        db_assignment = db.get(models.Assignment, assignment["assignmentId"])
        assert db_assignment is not None
        assert db_assignment.challenge_version_id == DEV_IDS["challenge_version"]
        assert db_assignment.attempt_policy_json == {"maxAttempts": 2, "maxResets": 1}
        assert db.scalar(
            select(func.count(models.AuditLog.id)).where(
                models.AuditLog.action.in_(
                    ["course.create", "course.member.upsert", "assignment.create"]
                )
            )
        ) >= 3
        assignment_events = db.scalar(
            select(func.count(models.OutboxEvent.id)).where(
                models.OutboxEvent.event_type == "assignment.opened",
                models.OutboxEvent.aggregate_id == assignment["assignmentId"],
            )
        )
        assert assignment_events == 1


def test_assignment_rejects_unpublished_challenge_version(
    client: TestClient,
    teacher_token: str,
) -> None:
    with client.app.state.SessionLocal() as db:
        version = db.get(models.ChallengeVersion, DEV_IDS["challenge_version"])
        assert version is not None
        version.status = "PENDING_APPROVAL"
        db.commit()

    response = client.post(
        "/api/v1/assignments",
        headers={**auth(teacher_token), "Idempotency-Key": "assignment-unpublished"},
        json={
            "courseId": DEV_IDS["course"],
            "challengeVersionId": DEV_IDS["challenge_version"],
            "title": "Should fail",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CHALLENGE_VERSION_NOT_PUBLISHED"
