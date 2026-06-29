from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from urllib.request import Request, urlopen

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from cla import models
from cla.challenge_assets import store_generated_challenge_package
from cla.ids import new_id
from cla.main import create_app
from cla.security import create_dev_token
from cla.seed import DEV_IDS
from cla.settings import Settings

from test_terminal_vertical_slice import auth, local_sqli_target


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


def test_teacher_runs_three_layer_authoring_pipeline_before_bank_create(
    client: TestClient,
    teacher_token: str,
    student_token: str,
) -> None:
    forbidden = client.post(
        "/api/v1/teacher/challenge-bank/authoring-run",
        headers=auth(student_token),
        json={
            **_bank_payload(
                title="带 GUI 页面入口的 SQL 注入登录题",
                summary="学生需要通过页面和终端验证登录认证边界。",
                description="目标服务需要提供浏览器页面、登录接口和健康检查。",
                requirements="学生需要说明根因、验证过程和修复建议。",
                tags=["WEB", "SQL注入", "GUI页面"],
            ),
            "layerOnePrompt": "第一层 Agent 已确认教师希望创建带页面入口的 SQL 注入登录认证题。",
            "candidateContext": {"mode": "USE_EXISTING", "candidateIds": [DEV_IDS["challenge_version"]]},
            "publish": False,
            "publishWindow": None,
        },
    )
    assert forbidden.status_code == 403

    response = client.post(
        "/api/v1/teacher/challenge-bank/authoring-run",
        headers=auth(teacher_token),
        json={
            **_bank_payload(
                title="带 GUI 页面入口的 SQL 注入登录题",
                summary="学生需要通过页面和终端验证登录认证边界。",
                description="目标服务需要提供浏览器页面、登录接口和健康检查。",
                requirements="学生需要说明根因、验证过程和修复建议。",
                tags=["WEB", "SQL注入", "GUI页面"],
            ),
            "layerOnePrompt": "第一层 Agent 已确认教师希望创建带页面入口的 SQL 注入登录认证题。",
            "candidateContext": {"mode": "USE_EXISTING", "candidateIds": [DEV_IDS["challenge_version"]]},
            "publish": False,
            "publishWindow": None,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "PASS"
    assert body["runId"].startswith("arun_")
    assert "target/server.py" in body["generatedFiles"]
    assert "target/templates/index.html" in body["generatedFiles"]
    assert body["rubric"]["totalScore"] == 100
    assert len(body["rubric"]["criteria"]) == 4
    layers = [step["layer"] for step in body["steps"]]
    assert "L1_REQUIREMENT_AGENT" in layers
    assert "L2_BUILDER_AGENT" in layers
    assert "L3_TESTER_AGENT" in layers
    assert any(step["status"] == "NEEDS_REVISION" for step in body["steps"])
    assert any(check["id"] == "gui-entry" for check in body["validationChecks"])
    assert "第一层 Agent" in body["layerOnePrompt"]


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
    assert student_item["completionStatus"] == "INCOMPLETE"
    assert student_item["completed"] is False
    assert student_item["latestScore"] is None

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
    other_student_token: str,
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
    assert first["access"]["kind"] == "WEB_HTTP"
    assert first["access"]["url"].startswith("http://127.0.0.1:18080")
    assert first["access"]["displayUrl"] == first["access"]["url"]
    assert any("$TARGET_BASE_URL" in command for command in first["access"]["commands"])
    assert first["terminalUrl"] == f"/student/terminal?attemptId={first['attemptId']}"
    assert "route" not in first
    assert "sessiond" not in str(first).lower()

    with client.app.state.SessionLocal() as db:
        lab_before_edit = db.get(models.LabSession, first["sessionId"])
        attempt_before_edit = db.get(models.Attempt, first["attemptId"])
        assignment_before_edit = db.get(models.Assignment, first["assignmentId"])
        assert lab_before_edit is not None
        assert attempt_before_edit is not None
        assert assignment_before_edit is not None
        lab_route_before_edit = lab_before_edit.route_endpoint
        lab_status_before_edit = lab_before_edit.status
        attempt_assignment_before_edit = attempt_before_edit.assignment_id
        assignment_version_before_edit = assignment_before_edit.challenge_version_id

    edited_active = client.patch(
        f"/api/v1/teacher/challenge-bank/{item_one['itemId']}",
        headers=auth(teacher_token),
        json={
            "title": "第一题：认证绕过（课堂提示已更新）",
            "description": "教师更新了题面说明，但不会重建或替换学生已经开启的容器。",
            "openAt": (open_at - timedelta(minutes=10)).isoformat(),
            "dueAt": (due_at + timedelta(hours=1)).isoformat(),
        },
    )
    assert edited_active.status_code == 200, edited_active.text
    assert edited_active.json()["status"] == "PUBLISHED"
    assert edited_active.json()["challengeVersionId"] == item_one["challengeVersionId"]
    assert edited_active.json()["assignmentId"] == first["assignmentId"]
    assert edited_active.json()["title"] == "第一题：认证绕过（课堂提示已更新）"

    visible_after_teacher_edit = client.get(
        "/api/v1/student/challenge-bank", headers=auth(student_token)
    )
    assert visible_after_teacher_edit.status_code == 200, visible_after_teacher_edit.text
    first_item_after_teacher_edit = next(
        item
        for item in visible_after_teacher_edit.json()["items"]
        if item["itemId"] == item_one["itemId"]
    )
    assert first_item_after_teacher_edit["description"] == "教师更新了题面说明，但不会重建或替换学生已经开启的容器。"
    assert first_item_after_teacher_edit["hasEnvironment"] is True
    assert first_item_after_teacher_edit["sessionId"] == first["sessionId"]
    assert first_item_after_teacher_edit["sessionStatus"] == first["sessionStatus"]
    assert first_item_after_teacher_edit["terminalUrl"] == f"/student/terminal?attemptId={first['attemptId']}"
    assert first_item_after_teacher_edit["access"]["kind"] == "WEB_HTTP"
    assert first_item_after_teacher_edit["access"]["url"] == first["access"]["url"]

    ticket_after_teacher_edit = client.post(
        f"/api/v1/attempts/{first['attemptId']}/terminal-ticket",
        headers=auth(student_token),
    )
    assert ticket_after_teacher_edit.status_code == 200, ticket_after_teacher_edit.text

    with client.app.state.SessionLocal() as db:
        lab_after_edit = db.get(models.LabSession, first["sessionId"])
        attempt_after_edit = db.get(models.Attempt, first["attemptId"])
        assignment_after_edit = db.get(models.Assignment, first["assignmentId"])
        assert lab_after_edit is not None
        assert attempt_after_edit is not None
        assert assignment_after_edit is not None
        assert lab_after_edit.status == lab_status_before_edit
        assert lab_after_edit.route_endpoint == lab_route_before_edit
        assert attempt_after_edit.assignment_id == attempt_assignment_before_edit
        assert assignment_after_edit.challenge_version_id == assignment_version_before_edit

    before_submit = client.get("/api/v1/student/challenge-bank", headers=auth(student_token))
    assert before_submit.status_code == 200, before_submit.text
    first_item_before_submit = next(
        item for item in before_submit.json()["items"] if item["itemId"] == item_one["itemId"]
    )
    assert first_item_before_submit["completionStatus"] == "INCOMPLETE"
    assert first_item_before_submit["completed"] is False
    assert first_item_before_submit["latestScore"] is None
    assert first_item_before_submit["terminalUrl"] == f"/student/terminal?attemptId={first['attemptId']}"

    submitted = client.post(
        f"/api/v1/attempts/{first['attemptId']}/submit",
        headers={**auth(student_token), "If-Match": '"attempt-version-1"'},
        json={
            "answers": [
                {
                    "questionId": "root-cause",
                    "format": "MARKDOWN",
                    "content": "根因是输入信任边界处理错误，应使用参数化查询。",
                    "clientDraftId": "bank-draft-1",
                }
            ],
            "requestOracleCheck": False,
        },
    )
    assert submitted.status_code == 202, submitted.text
    after_submit = client.get("/api/v1/student/challenge-bank", headers=auth(student_token))
    assert after_submit.status_code == 200, after_submit.text
    first_item_after_submit = next(
        item for item in after_submit.json()["items"] if item["itemId"] == item_one["itemId"]
    )
    second_item_after_submit = next(
        item for item in after_submit.json()["items"] if item["itemId"] == item_two["itemId"]
    )
    assert first_item_after_submit["completionStatus"] == "COMPLETED"
    assert first_item_after_submit["completed"] is True
    assert first_item_after_submit["latestScore"] == 40.0
    assert first_item_after_submit["gradeRevisionId"]
    assert second_item_after_submit["completionStatus"] == "INCOMPLETE"
    assert second_item_after_submit["completed"] is False
    assert second_item_after_submit["latestScore"] is None

    other_student_start = client.post(
        f"/api/v1/student/challenge-bank/{item_one['itemId']}/start",
        headers=auth(other_student_token),
    )
    assert other_student_start.status_code == 202, other_student_start.text
    other = other_student_start.json()
    assert other["attemptId"] != first["attemptId"]
    assert other["sessionId"] != first["sessionId"]
    other_student_list = client.get("/api/v1/student/challenge-bank", headers=auth(other_student_token))
    assert other_student_list.status_code == 200, other_student_list.text
    other_student_item = next(
        item for item in other_student_list.json()["items"] if item["itemId"] == item_one["itemId"]
    )
    assert other_student_item["completed"] is False
    assert other_student_item["latestScore"] is None

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
    assert second["terminalUrl"] == f"/student/terminal?attemptId={second['attemptId']}"

    ticket = client.post(
        f"/api/v1/attempts/{first['attemptId']}/terminal-ticket",
        headers=auth(student_token),
    )
    assert ticket.status_code == 200, ticket.text
    destroy = client.delete(
        f"/api/v1/student/challenge-bank/{item_one['itemId']}/environment",
        headers=auth(student_token),
    )
    assert destroy.status_code == 200, destroy.text
    destroyed = destroy.json()
    assert destroyed["destroyed"] is True
    assert destroyed["attemptId"] == first["attemptId"]
    assert destroyed["sessionId"] == first["sessionId"]
    assert destroyed["sessionStatus"] == "DESTROYED"

    after_destroy = client.get("/api/v1/student/challenge-bank", headers=auth(student_token))
    assert after_destroy.status_code == 200, after_destroy.text
    destroyed_item = next(
        item for item in after_destroy.json()["items"] if item["itemId"] == item_one["itemId"]
    )
    assert destroyed_item["attemptId"] == first["attemptId"]
    assert destroyed_item["hasEnvironment"] is False
    assert destroyed_item["sessionId"] is None
    assert destroyed_item["targetUrl"] is None
    assert destroyed_item["terminalUrl"] is None
    assert destroyed_item["access"]["kind"] == "WEB_HTTP"
    assert destroyed_item["access"]["url"] is None

    restart_after_destroy = client.post(
        f"/api/v1/student/challenge-bank/{item_one['itemId']}/start",
        headers=auth(student_token),
    )
    assert restart_after_destroy.status_code == 202, restart_after_destroy.text
    restarted = restart_after_destroy.json()
    assert restarted["attemptId"] == first["attemptId"]
    assert restarted["sessionId"] != first["sessionId"]
    assert restarted["sessionEpoch"] == first["sessionEpoch"] + 1

    with client.app.state.SessionLocal() as db:
        attempts = db.scalars(
            select(models.Attempt).where(
                models.Attempt.student_id.in_([DEV_IDS["student"], DEV_IDS["other_student"]])
            )
        ).all()
        bank_attempts = [
            attempt
            for attempt in attempts
            if attempt.assignment_id in {first["assignmentId"], second["assignmentId"]}
        ]
        assert len(bank_attempts) == 3
        assert db.scalar(
            select(func.count(models.TerminalTicketNonce.nonce)).where(
                models.TerminalTicketNonce.attempt_id == first["attemptId"],
                models.TerminalTicketNonce.status == "REVOKED",
            )
        ) == 2
        assert db.scalar(
            select(func.count(models.LabSession.id)).where(
                models.LabSession.attempt_id == first["attemptId"],
                models.LabSession.status == "DESTROYED",
            )
        ) == 1
        assert db.scalar(
            select(func.count(models.Event.id)).where(
                models.Event.type == "target.access_url.issued"
            )
        ) >= 3
        assert db.scalar(
            select(func.count(models.Event.id)).where(models.Event.type == "lab.destroyed")
        ) == 1


def test_teacher_bank_student_real_sqli_solution_gets_oracle_score(settings: Settings) -> None:
    session_key = "bank-oracle-pass-key"
    with local_sqli_target(session_key) as target_base_url:
        app_settings = replace(
            settings,
            local_target_base_url=target_base_url,
            local_target_session_key=session_key,
        )
        with TestClient(create_app(app_settings)) as client:
            teacher_token = create_dev_token(app_settings, subject="teacher@example.edu", roles=["teacher"])
            student_token = create_dev_token(app_settings, subject="student@example.edu", roles=["student"])
            open_at = datetime.now(timezone.utc) - timedelta(minutes=5)
            due_at = datetime.now(timezone.utc) + timedelta(hours=2)
            item = _create_bank_item(
                client,
                teacher_token,
                key="bank-real-sqli-solved",
                title="真实 SQL 注入评分闭环",
                publish=True,
                publishWindow={"openAt": open_at.isoformat(), "dueAt": due_at.isoformat()},
            )

            started = client.post(
                f"/api/v1/student/challenge-bank/{item['itemId']}/start",
                headers=auth(student_token),
            )
            assert started.status_code == 202, started.text
            assert started.json()["targetUrl"] == f"{target_base_url}/"

            exploit = Request(
                f"{target_base_url}/login",
                data=b"username=alice&password=' OR '1'='1",
                headers={"content-type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with urlopen(exploit, timeout=5) as response:
                assert response.status == 200
                assert json.loads(response.read().decode())["role"] == "admin"

            submitted = client.post(
                f"/api/v1/attempts/{started.json()['attemptId']}/submit",
                headers={**auth(student_token), "If-Match": '"attempt-version-1"'},
                json={
                    "answers": [
                        {
                            "questionId": "root-cause",
                            "format": "MARKDOWN",
                            "content": "根因是登录接口直接拼接 SQL，成功绕过认证；修复应使用参数化查询。",
                        }
                    ],
                    "requestOracleCheck": True,
                },
            )
            assert submitted.status_code == 202, submitted.text

            bank = client.get("/api/v1/student/challenge-bank", headers=auth(student_token))
            assert bank.status_code == 200, bank.text
            solved = next(row for row in bank.json()["items"] if row["itemId"] == item["itemId"])
            assert solved["completed"] is True
            assert solved["latestScore"] == 100.0

            grade = client.get(
                f"/api/v1/attempts/{started.json()['attemptId']}/grade",
                headers=auth(student_token),
            )
            assert grade.status_code == 200, grade.text
            oracle = next(
                criterion for criterion in grade.json()["criteria"] if criterion["criterionId"] == "oracle-auth-bypass"
            )
            assert oracle["score"] == 60.0
            assert oracle["evidenceRefs"]


def test_teacher_bank_student_report_without_solution_does_not_get_oracle_score(
    settings: Settings,
) -> None:
    session_key = "bank-oracle-fail-key"
    with local_sqli_target(session_key) as target_base_url:
        app_settings = replace(
            settings,
            local_target_base_url=target_base_url,
            local_target_session_key=session_key,
        )
        with TestClient(create_app(app_settings)) as client:
            teacher_token = create_dev_token(app_settings, subject="teacher@example.edu", roles=["teacher"])
            student_token = create_dev_token(app_settings, subject="student@example.edu", roles=["student"])
            open_at = datetime.now(timezone.utc) - timedelta(minutes=5)
            due_at = datetime.now(timezone.utc) + timedelta(hours=2)
            item = _create_bank_item(
                client,
                teacher_token,
                key="bank-real-sqli-unsolved",
                title="真实 SQL 注入未完成评分闭环",
                publish=True,
                publishWindow={"openAt": open_at.isoformat(), "dueAt": due_at.isoformat()},
            )
            started = client.post(
                f"/api/v1/student/challenge-bank/{item['itemId']}/start",
                headers=auth(student_token),
            )
            assert started.status_code == 202, started.text

            submitted = client.post(
                f"/api/v1/attempts/{started.json()['attemptId']}/submit",
                headers={**auth(student_token), "If-Match": '"attempt-version-1"'},
                json={
                    "answers": [
                        {
                            "questionId": "root-cause",
                            "format": "MARKDOWN",
                            "content": "根因是输入信任边界错误，应使用参数化查询。",
                        }
                    ],
                    "requestOracleCheck": True,
                },
            )
            assert submitted.status_code == 202, submitted.text

            grade = client.get(
                f"/api/v1/attempts/{started.json()['attemptId']}/grade",
                headers=auth(student_token),
            )
            assert grade.status_code == 200, grade.text
            body = grade.json()
            assert body["totalScore"] == 40.0
            oracle = next(
                criterion for criterion in body["criteria"] if criterion["criterionId"] == "oracle-auth-bypass"
            )
            assert oracle["score"] == 0.0
            assert oracle["evidenceRefs"]


def test_student_access_distinguishes_reverse_download_target(
    client: TestClient,
    teacher_token: str,
    student_token: str,
) -> None:
    with client.app.state.SessionLocal() as db:
        reverse_challenge = models.Challenge(
            id="chal_reverse_access",
            tenant_id=DEV_IDS["tenant"],
            slug="reverse-access-demo",
            title="逆向目标文件入口验证",
            category="REVERSE",
            owner_id=DEV_IDS["teacher"],
        )
        reverse_version = models.ChallengeVersion(
            id="cv_reverse_access_1",
            challenge_id=reverse_challenge.id,
            semver="1.0.0",
            status="PUBLISHED",
            manifest_json={
                "category": "REVERSE",
                "workspaceType": "TERMINAL",
                "studentAccess": {
                    "kind": "DOWNLOAD_FILE",
                    "label": "目标文件",
                    "downloadPath": "target/challenge.c",
                    "commands": ["file ./challenge", "strings ./challenge | head"],
                },
            },
            artifact_digest="sha256:reverse-access-demo",
            risk_tier=1,
            created_by=DEV_IDS["teacher"],
        )
        stored = store_generated_challenge_package(
            client.app.state.settings,
            tenant_id=DEV_IDS["tenant"],
            slug=reverse_challenge.slug,
            semver=reverse_version.semver,
            files={
                "manifest.yaml": "kind: CyberChallenge\n",
                "target/challenge.c": "int main(void) { return 0; }\n",
            },
        )
        db.add_all(
            [
                reverse_challenge,
                reverse_version,
                models.ChallengeArtifact(
                    id=new_id("casset"),
                    tenant_id=DEV_IDS["tenant"],
                    challenge_id=reverse_challenge.id,
                    version_id=reverse_version.id,
                    artifact_type="generated-challenge-package",
                    object_ref=stored.object_ref,
                    sha256=stored.sha256,
                    byte_count=stored.byte_count,
                    metadata_json=stored.metadata,
                ),
            ]
        )
        db.commit()

    open_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    due_at = datetime.now(timezone.utc) + timedelta(hours=1)
    published_item = _create_bank_item(
        client,
        teacher_token,
        key="bank-reverse-download",
        challengeVersionId="cv_reverse_access_1",
        title="逆向目标文件入口验证",
        tags=["REVERSE", "文件分析"],
        publish=True,
        publishWindow={"openAt": open_at.isoformat(), "dueAt": due_at.isoformat()},
    )

    visible = client.get("/api/v1/student/challenge-bank", headers=auth(student_token))
    assert visible.status_code == 200, visible.text
    reverse_item = next(
        row for row in visible.json()["items"] if row["itemId"] == published_item["itemId"]
    )
    access = reverse_item["access"]
    assert access["kind"] == "DOWNLOAD_FILE"
    assert access["url"].endswith(f"/student/challenge-bank/{published_item['itemId']}/artifact/download")
    assert reverse_item["targetUrl"] is None
    assert "file ./challenge" in access["commands"]

    download = client.get(access["url"], headers=auth(student_token))
    assert download.status_code == 200, download.text
    assert "challenge.c" in download.headers["content-disposition"]
    assert b"int main" in download.content

    start = client.post(
        f"/api/v1/student/challenge-bank/{published_item['itemId']}/start",
        headers=auth(student_token),
    )
    assert start.status_code == 202, start.text
    assert start.json()["targetUrl"] is None
    assert start.json()["access"]["kind"] == "DOWNLOAD_FILE"


def test_published_bank_item_can_update_display_fields_without_unpublishing(
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
    assert item["status"] == "PUBLISHED"
    assert item["actions"]["canEdit"] is True
    assert item["actions"]["canDelete"] is False

    new_open_at = open_at + timedelta(minutes=10)
    new_due_at = due_at + timedelta(hours=2)
    edit = client.patch(
        f"/api/v1/teacher/challenge-bank/{item['itemId']}",
        headers=auth(teacher_token),
        json={
            "title": "已发布题目的展示标题可直接修改",
            "summary": "已发布时可以直接修改展示摘要。",
            "description": "这只影响学生看到的题面说明，不会改变 ChallengeVersion、镜像或环境代码。",
            "requirements": "仍然使用同一个已经发布的题目环境完成。",
            "tags": ["WEB", "展示信息"],
            "openAt": new_open_at.isoformat(),
            "dueAt": new_due_at.isoformat(),
        },
    )
    assert edit.status_code == 200, edit.text
    edited = edit.json()
    assert edited["status"] == "PUBLISHED"
    assert edited["title"] == "已发布题目的展示标题可直接修改"
    assert edited["summary"] == "已发布时可以直接修改展示摘要。"
    assert edited["tags"] == ["WEB", "展示信息"]
    assert edited["challengeVersionId"] == item["challengeVersionId"]
    assert edited["assignmentId"] == item["assignmentId"]

    with client.app.state.SessionLocal() as db:
        assignment = db.get(models.Assignment, item["assignmentId"])
        assert assignment is not None
        assert assignment.title == "已发布题目的展示标题可直接修改"
        assert assignment.challenge_version_id == item["challengeVersionId"]
        assert assignment.open_at == new_open_at.replace(tzinfo=None)
        assert assignment.due_at == new_due_at.replace(tzinfo=None)

    new_course = client.post(
        "/api/v1/courses",
        headers={**auth(teacher_token), "Idempotency-Key": "bank-edit-display-course"},
        json={"code": "WEBSEC-BANK-EDIT", "title": "题库展示信息编辑课", "term": "2026-S"},
    )
    assert new_course.status_code == 201, new_course.text
    move_course = client.patch(
        f"/api/v1/teacher/challenge-bank/{item['itemId']}",
        headers=auth(teacher_token),
        json={"courseId": new_course.json()["courseId"]},
    )
    assert move_course.status_code == 200, move_course.text
    assert move_course.json()["courseId"] == new_course.json()["courseId"]
    assert move_course.json()["challengeVersionId"] == item["challengeVersionId"]
    assert move_course.json()["assignmentId"] == item["assignmentId"]
    with client.app.state.SessionLocal() as db:
        moved_assignment = db.get(models.Assignment, item["assignmentId"])
        assert moved_assignment is not None
        assert moved_assignment.course_id == new_course.json()["courseId"]
        assert moved_assignment.challenge_version_id == item["challengeVersionId"]

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
