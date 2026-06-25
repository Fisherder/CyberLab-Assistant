from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from cla import models
from cla.seed import DEV_IDS

from test_terminal_vertical_slice import auth


def _bank_payload(**overrides: object) -> dict:
    payload = {
        "courseId": DEV_IDS["course"],
        "challengeVersionId": DEV_IDS["challenge_version"],
        "title": "课堂 SQL 注入认证题",
        "summary": "验证登录输入信任边界并说明修复方向。",
        "description": "学生需要访问目标站点，构造认证绕过请求，并解释为什么参数化查询可以修复问题。",
        "requirements": "获取环境后访问目标地址，完成验证并在终端工作台提交根因解释。",
        "tags": ["WEB", "SQLi", "认证"],
    }
    payload.update(overrides)
    return payload


def _create_bank_item(
    client: TestClient,
    teacher_token: str,
    *,
    key: str,
    **overrides: object,
) -> dict:
    response = client.post(
        "/api/v1/teacher/challenge-bank",
        headers={**auth(teacher_token), "Idempotency-Key": key},
        json=_bank_payload(**overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_teacher_bank_lifecycle_and_student_visibility(
    client: TestClient,
    teacher_token: str,
    student_token: str,
) -> None:
    student_forbidden = client.post(
        "/api/v1/teacher/challenge-bank",
        headers={**auth(student_token), "Idempotency-Key": "student-bank-create"},
        json=_bank_payload(),
    )
    assert student_forbidden.status_code == 403

    draft = _create_bank_item(client, teacher_token, key="bank-draft")
    assert draft["status"] == "DRAFT"
    assert draft["publishState"] == "UNPUBLISHED"
    assert draft["actions"]["canEdit"] is True
    assert draft["assignmentId"] is None

    student_empty = client.get("/api/v1/student/challenge-bank", headers=auth(student_token))
    assert student_empty.status_code == 200, student_empty.text
    assert student_empty.json()["items"] == []

    future_open = datetime.now(timezone.utc) + timedelta(hours=1)
    future_due = future_open + timedelta(hours=2)
    published = client.post(
        f"/api/v1/teacher/challenge-bank/{draft['itemId']}/publish",
        headers=auth(teacher_token),
        json={"openAt": future_open.isoformat(), "dueAt": future_due.isoformat()},
    )
    assert published.status_code == 200, published.text
    body = published.json()
    assert body["status"] == "PUBLISHED"
    assert body["publishState"] == "NOT_STARTED"
    assert body["assignmentId"]

    student_list = client.get("/api/v1/student/challenge-bank", headers=auth(student_token))
    assert student_list.status_code == 200, student_list.text
    student_item = student_list.json()["items"][0]
    assert student_item["itemId"] == draft["itemId"]
    assert student_item["clickable"] is False
    assert student_item["disabledReason"] == "题目还未开始"

    start_too_early = client.post(
        f"/api/v1/student/challenge-bank/{draft['itemId']}/start",
        headers=auth(student_token),
    )
    assert start_too_early.status_code == 409
    assert start_too_early.json()["detail"]["code"] == "CHALLENGE_BANK_ITEM_NOT_ACTIVE"

    unpublish = client.post(
        f"/api/v1/teacher/challenge-bank/{draft['itemId']}/unpublish",
        headers=auth(teacher_token),
    )
    assert unpublish.status_code == 200, unpublish.text
    assert unpublish.json()["status"] == "UNPUBLISHED"
    assert unpublish.json()["openAt"] is not None
    assert unpublish.json()["dueAt"] is not None

    edited = client.patch(
        f"/api/v1/teacher/challenge-bank/{draft['itemId']}",
        headers=auth(teacher_token),
        json={"title": "修改后的 SQL 注入认证题", "tags": ["WEB", "SQLi"]},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["title"] == "修改后的 SQL 注入认证题"
    assert edited.json()["tags"] == ["WEB", "SQLi"]

    deleted = client.delete(
        f"/api/v1/teacher/challenge-bank/{draft['itemId']}",
        headers=auth(teacher_token),
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["status"] == "DELETED"

    teacher_list = client.get("/api/v1/teacher/challenge-bank", headers=auth(teacher_token))
    assert teacher_list.status_code == 200, teacher_list.text
    assert all(item["itemId"] != draft["itemId"] for item in teacher_list.json()["items"])

    trash = client.get("/api/v1/teacher/challenge-bank/trash", headers=auth(teacher_token))
    assert trash.status_code == 200, trash.text
    assert trash.json()["items"][0]["itemId"] == draft["itemId"]

    restored = client.post(
        f"/api/v1/teacher/challenge-bank/{draft['itemId']}/restore",
        headers=auth(teacher_token),
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "UNPUBLISHED"
    assert restored.json()["publishState"] == "UNPUBLISHED"


def test_student_starts_one_environment_per_bank_item_and_can_run_multiple_items(
    client: TestClient,
    teacher_token: str,
    student_token: str,
) -> None:
    open_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    due_at = datetime.now(timezone.utc) + timedelta(hours=2)
    item_one = _create_bank_item(
        client,
        teacher_token,
        key="bank-active-one",
        title="第一题：认证绕过",
        publish=True,
        publishWindow={"openAt": open_at.isoformat(), "dueAt": due_at.isoformat()},
    )
    item_two = _create_bank_item(
        client,
        teacher_token,
        key="bank-active-two",
        title="第二题：输入边界",
        publish=True,
        publishWindow={"openAt": open_at.isoformat(), "dueAt": due_at.isoformat()},
    )

    visible = client.get("/api/v1/student/challenge-bank", headers=auth(student_token))
    assert visible.status_code == 200, visible.text
    active_ids = {item["itemId"] for item in visible.json()["items"] if item["clickable"]}
    assert {item_one["itemId"], item_two["itemId"]} <= active_ids

    first_start = client.post(
        f"/api/v1/student/challenge-bank/{item_one['itemId']}/start",
        headers=auth(student_token),
    )
    assert first_start.status_code == 202, first_start.text
    first = first_start.json()
    assert first["reusedAttempt"] is False
    assert first["targetUrl"].startswith("http://127.0.0.1:18080")
    assert "route" not in first
    assert "sessiond" not in str(first).lower()

    repeated_start = client.post(
        f"/api/v1/student/challenge-bank/{item_one['itemId']}/start",
        headers=auth(student_token),
    )
    assert repeated_start.status_code == 202, repeated_start.text
    repeated = repeated_start.json()
    assert repeated["attemptId"] == first["attemptId"]
    assert repeated["sessionId"] == first["sessionId"]
    assert repeated["reusedAttempt"] is True

    second_start = client.post(
        f"/api/v1/student/challenge-bank/{item_two['itemId']}/start",
        headers=auth(student_token),
    )
    assert second_start.status_code == 202, second_start.text
    second = second_start.json()
    assert second["attemptId"] != first["attemptId"]
    assert second["assignmentId"] != first["assignmentId"]

    with client.app.state.SessionLocal() as db:
        attempts = db.scalars(
            select(models.Attempt).where(models.Attempt.student_id == DEV_IDS["student"])
        ).all()
        bank_attempts = [attempt for attempt in attempts if attempt.assignment_id in {first["assignmentId"], second["assignmentId"]}]
        assert len(bank_attempts) == 2
        assert db.scalar(
            select(func.count(models.Event.id)).where(
                models.Event.type == "target.access_url.issued"
            )
        ) >= 2


def test_published_bank_item_must_be_unpublished_before_edit_or_delete(
    client: TestClient,
    teacher_token: str,
) -> None:
    open_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    due_at = datetime.now(timezone.utc) + timedelta(hours=1)
    item = _create_bank_item(
        client,
        teacher_token,
        key="bank-edit-published",
        publish=True,
        publishWindow={"openAt": open_at.isoformat(), "dueAt": due_at.isoformat()},
    )

    edit = client.patch(
        f"/api/v1/teacher/challenge-bank/{item['itemId']}",
        headers=auth(teacher_token),
        json={"summary": "已发布时不能直接修改。"},
    )
    assert edit.status_code == 409
    assert edit.json()["detail"]["code"] == "CHALLENGE_BANK_ITEM_PUBLISHED"

    delete = client.delete(
        f"/api/v1/teacher/challenge-bank/{item['itemId']}",
        headers=auth(teacher_token),
    )
    assert delete.status_code == 409
    assert delete.json()["detail"]["code"] == "CHALLENGE_BANK_ITEM_PUBLISHED"

    unpublish = client.post(
        f"/api/v1/teacher/challenge-bank/{item['itemId']}/unpublish",
        headers=auth(teacher_token),
    )
    assert unpublish.status_code == 200, unpublish.text

    edit_after_unpublish = client.patch(
        f"/api/v1/teacher/challenge-bank/{item['itemId']}",
        headers=auth(teacher_token),
        json={"summary": "下架后可以修改。"},
    )
    assert edit_after_unpublish.status_code == 200, edit_after_unpublish.text
    assert edit_after_unpublish.json()["summary"] == "下架后可以修改。"
