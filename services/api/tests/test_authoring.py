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
    assert len(body["imported"]) == 150
    assert body["summary"]["valid"] is True
    assert body["summary"]["total"] == 150
    assert body["summary"]["counts"] == {"WEB": 50, "REVERSE": 50, "PWN": 50}

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
        assert counts == {"PWN": 50, "REVERSE": 50, "WEB": 50}
        assert (
            db.scalar(
                select(func.count(models.ChallengeArtifact.id)).where(
                    models.ChallengeArtifact.artifact_type == "blueprint-catalog-entry"
                )
            )
            == 150
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
        assert {"manifest.yaml", "workspace/Dockerfile", "target/server.py", "oracle/validator.py"} <= names


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
                "allowedTools": ["curl", "python"],
                "learningObjectives": [
                    "identify-input-trust-boundary",
                    "validate-authentication-impact",
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
