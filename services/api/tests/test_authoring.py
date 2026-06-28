from __future__ import annotations

from pathlib import Path
import tarfile

from sqlalchemy import func, select
from fastapi.testclient import TestClient

from cla import agent_runtime
from cla import models
from cla.main import create_app
from cla.security import create_dev_token
from cla.seed import DEV_IDS
from cla.settings import Settings

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
    proposal = body["authoringProposal"]
    assert proposal["mode"] == "USE_EXISTING"
    assert proposal["challengeVersionId"] == DEV_IDS["challenge_version"]
    assert proposal["title"] == "SQL 注入登录认证绕过实践"
    assert "UNKNOWN" not in proposal["tags"]
    assert "教师需求" not in proposal["description"]
    assert "教师补充要求" not in proposal["requirements"]
    assert proposal["requiresCustomGeneration"] is False

    with client.app.state.SessionLocal() as db:
        assert db.scalar(select(func.count(models.AgentRun.id))) == 0
        audit = db.scalar(
            select(models.AuditLog).where(
                models.AuditLog.action == "challenge.draft.candidates.read",
                models.AuditLog.resource_id == draft["draftId"],
            )
        )
        assert audit is not None


def test_teacher_chinese_sqli_brief_is_rewritten_into_student_facing_proposal(
    client: TestClient,
    teacher_token: str,
) -> None:
    brief = "创建一个经典的 SQL 注入题目。"
    draft_response = client.post(
        "/api/v1/challenge-drafts",
        headers={**auth(teacher_token), "Idempotency-Key": "chinese-sqli-authoring"},
        json={
            "courseId": DEV_IDS["course"],
            "brief": brief,
            "constraints": {"internet": False, "maxDifficulty": 3, "workspaceType": "TERMINAL"},
        },
    )
    assert draft_response.status_code == 201, draft_response.text
    draft = draft_response.json()
    assert draft["courseIntent"]["category"] == "WEB"
    assert draft["courseIntent"]["target"] in {"SQLI", "SQLI_AUTHENTICATION", "INPUT_TRUST_BOUNDARY"}
    assert "category" not in draft["courseIntent"]["uncertainFields"]

    response = client.get(draft["candidatesUrl"], headers=auth(teacher_token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["candidates"]
    assert body["candidates"][0]["candidateId"] == DEV_IDS["challenge_version"]

    proposal = body["authoringProposal"]
    assert proposal["mode"] == "USE_EXISTING"
    assert proposal["challengeVersionId"] == DEV_IDS["challenge_version"]
    assert proposal["title"] == "SQL 注入登录认证绕过实践"
    assert proposal["title"] != brief
    assert "创建一个" not in proposal["title"]
    assert "UNKNOWN" not in proposal["tags"]
    assert "SQL注入" in proposal["tags"]
    assert "题库" in proposal["agentMessage"]
    assert brief not in proposal["description"]
    assert brief not in proposal["requirements"]
    assert "教师需求" not in proposal["description"]
    assert "教师补充要求" not in proposal["requirements"]
    assert "username" in proposal["description"]
    assert "参数化查询" in proposal["requirements"]


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


def test_registry_import_searches_and_records_artifacts(
    client: TestClient,
    teacher_token: str,
    student_token: str,
) -> None:
    forbidden = client.get("/api/v1/challenge-registry", headers=auth(student_token))
    assert forbidden.status_code == 403

    before = client.get("/api/v1/challenge-registry?query=SQLi", headers=auth(teacher_token))
    assert before.status_code == 200, before.text
    assert before.json()["versions"]

    imported = client.post("/api/v1/challenge-registry/import-local", headers=auth(teacher_token))
    assert imported.status_code == 202, imported.text
    body = imported.json()
    assert body["imported"]
    assert body["skipped"] == []

    searched = client.get("/api/v1/challenge-registry?query=认证 登录", headers=auth(teacher_token))
    assert searched.status_code == 200, searched.text
    registry = searched.json()
    assert registry["retrieval"]["mode"] == "hard-filter+bm25"
    assert registry["versions"]
    assert registry["versions"][0]["artifactCount"] >= 1
    assert registry["versions"][0]["latestArtifactRef"].startswith("local://challenge-artifacts/")

    with client.app.state.SessionLocal() as db:
        assert db.scalar(select(func.count(models.ChallengeArtifact.id))) >= 1


def test_authoritative_blueprint_catalog_imports_large_database(
    client: TestClient,
    teacher_token: str,
    student_token: str,
) -> None:
    forbidden = client.post("/api/v1/challenge-registry/import-blueprints", headers=auth(student_token))
    assert forbidden.status_code == 403

    imported = client.post("/api/v1/challenge-registry/import-blueprints", headers=auth(teacher_token))
    assert imported.status_code == 202, imported.text
    body = imported.json()
    assert body["skipped"] == []
    assert len(body["imported"]) == 300
    assert body["summary"]["valid"] is True
    assert body["summary"]["total"] == 300
    assert body["summary"]["counts"] == {
        "WEB": 50,
        "REVERSE": 50,
        "PWN": 50,
        "CRYPTO": 50,
        "FORENSICS": 50,
        "MISC": 50,
    }

    validation = client.get(
        f"/api/v1/challenge-versions/{body['imported'][0]['challengeVersionId']}/validation",
        headers=auth(teacher_token),
    )
    assert validation.status_code == 200, validation.text
    assert validation.json()["overallStatus"] == "WARN"

    with client.app.state.SessionLocal() as db:
        counts = dict(
            db.execute(
                select(models.Challenge.category, func.count(models.ChallengeVersion.id))
                .join(models.ChallengeVersion, models.ChallengeVersion.challenge_id == models.Challenge.id)
                .where(models.ChallengeVersion.status == "BLUEPRINT")
                .group_by(models.Challenge.category)
            ).all()
        )
        assert counts == {
            "CRYPTO": 50,
            "FORENSICS": 50,
            "MISC": 50,
            "PWN": 50,
            "REVERSE": 50,
            "WEB": 50,
        }
        assert (
            db.scalar(
                select(func.count(models.ChallengeArtifact.id)).where(
                    models.ChallengeArtifact.artifact_type == "blueprint-catalog-entry"
                )
            )
            == 300
        )


def test_authoring_retrieves_blueprints_and_builds_composition_plan(
    client: TestClient,
    teacher_token: str,
) -> None:
    imported = client.post("/api/v1/challenge-registry/import-blueprints", headers=auth(teacher_token))
    assert imported.status_code == 202, imported.text

    draft_response = client.post(
        "/api/v1/challenge-drafts",
        headers={**auth(teacher_token), "Idempotency-Key": "blueprint-compose-draft"},
        json={
            "courseId": DEV_IDS["course"],
            "brief": (
                "需要一个终端 Web 组合题，覆盖访问控制、认证和 API 越权，"
                "学生使用 curl 与 python 完成验证并解释业务影响，预计 90 分钟。"
            ),
            "constraints": {
                "internet": False,
                "maxDifficulty": 5,
                "workspaceType": "TERMINAL",
            },
        },
    )
    assert draft_response.status_code == 201, draft_response.text
    draft = draft_response.json()
    assert draft["courseIntent"]["category"] == "WEB"

    response = client.get(draft["candidatesUrl"], headers=auth(teacher_token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["candidates"]
    assert body["compositionPlan"]["mode"] in {"compose-existing-blueprints", "single-best-candidate"}
    assert body["compositionPlan"]["candidateIds"]
    assert any("source-backed-blueprint" in candidate["matchReasons"] for candidate in body["candidates"])
    assert any(candidate["retrievalSignals"].get("sourceRefs") for candidate in body["candidates"])

    reverse_draft = client.post(
        "/api/v1/challenge-drafts",
        headers={**auth(teacher_token), "Idempotency-Key": "reverse-category-draft"},
        json={
            "courseId": DEV_IDS["course"],
            "brief": "需要一个逆向 crackme 题，学生使用 strings、objdump、gdb 还原校验逻辑。",
            "constraints": {"internet": False, "maxDifficulty": 5, "workspaceType": "TERMINAL"},
        },
    )
    assert reverse_draft.status_code == 201, reverse_draft.text
    assert reverse_draft.json()["courseIntent"]["category"] == "REVERSE"


def test_authoring_handles_common_security_briefs_with_target_specific_proposals(
    client: TestClient,
    teacher_token: str,
) -> None:
    imported = client.post("/api/v1/challenge-registry/import-blueprints", headers=auth(teacher_token))
    assert imported.status_code == 202, imported.text

    cases = [
        {
            "key": "brief-xss",
            "brief": "创建一个经典的 XSS 漏洞题目",
            "category": "WEB",
            "target": "XSS",
            "title": "XSS 输出编码与脚本注入实践",
            "tag": "XSS",
            "candidate": "web_xss",
            "descriptionTerm": "输出编码",
        },
        {
            "key": "brief-reverse-medium",
            "brief": "创建一个经典的逆向工程中等难度题目",
            "category": "REVERSE",
            "target": "BINARY_ANALYSIS",
            "difficulty": 3,
            "title": "逆向校验逻辑分析实践",
            "tag": "二进制分析",
            "candidate": "reverse",
            "descriptionTerm": "objdump",
        },
        {
            "key": "brief-pwn-integer",
            "brief": "创建一个整数类型溢出的 Pwn 题目",
            "category": "PWN",
            "target": "INTEGER_OVERFLOW",
            "title": "Pwn 整数溢出利用实践",
            "tag": "整数溢出",
            "candidate": "pwn_integer",
            "descriptionTerm": "整数",
        },
        {
            "key": "brief-sqli-hard-deadline",
            "brief": "创建一个难度较高的 SQL 注入题目，时间截止到下周。",
            "category": "WEB",
            "target": "SQLI",
            "difficulty": 4,
            "title": "SQL 注入登录认证绕过实践",
            "tag": "SQL注入",
            "candidate": "web_sqli",
            "descriptionTerm": "输入信任边界",
        },
    ]
    for case in cases:
        draft_response = client.post(
            "/api/v1/challenge-drafts",
            headers={**auth(teacher_token), "Idempotency-Key": case["key"]},
            json={
                "courseId": DEV_IDS["course"],
                "brief": case["brief"],
                "constraints": {"internet": False, "maxDifficulty": 5, "workspaceType": "TERMINAL"},
            },
        )
        assert draft_response.status_code == 201, draft_response.text
        draft = draft_response.json()
        assert draft["courseIntent"]["category"] == case["category"]
        assert draft["courseIntent"]["target"] == case["target"]
        if "difficulty" in case:
            assert draft["courseIntent"]["difficulty"] == case["difficulty"]

        candidates = client.get(draft["candidatesUrl"], headers=auth(teacher_token))
        assert candidates.status_code == 200, candidates.text
        body = candidates.json()
        assert body["candidates"]
        assert case["candidate"] in body["candidates"][0]["candidateId"]
        proposal = body["authoringProposal"]
        assert proposal["mode"] in {"USE_EXISTING", "COMPOSE_EXISTING"}
        assert proposal["title"] == case["title"]
        assert case["tag"] in proposal["tags"]
        assert "UNKNOWN" not in proposal["tags"]
        assert case["brief"] not in proposal["description"]
        assert case["descriptionTerm"] in proposal["description"]
        assert "教师需求" not in proposal["description"]


def test_authoring_agent_preserves_multiturn_context_and_uses_latest_updates(
    client: TestClient,
    teacher_token: str,
) -> None:
    imported = client.post("/api/v1/challenge-registry/import-blueprints", headers=auth(teacher_token))
    assert imported.status_code == 202, imported.text

    conversation = [
        {"role": "teacher", "content": "出一道经典的字符串相关漏洞的 Pwn 题，难度中等。"},
        {"role": "agent", "content": "已生成初版题面。"},
        {"role": "teacher", "content": "时间持续一年。"},
    ]
    brief = "\n".join(
        f"{item['role']}：{item['content']}" for item in conversation if item["role"] == "teacher"
    )
    draft_response = client.post(
        "/api/v1/challenge-drafts",
        headers={**auth(teacher_token), "Idempotency-Key": "multiturn-pwn-year"},
        json={
            "courseId": DEV_IDS["course"],
            "brief": brief,
            "constraints": {
                "internet": False,
                "maxDifficulty": 5,
                "workspaceType": "TERMINAL",
                "authoringConversation": conversation,
                "latestTeacherMessage": "时间持续一年。",
            },
        },
    )
    assert draft_response.status_code == 201, draft_response.text
    draft = draft_response.json()
    assert draft["courseIntent"]["category"] == "PWN"
    assert draft["courseIntent"]["target"] == "PWN_FORMAT"
    assert draft["courseIntent"]["difficulty"] == 3

    candidates = client.get(draft["candidatesUrl"], headers=auth(teacher_token))
    assert candidates.status_code == 200, candidates.text
    body = candidates.json()
    assert body["candidates"]
    assert "pwn_format" in body["candidates"][0]["candidateId"]
    proposal = body["authoringProposal"]
    assert "最新要求" in proposal["agentMessage"]
    assert "CourseIntent" not in proposal["agentMessage"]
    assert "不会直接复用教师原句" not in proposal["agentMessage"]

    followup_conversation = [
        {"role": "teacher", "content": "出一道经典的字符串相关漏洞的 Pwn 题，难度中等。"},
        {"role": "agent", "content": proposal["agentMessage"]},
        {"role": "teacher", "content": "难度改成简单一些，仍然保持 Pwn 字符串方向。"},
    ]
    followup = client.post(
        "/api/v1/challenge-drafts",
        headers={**auth(teacher_token), "Idempotency-Key": "multiturn-pwn-easy"},
        json={
            "courseId": DEV_IDS["course"],
            "brief": "\n".join(item["content"] for item in followup_conversation if item["role"] == "teacher"),
            "constraints": {
                "internet": False,
                "maxDifficulty": 5,
                "workspaceType": "TERMINAL",
                "authoringConversation": followup_conversation,
                "latestTeacherMessage": "难度改成简单一些，仍然保持 Pwn 字符串方向。",
            },
        },
    )
    assert followup.status_code == 201, followup.text
    followup_intent = followup.json()["courseIntent"]
    assert followup_intent["category"] == "PWN"
    assert followup_intent["target"] == "PWN_FORMAT"
    assert followup_intent["difficulty"] == 1

    preserved_intent = {
        "category": "WEB",
        "target": "SQLI",
        "difficulty": 5,
        "expectedMinutes": 150,
        "workspaceType": "TERMINAL",
        "isolationTier": 1,
        "allowedTools": ["curl", "python"],
        "learningObjectives": ["identify-input-trust-boundary"],
        "uncertainFields": [],
        "confidence": 0.93,
    }
    preserve_conversation = [
        {"role": "teacher", "content": "创建一个难度较高的 SQL 注入题目。"},
        {"role": "agent", "content": "已生成高难 SQL 注入题面。"},
        {"role": "teacher", "content": "标题改成 SQL 注入下周截止专项。标签增加 课程考核。"},
    ]
    preserved = client.post(
        "/api/v1/challenge-drafts",
        headers={**auth(teacher_token), "Idempotency-Key": "multiturn-preserve-intent"},
        json={
            "courseId": DEV_IDS["course"],
            "brief": "\n".join(item["content"] for item in preserve_conversation if item["role"] == "teacher"),
            "constraints": {
                "internet": False,
                "maxDifficulty": 5,
                "workspaceType": "TERMINAL",
                "authoringConversation": preserve_conversation,
                "latestTeacherMessage": "标题改成 SQL 注入下周截止专项。标签增加 课程考核。",
                "currentCourseIntent": preserved_intent,
            },
        },
    )
    assert preserved.status_code == 201, preserved.text
    preserved_body = preserved.json()["courseIntent"]
    assert preserved_body["category"] == "WEB"
    assert preserved_body["target"] == "SQLI"
    assert preserved_body["difficulty"] == 5
    assert preserved_body["expectedMinutes"] == 150


def test_model_parser_gui_tools_and_higher_isolation_still_retrieve_blueprints(
    tmp_path,
    monkeypatch,
) -> None:
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        dev_mode=True,
        dev_oidc_secret="test-oidc-secret",
        terminal_ticket_secret="test-terminal-secret",
        oracle_shared_secret="test-oracle-secret",
        internal_service_token="test-internal",
        gateway_url="ws://gateway.test/ws/terminal",
        transcript_object_root=str(tmp_path / "transcripts"),
        challenge_artifact_object_root=str(tmp_path / "challenge-artifacts"),
        transcript_encryption_key="test-transcript-key",
        agent_runtime_enabled=True,
        model_base_url="https://model.example/v1",
        model_name="deepseekv4flash",
        model_api_key="test-key",
    )

    def fake_parse(*args, brief: str, **kwargs) -> agent_runtime.AgentModelResult:
        if "XSS" in brief:
            output = {
                "category": "WEB",
                "target": "XSS",
                "difficulty": 2,
                "expectedMinutes": 30,
                "workspaceType": "TERMINAL",
                "isolationTier": 3,
                "allowedTools": ["Firefox", "Burp Suite", "python", "pwntools"],
                "learningObjectives": ["XSS", "OUTPUT_ENCODING"],
                "uncertainFields": [],
                "confidence": 0.88,
            }
        elif "逆向" in brief:
            output = {
                "category": "REVERSE",
                "target": "REV_UNK",
                "difficulty": 3,
                "expectedMinutes": 45,
                "workspaceType": "TERMINAL",
                "isolationTier": 3,
                "allowedTools": ["IDA Pro", "Ghidra", "gdb", "pwntools"],
                "learningObjectives": ["逆向分析", "算法还原"],
                "uncertainFields": [],
                "confidence": 0.82,
            }
        else:
            output = {
                "category": "PWN",
                "target": "INTEGER_OVERFLOW",
                "difficulty": 3,
                "expectedMinutes": 60,
                "workspaceType": "TERMINAL",
                "isolationTier": 3,
                "allowedTools": ["pwntools", "gdb", "objdump", "readelf", "strings"],
                "learningObjectives": ["INTEGER_OVERFLOW"],
                "uncertainFields": [],
                "confidence": 0.81,
            }
        return agent_runtime.AgentModelResult(
            output=output,
            usage={"provider": "openai-compatible", "model": "deepseekv4flash"},
        )

    monkeypatch.setattr(agent_runtime, "parse_course_intent_with_model", fake_parse)

    client = TestClient(create_app(settings))
    teacher_token = create_dev_token(settings, subject="teacher@example.edu", roles=["teacher"])
    imported = client.post("/api/v1/challenge-registry/import-blueprints", headers=auth(teacher_token))
    assert imported.status_code == 202, imported.text

    cases = [
        (
            "model-xss",
            "创建一个经典的 XSS 漏洞题目",
            "XSS",
            "web_xss",
            {"firefox", "burp suite", "pwntools"},
        ),
        (
            "model-reverse",
            "创建一个经典的逆向工程中等难度题目",
            "BINARY_ANALYSIS",
            "reverse",
            {"ida pro", "ghidra", "pwntools"},
        ),
        (
            "model-pwn-int",
            "创建一个整数类型溢出的 Pwn 题目",
            "INTEGER_OVERFLOW",
            "pwn_integer",
            {"objdump", "readelf", "strings"},
        ),
    ]
    for key, brief, expected_target, expected_candidate, forbidden_tools in cases:
        draft_response = client.post(
            "/api/v1/challenge-drafts",
            headers={**auth(teacher_token), "Idempotency-Key": key},
            json={
                "courseId": DEV_IDS["course"],
                "brief": brief,
                "constraints": {"internet": False, "maxDifficulty": 5, "workspaceType": "TERMINAL"},
            },
        )
        assert draft_response.status_code == 201, draft_response.text
        draft = draft_response.json()
        assert draft["courseIntent"]["target"] == expected_target
        normalized_tools = {tool.lower() for tool in draft["courseIntent"]["allowedTools"]}
        assert not (normalized_tools & forbidden_tools)

        candidates = client.get(draft["candidatesUrl"], headers=auth(teacher_token))
        assert candidates.status_code == 200, candidates.text
        body = candidates.json()
        assert body["candidates"]
        assert expected_candidate in body["candidates"][0]["candidateId"]
        assert body["authoringProposal"]["mode"] in {"USE_EXISTING", "COMPOSE_EXISTING"}
        assert body["authoringProposal"]["requiresCustomGeneration"] is False


def test_authoring_common_security_topic_matrix_retrieves_blueprints(
    client: TestClient,
    teacher_token: str,
) -> None:
    imported = client.post("/api/v1/challenge-registry/import-blueprints", headers=auth(teacher_token))
    assert imported.status_code == 202, imported.text

    cases = [
        ("matrix-web-sqli", "创建一个 SQL 注入联合查询枚举题目", "WEB", "sqli", "SQL 注入"),
        ("matrix-web-xss", "创建一个 XSS DOM Source Sink 题目", "WEB", "xss", "XSS"),
        ("matrix-web-auth", "创建一个认证与会话逻辑弱重置令牌题目", "WEB", "auth", "认证"),
        ("matrix-web-access", "创建一个访问控制 IDOR 横向越权题目", "WEB", "access", "访问控制"),
        ("matrix-web-ssrf", "创建一个 SSRF 云元数据探测题目", "WEB", "ssrf", "SSRF"),
        ("matrix-web-file", "创建一个文件上传路径遍历题目", "WEB", "file", "文件"),
        ("matrix-web-ssti", "创建一个 SSTI 模板注入题目", "WEB", "ssti", "模板"),
        ("matrix-web-xxe", "创建一个 XXE XML 外部实体题目", "WEB", "xxe", "XML"),
        ("matrix-web-race", "创建一个 Web 缓存投毒和业务逻辑竞态题目", "WEB", "race", "竞态"),
        ("matrix-web-api", "创建一个 GraphQL API 过度暴露题目", "WEB", "api", "API"),
        ("matrix-reverse-strings", "创建一个逆向字符串 XOR 恢复题目", "REVERSE", "reverse_strings", "逆向"),
        ("matrix-reverse-keygen", "创建一个 crackme keygen 线性校验题目", "REVERSE", "reverse_keygen", "逆向"),
        ("matrix-reverse-antidebug", "创建一个反调试 ptrace 检测逆向题目", "REVERSE", "reverse_antidebug", "逆向"),
        ("matrix-reverse-packing", "创建一个加壳自解密逆向题目", "REVERSE", "reverse_packing", "逆向"),
        ("matrix-reverse-cff", "创建一个控制流混淆逆向题目", "REVERSE", "reverse_cff", "逆向"),
        ("matrix-reverse-vm", "创建一个虚拟机字节码逆向题目", "REVERSE", "reverse_vm", "逆向"),
        ("matrix-reverse-crypto", "创建一个逆向中的弱 PRNG 密码误用题目", "REVERSE", "reverse_crypto", "逆向"),
        ("matrix-reverse-mobile", "创建一个移动端 DEX 控制流逆向题目", "REVERSE", "reverse_mobile", "逆向"),
        ("matrix-reverse-stripped", "创建一个 Go Rust 静态链接无符号逆向题目", "REVERSE", "reverse_stripped", "逆向"),
        ("matrix-reverse-embedded", "创建一个 MSP430 固件嵌入式逆向题目", "REVERSE", "reverse_embedded", "逆向"),
        ("matrix-pwn-stack", "创建一个 Pwn 栈溢出 ret2win 题目", "PWN", "pwn_stack", "内存"),
        ("matrix-pwn-rop", "创建一个 ROP ret2libc Pwn 题目", "PWN", "pwn_rop", "内存"),
        ("matrix-pwn-format", "创建一个格式化字符串任意地址写 Pwn 题目", "PWN", "pwn_format", "内存"),
        ("matrix-pwn-heap", "创建一个堆利用 tcache poisoning Pwn 题目", "PWN", "pwn_heap", "内存"),
        ("matrix-pwn-uaf", "创建一个 Use After Free 对象复用 Pwn 题目", "PWN", "pwn_uaf", "内存"),
        ("matrix-pwn-integer", "创建一个整数溢出乘法边界 Pwn 题目", "PWN", "pwn_integer", "整数"),
        ("matrix-pwn-shellcode", "创建一个 shellcode seccomp ORW Pwn 题目", "PWN", "pwn_shellcode", "内存"),
        ("matrix-pwn-pie", "创建一个 PIE Canary NX 绕过 Pwn 题目", "PWN", "pwn_pie", "内存"),
        ("matrix-pwn-sandbox", "创建一个 chroot 沙箱逃逸 Pwn 题目", "PWN", "pwn_sandbox", "内存"),
        ("matrix-pwn-kernelish", "创建一个 ioctl 模型内核风格用户态 Pwn 题目", "PWN", "pwn_kernelish", "内存"),
        ("matrix-crypto-encoding", "创建一个密码学 Base64 多层编码题目", "CRYPTO", "crypto_encoding", "密码"),
        ("matrix-crypto-classical", "创建一个凯撒移位古典密码题目", "CRYPTO", "crypto_classical", "密码"),
        ("matrix-crypto-xor", "创建一个重复密钥 XOR 密码题目", "CRYPTO", "crypto_xor", "密码"),
        ("matrix-crypto-hash", "创建一个哈希长度扩展攻击题目", "CRYPTO", "crypto_hash", "密码"),
        ("matrix-crypto-symmetric", "创建一个 AES ECB 模式识别题目", "CRYPTO", "crypto_symmetric", "密码"),
        ("matrix-crypto-padding", "创建一个 CBC Padding Oracle 题目", "CRYPTO", "crypto_padding", "密码"),
        ("matrix-crypto-rsa", "创建一个 RSA 小指数广播题目", "CRYPTO", "crypto_rsa", "密码"),
        ("matrix-crypto-dh", "创建一个 Diffie-Hellman 小子群攻击题目", "CRYPTO", "crypto_dh", "密码"),
        ("matrix-crypto-ecc", "创建一个 ECC 椭圆曲线 ECDSA Nonce 重用题目", "CRYPTO", "crypto_ecc", "密码"),
        ("matrix-crypto-prng", "创建一个随机数 PRNG LCG 参数恢复题目", "CRYPTO", "crypto_prng", "密码"),
        ("matrix-forensics-file", "创建一个文件格式魔数修复取证题目", "FORENSICS", "forensics_file", "取证"),
        ("matrix-forensics-image", "创建一个图片 LSB 隐写取证题目", "FORENSICS", "forensics_image", "取证"),
        ("matrix-forensics-pcap", "创建一个 PCAP HTTP 会话重组流量取证题目", "FORENSICS", "forensics_pcap", "取证"),
        ("matrix-forensics-memory", "创建一个 Volatility 内存取证进程列表题目", "FORENSICS", "forensics_memory", "取证"),
        ("matrix-forensics-disk", "创建一个磁盘文件系统删除文件恢复取证题目", "FORENSICS", "forensics_disk", "取证"),
        ("matrix-forensics-logs", "创建一个日志时间线分析题目", "FORENSICS", "forensics_logs", "取证"),
        ("matrix-forensics-malware", "创建一个恶意样本字符串 IOC 静态取证题目", "FORENSICS", "forensics_malware", "取证"),
        ("matrix-forensics-audio", "创建一个音频频谱图隐藏取证题目", "FORENSICS", "forensics_audio", "取证"),
        ("matrix-forensics-osint", "创建一个 OSINT 图片地理线索取证题目", "FORENSICS", "forensics_osint", "取证"),
        ("matrix-forensics-document", "创建一个 PDF 文档元数据取证题目", "FORENSICS", "forensics_document", "取证"),
        ("matrix-misc-linux", "创建一个 Linux 隐藏文件通用技能题目", "MISC", "misc_linux", "通用"),
        ("matrix-misc-shell", "创建一个 Shell grep sed awk 管道题目", "MISC", "misc_shell", "通用"),
        ("matrix-misc-scripting", "创建一个 Python 自动化脚本批量处理题目", "MISC", "misc_scripting", "通用"),
        ("matrix-misc-git", "创建一个 Git 提交历史恢复题目", "MISC", "misc_git", "通用"),
        ("matrix-misc-regex", "创建一个正则表达式日志字段提取题目", "MISC", "misc_regex", "通用"),
        ("matrix-misc-container", "创建一个 Docker 容器镜像层查看题目", "MISC", "misc_container", "通用"),
        ("matrix-misc-permission", "创建一个 Linux 权限 setuid 线索题目", "MISC", "misc_permission", "通用"),
        ("matrix-misc-data", "创建一个 JSON jq CSV SQLite 数据处理题目", "MISC", "misc_data", "通用"),
        ("matrix-misc-network", "创建一个 nc 端口 DNS 网络基础题目", "MISC", "misc_network", "通用"),
        ("matrix-misc-encoding", "创建一个通用 Base64 URL Hex 多层编码题目", "MISC", "misc_encoding", "通用"),
    ]

    for key, brief, expected_category, expected_candidate, expected_tag in cases:
        draft_response = client.post(
            "/api/v1/challenge-drafts",
            headers={**auth(teacher_token), "Idempotency-Key": key},
            json={
                "courseId": DEV_IDS["course"],
                "brief": brief,
                "constraints": {"internet": False, "maxDifficulty": 5, "workspaceType": "TERMINAL"},
            },
        )
        assert draft_response.status_code == 201, (key, draft_response.text)
        draft = draft_response.json()
        assert draft["courseIntent"]["category"] == expected_category, (key, draft["courseIntent"])

        candidates = client.get(draft["candidatesUrl"], headers=auth(teacher_token))
        assert candidates.status_code == 200, (key, candidates.text)
        body = candidates.json()
        assert body["candidates"], key
        assert expected_candidate in body["candidates"][0]["candidateId"], (
            key,
            body["candidates"][0]["candidateId"],
        )
        proposal = body["authoringProposal"]
        assert proposal["mode"] in {"USE_EXISTING", "COMPOSE_EXISTING"}, key
        assert proposal["requiresCustomGeneration"] is False, key
        assert "UNKNOWN" not in proposal["tags"], key
        assert expected_tag in "".join(proposal["tags"]) + proposal["title"], key


def test_custom_package_generation_when_no_candidate_matches(
    client: TestClient,
    teacher_token: str,
    settings: Settings,
) -> None:
    draft_response = client.post(
        "/api/v1/challenge-drafts",
        headers={**auth(teacher_token), "Idempotency-Key": "custom-package-draft"},
        json={
            "courseId": DEV_IDS["course"],
            "brief": "需要一个终端 Web 定制题，但预计 1 分钟内完成，用于验证无候选时的定制靶场生成。",
            "constraints": {
                "internet": False,
                "maxDifficulty": 1,
                "maxExpectedMinutes": 1,
                "workspaceType": "TERMINAL",
            },
        },
    )
    assert draft_response.status_code == 201, draft_response.text
    draft = draft_response.json()

    candidates = client.get(draft["candidatesUrl"], headers=auth(teacher_token))
    assert candidates.status_code == 200, candidates.text
    candidate_body = candidates.json()
    assert candidate_body["candidates"] == []
    assert candidate_body["compositionPlan"]["mode"] == "custom-agent-scaffold"
    assert candidate_body["authoringProposal"]["mode"] == "GENERATE_CUSTOM"
    assert candidate_body["authoringProposal"]["requiresCustomGeneration"] is True
    assert candidate_body["authoringProposal"]["challengeVersionId"] is None
    assert "SQLite" in candidate_body["authoringProposal"]["description"]

    generated = client.post(
        f"/api/v1/challenge-drafts/{draft['draftId']}/generate-custom-package",
        headers=auth(teacher_token),
    )
    assert generated.status_code == 200, generated.text
    body = generated.json()
    assert body["status"] == "GENERATED_CUSTOM"
    assert body["sourceCandidateId"] == "custom-agent-scaffold"
    assert body["generatedBy"] == "agent-scaffold"
    assert body["versionStatus"] == "PENDING_APPROVAL"
    assert body["validationStatus"] == "WARN"
    assert "manifest.yaml" in body["modelDraft"]["generatedFiles"]
    assert "target/server.py" in body["modelDraft"]["generatedFiles"]
    assert "oracle/validator.py" in body["modelDraft"]["generatedFiles"]

    validation = client.get(body["validationReportUrl"], headers=auth(teacher_token))
    assert validation.status_code == 200, validation.text
    assert validation.json()["overallStatus"] == "WARN"

    with client.app.state.SessionLocal() as db:
        version = db.get(models.ChallengeVersion, body["challengeVersionId"])
        assert version is not None
        assert version.status == "PENDING_APPROVAL"
        artifact = db.scalar(
            select(models.ChallengeArtifact).where(
                models.ChallengeArtifact.version_id == version.id,
                models.ChallengeArtifact.artifact_type == "generated-challenge-package",
            )
        )
        assert artifact is not None
        assert artifact.object_ref.startswith("local://challenge-artifacts/")
        relative = artifact.object_ref.removeprefix("local://challenge-artifacts/")
        archive_path = Path(settings.challenge_artifact_object_root) / relative
        assert archive_path.is_file()
        with tarfile.open(archive_path) as archive:
            names = set(archive.getnames())
            server_source = archive.extractfile("target/server.py")
            assert server_source is not None
            server_text = server_source.read().decode("utf-8")
        assert {"manifest.yaml", "workspace/Dockerfile", "target/server.py", "oracle/validator.py"} <= names
        assert "sqlite3" in server_text
        assert "CREATE TABLE IF NOT EXISTS users" in server_text
        assert "def login_with_vulnerable_query" in server_text

    followup = client.post(
        "/api/v1/challenge-drafts",
        headers={**auth(teacher_token), "Idempotency-Key": "custom-package-followup-sqli"},
        json={
            "courseId": DEV_IDS["course"],
            "brief": "创建一个经典的 SQL 注入题目。",
            "constraints": {"internet": False, "maxDifficulty": 3, "workspaceType": "TERMINAL"},
        },
    )
    assert followup.status_code == 201, followup.text
    followup_candidates = client.get(followup.json()["candidatesUrl"], headers=auth(teacher_token))
    assert followup_candidates.status_code == 200, followup_candidates.text
    followup_body = followup_candidates.json()
    assert followup_body["candidates"]
    assert followup_body["candidates"][0]["candidateId"] == DEV_IDS["challenge_version"]
    assert followup_body["candidates"][0]["candidateId"] != body["challengeVersionId"]


def test_custom_package_generation_uses_target_specific_templates(
    client: TestClient,
    teacher_token: str,
    settings: Settings,
) -> None:
    cases = [
        {
            "key": "custom-xss-template",
            "brief": "创建一个经典的 XSS 漏洞题目，但要求 1 分钟内完成以触发定制生成。",
            "expectedTitle": "定制 XSS 脚本注入靶场",
            "path": "target/server.py",
            "terms": ["CLA XSS 留言调试页", "CREATE TABLE IF NOT EXISTS messages", "xss_probe_observed"],
        },
        {
            "key": "custom-pwn-integer-template",
            "brief": "创建一个整数类型溢出的 Pwn 题目，但要求 1 分钟内完成以触发定制生成。",
            "expectedTitle": "定制 Pwn 整数溢出靶场",
            "path": "target/vuln.c",
            "terms": ["integer boundary crossed", "unsigned int bytes = count * 16", "cla-proof"],
        },
    ]
    for case in cases:
        draft_response = client.post(
            "/api/v1/challenge-drafts",
            headers={**auth(teacher_token), "Idempotency-Key": case["key"]},
            json={
                "courseId": DEV_IDS["course"],
                "brief": case["brief"],
                "constraints": {
                    "internet": False,
                    "maxDifficulty": 5,
                    "maxExpectedMinutes": 1,
                    "workspaceType": "TERMINAL",
                },
            },
        )
        assert draft_response.status_code == 201, draft_response.text
        draft = draft_response.json()
        candidates = client.get(draft["candidatesUrl"], headers=auth(teacher_token))
        assert candidates.status_code == 200, candidates.text
        assert candidates.json()["authoringProposal"]["mode"] == "GENERATE_CUSTOM"

        generated = client.post(
            f"/api/v1/challenge-drafts/{draft['draftId']}/generate-custom-package",
            headers=auth(teacher_token),
        )
        assert generated.status_code == 200, generated.text
        body = generated.json()
        assert body["modelDraft"]["title"] == case["expectedTitle"]

        with client.app.state.SessionLocal() as db:
            artifact = db.scalar(
                select(models.ChallengeArtifact)
                .where(models.ChallengeArtifact.version_id == body["challengeVersionId"])
                .where(models.ChallengeArtifact.artifact_type == "generated-challenge-package")
            )
        assert artifact is not None
        archive_path = Path(settings.challenge_artifact_object_root) / artifact.object_ref.removeprefix(
            "local://challenge-artifacts/"
        )
        with tarfile.open(archive_path) as archive:
            source = archive.extractfile(case["path"])
            assert source is not None
            text = source.read().decode("utf-8")
        for term in case["terms"]:
            assert term in text


def test_model_brief_parser_and_version_generation_are_audited(tmp_path, monkeypatch) -> None:
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        dev_mode=True,
        dev_oidc_secret="test-oidc-secret",
        terminal_ticket_secret="test-terminal-secret",
        oracle_shared_secret="test-oracle-secret",
        internal_service_token="test-internal",
        gateway_url="ws://gateway.test/ws/terminal",
        transcript_object_root=str(tmp_path / "transcripts"),
        challenge_artifact_object_root=str(tmp_path / "challenge-artifacts"),
        transcript_encryption_key="test-transcript-key",
        agent_runtime_enabled=True,
        model_base_url="https://model.example/v1",
        model_name="deepseekv4flash",
        model_api_key="test-key",
    )

    def fake_parse(*args, **kwargs) -> agent_runtime.AgentModelResult:
        return agent_runtime.AgentModelResult(
            output={
                "category": "WEB",
                "target": "AUTHENTICATION",
                "difficulty": 2,
                "expectedMinutes": 75,
                "workspaceType": "TERMINAL",
                "isolationTier": 1,
                "allowedTools": ["sqlmap", "curl"],
                "learningObjectives": [
                    "SQL_INJECTION",
                    "DATABASE",
                ],
                "uncertainFields": [],
                "confidence": 0.97,
            },
            usage={"provider": "openai-compatible", "model": "deepseekv4flash"},
        )

    def fake_draft(*args, **kwargs) -> agent_runtime.AgentModelResult:
        return agent_runtime.AgentModelResult(
            output={
                "title": "登录逻辑与输入信任边界",
                "summary": "学生验证登录输入边界并说明修复方向。",
                "manifestNotes": ["保持终端工作区", "保持外部 Oracle"],
                "rubricDraft": {
                    "criteria": [
                        {
                            "id": "oracle-auth-bypass",
                            "title": "外部 Oracle 观测到认证绕过",
                            "graderType": "DETERMINISTIC_ORACLE",
                            "maxScore": 60,
                            "evidencePolicy": {"requiredEventTypes": ["oracle.observed"]},
                        }
                    ]
                },
                "teacherReviewChecklist": ["确认验证报告没有阻断项"],
                "confidence": 0.91,
            },
            usage={"provider": "openai-compatible", "model": "deepseekv4flash"},
        )

    monkeypatch.setattr(agent_runtime, "parse_course_intent_with_model", fake_parse)
    monkeypatch.setattr(agent_runtime, "draft_challenge_version_with_model", fake_draft)

    client = TestClient(create_app(settings))
    teacher_token = create_dev_token(settings, subject="teacher@example.edu", roles=["teacher"])

    draft = create_draft(client, teacher_token, key="model-draft")
    assert draft["courseIntent"]["confidence"] == 0.97
    assert "sqlmap" not in [tool.lower() for tool in draft["courseIntent"]["allowedTools"]]
    assert "curl" in draft["courseIntent"]["allowedTools"]
    assert "identify-input-trust-boundary" in draft["courseIntent"]["learningObjectives"]

    candidates = client.get(draft["candidatesUrl"], headers=auth(teacher_token))
    assert candidates.status_code == 200, candidates.text
    selected = candidates.json()["candidates"][0]["candidateId"]

    generated = client.post(
        f"/api/v1/challenge-drafts/{draft['draftId']}/generate-version",
        headers=auth(teacher_token),
        json={"selectedCandidateId": selected},
    )
    assert generated.status_code == 200, generated.text
    body = generated.json()
    assert body["generatedBy"] == "model"
    assert body["versionStatus"] == "PENDING_APPROVAL"
    assert body["modelDraft"]["summary"] == "学生验证登录输入边界并说明修复方向。"

    approval = client.post(
        f"/api/v1/challenge-versions/{body['challengeVersionId']}/approve",
        headers=auth(teacher_token),
    )
    assert approval.status_code == 200, approval.text
    assert approval.json()["published"] is True

    with client.app.state.SessionLocal() as db:
        runs = db.scalars(select(models.AgentRun).order_by(models.AgentRun.purpose.asc())).all()
        assert {run.purpose for run in runs} == {"brief.parse", "challenge.version.draft"}
        assert all(run.status == "SUCCEEDED" for run in runs)
        assert db.scalar(select(func.count(models.ChallengeArtifact.id))) >= 1
