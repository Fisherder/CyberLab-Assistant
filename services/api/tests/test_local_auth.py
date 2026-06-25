from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from cla import models
from cla.seed import DEV_IDS


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register_account(
    client: TestClient,
    *,
    email: str,
    password: str = "SecurePass123!",
    display_name: str = "本地用户",
    role: str = "STUDENT",
) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "displayName": display_name,
            "role": role,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_student_can_register_login_and_use_assignment(client: TestClient) -> None:
    registered = register_account(client, email="new-student@example.edu", display_name="新学生")

    assert registered["tokenType"] == "Bearer"
    assert registered["user"]["displayName"] == "新学生"
    assert registered["user"]["roles"] == ["student"]
    assert registered["user"]["courseRoles"] == [
        {"courseId": DEV_IDS["course"], "role": "STUDENT"}
    ]

    me = client.get("/api/v1/me", headers=bearer(registered["accessToken"]))
    assert me.status_code == 200, me.text
    assert me.json()["displayName"] == "新学生"

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "NEW-STUDENT@example.edu", "password": "SecurePass123!"},
    )
    assert login.status_code == 200, login.text
    assert login.json()["user"]["userId"] == registered["user"]["userId"]

    attempt = client.post(
        f"/api/v1/assignments/{DEV_IDS['assignment']}/attempts",
        headers={**bearer(login.json()["accessToken"]), "Idempotency-Key": "local-student"},
        json={
            "clientCapabilities": {
                "terminalBinaryFrames": True,
                "workspaceTypes": ["TERMINAL"],
            }
        },
    )
    assert attempt.status_code == 202, attempt.text
    assert attempt.json()["status"] == "PROVISIONING"


def test_teacher_can_register_and_open_teacher_pages(client: TestClient) -> None:
    registered = register_account(
        client,
        email="new-teacher@example.edu",
        display_name="新教师",
        role="TEACHER",
    )

    assert registered["user"]["roles"] == ["teacher"]
    validation = client.get(
        f"/api/v1/challenge-versions/{DEV_IDS['challenge_version']}/validation",
        headers=bearer(registered["accessToken"]),
    )
    assert validation.status_code == 200, validation.text

    live = client.get(
        f"/api/v1/assignments/{DEV_IDS['assignment']}/live",
        headers=bearer(registered["accessToken"]),
    )
    assert live.status_code == 200, live.text


def test_register_rejects_duplicate_email_case_insensitively(client: TestClient) -> None:
    register_account(client, email="duplicate@example.edu")
    duplicate = client.post(
        "/api/v1/auth/register",
        json={
            "email": "DUPLICATE@example.edu",
            "password": "SecurePass123!",
            "displayName": "重复用户",
            "role": "STUDENT",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "ACCOUNT_ALREADY_EXISTS"


def test_login_rejects_wrong_password_and_does_not_update_last_login(client: TestClient) -> None:
    registered = register_account(client, email="wrong-password@example.edu")
    wrong = client.post(
        "/api/v1/auth/login",
        json={"email": "wrong-password@example.edu", "password": "bad-password"},
    )
    assert wrong.status_code == 401
    assert wrong.json()["detail"]["code"] == "INVALID_CREDENTIALS"

    with client.app.state.SessionLocal() as db:
        user = db.scalar(
            select(models.User).where(models.User.id == registered["user"]["userId"])
        )
        assert user is not None
        assert user.last_login_at is None
