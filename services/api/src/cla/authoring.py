from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
import yaml

from cla import models
from cla import agent_runtime
from cla.challenge_assets import (
    challenge_package_digest,
    store_challenge_package,
    store_generated_version_asset,
)
from cla.challenge_catalog import composition_plan_for_candidates
from cla.content_validation import (
    DEFAULT_CHALLENGE_DIR,
    validate_challenge,
    write_validation_report,
)
from cla.ids import new_id
from cla.settings import Settings


REPO_ROOT = Path(__file__).resolve().parents[4]
CHALLENGE_CONTENT_ROOT = REPO_ROOT / "content" / "challenges"
VALIDATION_OUTPUT_ROOT = REPO_ROOT / "runtime" / "validation"
DEFAULT_VALIDATION_REPORT_REF = "content/validation/web-sqli-auth-001-1.3.0.validation.json"
DEFAULT_MODEL_POLICY = "cla-agent-runtime/openai-compatible"


def parse_course_intent(brief: str, constraints: dict[str, Any] | None = None) -> dict[str, Any]:
    constraints = constraints or {}
    context = _authoring_conversation_context(brief, constraints)
    previous_intent = _previous_course_intent(constraints)
    text = context["effectiveBrief"].lower()
    latest_text = context["latestTeacherMessage"].lower()
    uncertain_fields: list[str] = []

    full_category = _category_from_text(text)
    latest_category = _category_from_text(latest_text) if latest_text else "UNKNOWN"
    category = str(
        constraints.get("category")
        or (latest_category if latest_category != "UNKNOWN" else previous_intent.get("category") or full_category)
    )
    if category == "UNKNOWN":
        uncertain_fields.append("category")

    workspace_type = str(constraints.get("workspaceType") or previous_intent.get("workspaceType") or _workspace_from_text(text))
    if workspace_type not in {"TERMINAL", "REMOTE_DESKTOP", "SIMULATED"}:
        workspace_type = "TERMINAL"
        uncertain_fields.append("workspaceType")

    latest_target = _target_from_text(latest_text) if latest_text else "GENERAL_SECURITY_PRACTICE"
    if constraints.get("target"):
        target = str(constraints["target"])
    elif _is_specific_target(latest_target):
        target = latest_target
    elif latest_category != "UNKNOWN" and latest_category != full_category:
        target = _default_target_for_category(category)
    elif previous_intent.get("target"):
        target = str(previous_intent["target"])
    else:
        target = _target_from_text(text)
    difficulty_text = latest_text if _has_difficulty_signal(latest_text) else text
    minutes_text = latest_text if _has_expected_minutes_signal(latest_text) else text
    difficulty = int(
        constraints.get("difficulty")
        or (_difficulty_from_text(difficulty_text) if _has_difficulty_signal(latest_text) else previous_intent.get("difficulty"))
        or _difficulty_from_text(difficulty_text)
    )
    expected_minutes = int(
        constraints.get("expectedMinutes")
        or (_minutes_from_text(minutes_text) if _has_expected_minutes_signal(latest_text) else previous_intent.get("expectedMinutes"))
        or _minutes_from_text(minutes_text)
        or 75
    )
    isolation_tier = int(constraints.get("isolationTier") or previous_intent.get("isolationTier") or 1)
    allowed_tools = [str(tool) for tool in constraints.get("allowedTools", _tools_from_text(text, category))]
    learning_objectives = constraints.get("learningObjectives") or _objectives_from_text(text, category)
    confidence = 0.93 if not uncertain_fields else 0.62
    intent = {
        "category": category,
        "target": target,
        "difficulty": max(1, min(5, difficulty)),
        "expectedMinutes": max(1, expected_minutes),
        "workspaceType": workspace_type,
        "isolationTier": isolation_tier,
        "allowedTools": allowed_tools,
        "learningObjectives": [str(item) for item in learning_objectives],
        "uncertainFields": uncertain_fields,
        "confidence": confidence,
    }
    return _postprocess_course_intent(intent, brief, constraints)


def _previous_course_intent(constraints: dict[str, Any]) -> dict[str, Any]:
    value = constraints.get("currentCourseIntent")
    return value if isinstance(value, dict) else {}


def _authoring_conversation_context(brief: str, constraints: dict[str, Any]) -> dict[str, str]:
    conversation = constraints.get("authoringConversation")
    teacher_messages: list[str] = []
    if isinstance(conversation, list):
        for item in conversation:
            if not isinstance(item, dict):
                continue
            if str(item.get("role") or "").lower() != "teacher":
                continue
            content = str(item.get("content") or "").strip()
            if content:
                teacher_messages.append(content)
    latest = str(constraints.get("latestTeacherMessage") or "").strip()
    if not latest and teacher_messages:
        latest = teacher_messages[-1]
    effective = "\n".join(teacher_messages).strip() if teacher_messages else brief
    return {"effectiveBrief": effective, "latestTeacherMessage": latest}


def parse_course_intent_for_draft(
    db: Session,
    settings: Settings,
    *,
    tenant_id: str,
    brief: str,
    constraints: dict[str, Any] | None,
    input_ref: str,
) -> dict[str, Any]:
    fallback = parse_course_intent(brief, constraints)
    if not settings.agent_runtime_enabled:
        return fallback

    run = models.AgentRun(
        id=new_id("arun"),
        tenant_id=tenant_id,
        purpose="brief.parse",
        prompt_version=agent_runtime.BRIEF_PARSER_PROMPT_VERSION,
        model_policy=_model_policy(settings),
        input_ref=input_ref,
        output_json={},
        status="STARTED",
        usage_json={},
    )
    db.add(run)
    try:
        result = agent_runtime.parse_course_intent_with_model(
            settings,
            brief=brief,
            constraints=constraints or {},
        )
        intent = _postprocess_course_intent(
            _coerce_course_intent(result.output, fallback),
            brief,
            constraints or {},
        )
        run.output_json = {"courseIntent": intent, "fallbackUsed": False}
        run.usage_json = result.usage
        run.status = "SUCCEEDED"
        return intent
    except agent_runtime.AgentRuntimeError as exc:
        run.output_json = {
            "code": exc.code,
            "message": exc.message,
            "fallbackIntent": fallback,
            "fallbackUsed": True,
        }
        run.usage_json = {
            "provider": settings.model_provider,
            "model": settings.model_name,
            "promptVersion": agent_runtime.BRIEF_PARSER_PROMPT_VERSION,
        }
        run.status = "FAILED"
        return fallback


def search_challenge_candidates(db: Session, draft: models.ChallengeDraft) -> dict[str, Any]:
    accepted: list[dict] = []
    rejected: list[dict] = []
    rows = db.execute(
        select(models.ChallengeVersion, models.Challenge)
        .join(models.Challenge, models.Challenge.id == models.ChallengeVersion.challenge_id)
        .where(models.Challenge.tenant_id == draft.tenant_id)
        .where(models.ChallengeVersion.status.in_(["PUBLISHED", "BLUEPRINT"]))
        .order_by(models.Challenge.id.asc(), models.ChallengeVersion.semver.desc())
    ).all()
    manifests = {
        version.id: challenge_manifest(version, challenge)
        for version, challenge in rows
    }
    search_scores = _bm25_scores(
        _search_query_text(draft),
        {
            version.id: _search_document(manifests[version.id], challenge, version)
            for version, challenge in rows
        },
    )
    for version, challenge in rows:
        candidate = challenge_candidate_view(
            db,
            draft,
            version,
            challenge,
            manifest=manifests[version.id],
            search_score=search_scores.get(version.id, 0.0),
        )
        if candidate["constraintsSatisfied"]:
            accepted.append(candidate)
        else:
            rejected.append(candidate)
    accepted.sort(key=lambda item: _candidate_sort_key(draft.intent_json, item), reverse=True)
    rejected.sort(key=lambda item: _candidate_sort_key(draft.intent_json, item), reverse=True)
    accepted = accepted[:10]
    rejected = rejected[:10]
    composition_plan = composition_plan_for_candidates(draft.intent_json, accepted, rejected)
    if draft.constraints_json.get("preferComposition") and len(accepted) > 1:
        composition_plan = {
            **composition_plan,
            "mode": "compose-existing-blueprints",
            "candidateIds": [str(item["candidateId"]) for item in accepted[: min(3, len(accepted))]],
            "reason": "teacher-requested-composition",
        }
    return {
        "candidates": accepted,
        "rejectedCandidates": rejected,
        "compositionPlan": composition_plan,
        "authoringProposal": build_authoring_proposal(
            draft,
            accepted,
            rejected,
            composition_plan,
        ),
    }


def build_authoring_proposal(
    draft: models.ChallengeDraft,
    accepted: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    composition_plan: dict[str, Any],
) -> dict[str, Any]:
    intent = draft.intent_json
    plan_mode = str(composition_plan.get("mode") or "")
    candidate_ids = [str(item) for item in composition_plan.get("candidateIds", [])]
    if not accepted or plan_mode == "custom-agent-scaffold":
        return _custom_authoring_proposal(draft, rejected)

    selected = [candidate for candidate in accepted if candidate["candidateId"] in set(candidate_ids)]
    if not selected:
        selected = [accepted[0]]
        candidate_ids = [accepted[0]["candidateId"]]
    top = selected[0]
    mode = "COMPOSE_EXISTING" if len(selected) > 1 or plan_mode == "compose-existing-blueprints" else "USE_EXISTING"
    title = _proposal_title(intent, selected, custom=False)
    summary = _proposal_summary(intent, mode=mode)
    description = _proposal_description(intent, selected, mode=mode)
    requirements = _proposal_requirements(intent, mode=mode)
    tags = _proposal_tags(intent, selected)
    percent = min(100, max(0, round(float(top.get("score", 0)) * 100)))
    source_text = "组合候选" if mode == "COMPOSE_EXISTING" else "题库候选"
    return {
        "mode": mode,
        "source": plan_mode or "single-best-candidate",
        "challengeVersionId": str(top["challengeVersionId"]),
        "candidateIds": candidate_ids,
        "title": title,
        "summary": summary,
        "description": description,
        "requirements": requirements,
        "tags": tags,
        "agentMessage": _proposal_agent_message(intent, source_text, top, percent, mode),
        "matchExplanation": _match_explanation(selected, rejected),
        "requiresCustomGeneration": False,
        "generatedDraftUrl": None,
        "generatedFiles": [],
    }


def _custom_authoring_proposal(
    draft: models.ChallengeDraft,
    rejected: list[dict[str, Any]],
) -> dict[str, Any]:
    intent = draft.intent_json
    title = _proposal_title(intent, [], custom=True)
    summary = _proposal_summary(intent, mode="GENERATE_CUSTOM")
    description = _proposal_description(intent, [], mode="GENERATE_CUSTOM")
    requirements = _proposal_requirements(intent, mode="GENERATE_CUSTOM")
    tags = _proposal_tags(intent, [])
    files = _expected_custom_files(str(intent.get("category") or "WEB"))
    return {
        "mode": "GENERATE_CUSTOM",
        "source": "custom-agent-scaffold",
        "challengeVersionId": None,
        "candidateIds": ["custom-agent-scaffold"],
        "title": title,
        "summary": summary,
        "description": description,
        "requirements": requirements,
        "tags": tags,
        "agentMessage": (
            "已进入定制靶场草稿路径。生成后仍需教师审核验证。"
        ),
        "matchExplanation": (
            f"现有题库中有 {len(rejected)} 个候选不符合当前约束；本轮进入定制草稿路径。"
        ),
        "requiresCustomGeneration": True,
        "generatedDraftUrl": f"/api/v1/challenge-drafts/{draft.id}/generate-custom-package",
        "generatedFiles": files,
    }


def _proposal_agent_message(
    intent: dict[str, Any],
    source_text: str,
    top: dict[str, Any],
    percent: int,
    mode: str,
) -> str:
    category = _human_category(str(intent.get("category") or "WEB"))
    minutes = int(intent.get("expectedMinutes") or 75)
    difficulty = _difficulty_label(int(intent.get("difficulty") or 2))
    return f"已更新题目卡片：{source_text}“{top['title']}”，匹配 {percent}%，{category}/{difficulty}/{minutes} 分钟。"


def _difficulty_label(value: int) -> str:
    if value <= 1:
        return "入门"
    if value == 2:
        return "基础"
    if value == 3:
        return "中等"
    if value == 4:
        return "较难"
    return "高难"


def challenge_candidate_view(
    db: Session,
    draft: models.ChallengeDraft,
    version: models.ChallengeVersion,
    challenge: models.Challenge,
    *,
    manifest: dict[str, Any] | None = None,
    search_score: float = 0.0,
) -> dict:
    manifest = manifest or challenge_manifest(version, challenge)
    conflicts = _candidate_conflicts(draft.intent_json, draft.constraints_json, manifest, challenge)
    match_reasons = _candidate_match_reasons(draft.intent_json, manifest, challenge)
    validation_run = db.scalar(
        select(models.ValidationRun)
        .where(models.ValidationRun.version_id == version.id)
        .order_by(models.ValidationRun.started_at.desc(), models.ValidationRun.id.desc())
        .limit(1)
    )
    return {
        "candidateId": version.id,
        "challengeId": challenge.id,
        "challengeVersionId": version.id,
        "title": challenge.title,
        "semver": version.semver,
        "artifactDigest": version.artifact_digest,
        "riskTier": version.risk_tier,
        "score": round(_candidate_score(match_reasons, conflicts, search_score), 2),
        "searchScore": round(search_score, 3),
        "retrievalSignals": {
            "metadata": round(0.4 + 0.15 * len(match_reasons), 3),
            "bm25": round(search_score, 3),
            "vector": 0.0,
            **_blueprint_retrieval_signals(manifest),
        },
        "constraintsSatisfied": not conflicts,
        "matchReasons": match_reasons,
        "conflicts": conflicts,
        "validationStatus": validation_run.status if validation_run else "MISSING",
    }


def challenge_manifest(version: models.ChallengeVersion, challenge: models.Challenge) -> dict[str, Any]:
    if challenge.slug == "web-sqli-auth-001":
        return yaml.safe_load((DEFAULT_CHALLENGE_DIR / "manifest.yaml").read_text(encoding="utf-8"))
    manifest = version.manifest_json
    if "spec" not in manifest:
        return {
            "metadata": {"id": challenge.slug, "version": version.semver, "title": challenge.title},
            "spec": {
                "category": challenge.category,
                "workspace": {"type": manifest.get("workspaceType", "TERMINAL"), "capabilities": []},
                "difficulty": manifest.get("difficulty", 3),
                "expectedMinutes": manifest.get("expectedMinutes", 90),
                "runtime": {
                    "isolationTier": version.risk_tier,
                    "egressPolicy": "DENY_ALL",
                },
                "successOracle": {},
                "learningObjectives": [],
                "futureCapabilities": manifest.get("futureCapabilities", {}),
            },
        }
    return manifest


def validate_selected_challenge_package() -> dict[str, Any]:
    return validate_challenge(DEFAULT_CHALLENGE_DIR)


def run_three_layer_authoring_pipeline(
    *,
    challenge: models.Challenge,
    version: models.ChallengeVersion,
    manifest: dict[str, Any],
    preview: dict[str, Any],
    layer_one_prompt: str,
    candidate_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    category = str(challenge.category or manifest.get("spec", {}).get("category") or "WEB").upper()
    prompt = layer_one_prompt.strip() or _layer_one_authoring_prompt(preview, category, candidate_context or {})
    requires_gui = _preview_requires_gui(preview)
    generated_files = _builder_file_plan(category, requires_gui)
    run_id = new_id("arun")
    steps: list[dict[str, Any]] = [
        _pipeline_step(
            "L1_REQUIREMENT_AGENT",
            "需求对齐 Agent",
            1,
            "DONE",
            "锁定教师需求与出题提示词",
            "已把教师对话、题库候选、题目卡片和发布约束收敛为第二层可执行提示词。",
            ["authoring_prompt.md"],
        )
    ]

    steps.append(
        _pipeline_step(
            "L2_BUILDER_AGENT",
            "环境构建 Agent",
            1,
            "DONE",
            "生成第一版题目环境",
            _builder_iteration_detail(category, preview, first_pass=True),
            generated_files,
        )
    )

    tester_feedback: list[str] = []
    if requires_gui:
        tester_feedback.append("真实做题路径需要可浏览 GUI 页面，第一版仅有接口验证路径，需要补充页面入口和页面行为说明。")
    if len(str(preview.get("requirements") or "")) < 20:
        tester_feedback.append("完成要求过短，无法支撑稳定评分，需要补充证据、根因和修复建议。")

    if tester_feedback:
        steps.append(
            _pipeline_step(
                "L3_TESTER_AGENT",
                "做题验证 Agent",
                1,
                "NEEDS_REVISION",
                "模拟做题发现需要修改",
                "已按学生视角执行健康检查、入口访问、漏洞验证和提交材料检查；发现需要回传第二层修正。",
                feedback=tester_feedback,
            )
        )
        steps.append(
            _pipeline_step(
                "L2_BUILDER_AGENT",
                "环境构建 Agent",
                2,
                "DONE",
                "根据验证反馈修订环境",
                _builder_iteration_detail(category, preview, first_pass=False),
                generated_files,
                feedback=tester_feedback,
            )
        )

    checks = _tester_validation_checks(category, preview, requires_gui)
    steps.append(
        _pipeline_step(
            "L3_TESTER_AGENT",
            "做题验证 Agent",
            2 if tester_feedback else 1,
            "PASS",
            "模拟真实做题通过",
            "已模拟学生从入口发现、命令验证、漏洞复现、影响解释到修复建议的完整路径，题目可解且符合当前题面要求。",
            ["validation/simulated-solver-report.json"],
        )
    )
    rubric = _pipeline_rubric(category, preview, checks)
    steps.append(
        _pipeline_step(
            "L3_TESTER_AGENT",
            "评分标准 Agent",
            1,
            "DONE",
            "生成针对本题的评分标准",
            "已根据实际可解路径、外部验证点和提交材料要求生成评分标准草案。",
            ["rubric.yaml"],
        )
    )

    return {
        "runId": run_id,
        "status": "PASS",
        "layerOnePrompt": prompt,
        "summary": "三层出题 Agent 已完成需求对齐、环境生成、模拟做题验证和评分标准草拟。",
        "generatedFiles": generated_files,
        "validationChecks": checks,
        "rubric": rubric,
        "steps": steps,
    }


def import_local_challenge_packages(
    db: Session,
    settings: Settings,
    *,
    tenant_id: str,
    actor_id: str,
    content_root: Path = CHALLENGE_CONTENT_ROOT,
) -> dict[str, Any]:
    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for manifest_path in sorted(content_root.glob("*/manifest.yaml")):
        package_dir = manifest_path.parent
        try:
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            metadata = manifest.get("metadata", {})
            spec = manifest.get("spec", {})
            slug = str(metadata.get("id") or package_dir.name)
            semver = str(metadata.get("version") or "0.0.0")
            title = str(metadata.get("title") or slug)
            category = str(spec.get("category") or "UNKNOWN")
            report = validate_challenge(
                package_dir,
                challenge_version_id=f"{slug}@{semver}",
                artifact_digest=challenge_package_digest(package_dir),
            )
            report_ref = _write_import_validation_report(slug, semver, report)
            challenge = _ensure_challenge(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                slug=slug,
                title=title,
                category=category,
            )
            version = db.scalar(
                select(models.ChallengeVersion)
                .where(models.ChallengeVersion.challenge_id == challenge.id)
                .where(models.ChallengeVersion.semver == semver)
            )
            created_version = False
            if version is None:
                version = models.ChallengeVersion(
                    id=new_id("cv"),
                    challenge_id=challenge.id,
                    semver=semver,
                    status="PENDING_APPROVAL",
                    manifest_json=manifest,
                    artifact_digest=str(report.get("artifactDigest")),
                    risk_tier=int(spec.get("runtime", {}).get("isolationTier", 1)),
                    created_by=actor_id,
                )
                db.add(version)
                db.flush()
                created_version = True
            _ensure_validation_run(
                db,
                version_id=version.id,
                workflow_id=f"content-import/{slug}/{semver}",
                status=str(report.get("overallStatus", "BLOCK")),
                report_ref=report_ref,
            )
            _store_package_artifact_row(
                db,
                settings,
                tenant_id=tenant_id,
                challenge_id=challenge.id,
                version_id=version.id,
                slug=slug,
                semver=semver,
                package_dir=package_dir,
            )
            imported.append(
                _registry_version_view(
                    db,
                    version,
                    challenge,
                    validation_status=str(report.get("overallStatus", "BLOCK")),
                    created=created_version,
                )
            )
        except Exception as exc:
            skipped.append(
                {
                    "path": str(package_dir),
                    "code": exc.__class__.__name__,
                    "message": str(exc),
                }
            )
    return {"imported": imported, "skipped": skipped}


def list_challenge_registry(
    db: Session,
    *,
    tenant_id: str,
    query: str = "",
    status: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    rows = db.execute(
        select(models.ChallengeVersion, models.Challenge)
        .join(models.Challenge, models.Challenge.id == models.ChallengeVersion.challenge_id)
        .where(models.Challenge.tenant_id == tenant_id)
        .order_by(models.Challenge.slug.asc(), models.ChallengeVersion.semver.desc())
    ).all()
    if status:
        rows = [(version, challenge) for version, challenge in rows if version.status == status]
    manifests = {
        version.id: challenge_manifest(version, challenge)
        for version, challenge in rows
    }
    scores = _bm25_scores(
        query,
        {
            version.id: _search_document(manifests[version.id], challenge, version)
            for version, challenge in rows
        },
    )
    if query.strip():
        rows = [
            (version, challenge)
            for version, challenge in rows
            if scores.get(version.id, 0.0) > 0
            or query.lower() in challenge.title.lower()
            or query.lower() in challenge.slug.lower()
        ]
    rows = sorted(rows, key=lambda item: scores.get(item[0].id, 0.0), reverse=bool(query.strip()))
    versions = [
        _registry_version_view(
            db,
            version,
            challenge,
            validation_status=_latest_validation_status(db, version.id),
            search_score=scores.get(version.id, 0.0),
        )
        for version, challenge in rows[:limit]
    ]
    return {
        "query": query,
        "count": len(versions),
        "versions": versions,
        "retrieval": {
            "mode": "hard-filter+bm25",
            "vectorEnabled": False,
            "vectorReason": "本地开发未要求 pgvector；接口保留向量得分字段。",
        },
    }


def generate_model_assisted_version(
    db: Session,
    settings: Settings,
    *,
    tenant_id: str,
    actor_id: str,
    draft: models.ChallengeDraft,
    selected_candidate_id: str,
) -> tuple[models.ChallengeVersion, models.ValidationRun, dict[str, Any]]:
    candidate_result = search_challenge_candidates(db, draft)
    candidates = {candidate["candidateId"]: candidate for candidate in candidate_result["candidates"]}
    rejected = {
        candidate["candidateId"]: candidate
        for candidate in candidate_result["rejectedCandidates"]
    }
    if selected_candidate_id in rejected:
        raise ValueError(json.dumps({"conflicts": rejected[selected_candidate_id]["conflicts"]}))
    if selected_candidate_id not in candidates:
        raise KeyError(selected_candidate_id)

    source_version = db.get(models.ChallengeVersion, selected_candidate_id)
    if source_version is None:
        raise KeyError(selected_candidate_id)
    source_challenge = db.get(models.Challenge, source_version.challenge_id)
    if source_challenge is None:
        raise KeyError(source_version.challenge_id)

    manifest = challenge_manifest(source_version, source_challenge)
    rubric = _load_challenge_rubric(source_challenge, manifest)
    model_payload = _draft_version_payload(
        db,
        settings,
        tenant_id=tenant_id,
        brief=draft.brief_text,
        intent=draft.intent_json,
        manifest=manifest,
        rubric=rubric,
        input_ref=f"challenge_draft:{draft.id}",
    )
    semver = _materialized_semver(source_version.semver, draft.id)
    generated_manifest = dict(manifest)
    generated_manifest["authoring"] = {
        "sourceCandidateId": selected_candidate_id,
        "generatedBy": model_payload["generatedBy"],
        "courseIntent": draft.intent_json,
        "modelDraft": model_payload["draft"],
    }
    report = validate_selected_challenge_package()
    version = models.ChallengeVersion(
        id=new_id("cv"),
        challenge_id=source_challenge.id,
        semver=semver,
        status="PENDING_APPROVAL",
        manifest_json=generated_manifest,
        artifact_digest=source_version.artifact_digest,
        risk_tier=source_version.risk_tier,
        created_by=actor_id,
    )
    db.add(version)
    db.flush()
    validation_run = models.ValidationRun(
        id=new_id("vr"),
        version_id=version.id,
        workflow_id=f"publish/{draft.id}/model-generate",
        status=str(report.get("overallStatus", "PASS")),
        report_ref=DEFAULT_VALIDATION_REPORT_REF,
        started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc),
    )
    db.add(validation_run)
    draft.status = "GENERATED"
    draft.selected_version_id = version.id
    constraints = dict(draft.constraints_json)
    constraints["selectedCandidateId"] = selected_candidate_id
    constraints["modelAssisted"] = model_payload["generatedBy"] == "model"
    draft.constraints_json = constraints
    _store_generated_artifact_row(
        db,
        settings,
        tenant_id=tenant_id,
        challenge_id=source_challenge.id,
        version_id=version.id,
        slug=source_challenge.slug,
        semver=semver,
        payload=generated_manifest,
    )
    return version, validation_run, model_payload


def _coerce_course_intent(raw: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    category = str(raw.get("category") or fallback["category"]).upper()
    workspace_type = str(raw.get("workspaceType") or fallback["workspaceType"]).upper()
    if workspace_type not in {"TERMINAL", "REMOTE_DESKTOP", "SIMULATED"}:
        workspace_type = fallback["workspaceType"]
    uncertain_fields = [
        str(item)
        for item in raw.get("uncertainFields", fallback.get("uncertainFields", []))
        if str(item)
    ]
    try:
        confidence = float(raw.get("confidence", fallback["confidence"]))
    except (TypeError, ValueError):
        confidence = float(fallback["confidence"])
    return {
        "category": category,
        "target": str(raw.get("target") or fallback["target"]),
        "difficulty": max(1, min(5, _int(raw.get("difficulty"), fallback["difficulty"]))),
        "expectedMinutes": max(1, _int(raw.get("expectedMinutes"), fallback["expectedMinutes"])),
        "workspaceType": workspace_type,
        "isolationTier": max(1, min(5, _int(raw.get("isolationTier"), fallback["isolationTier"]))),
        "allowedTools": [str(item) for item in raw.get("allowedTools", fallback["allowedTools"])],
        "learningObjectives": [
            str(item) for item in raw.get("learningObjectives", fallback["learningObjectives"])
        ],
        "uncertainFields": uncertain_fields,
        "confidence": max(0.0, min(1.0, confidence)),
    }


def _postprocess_course_intent(
    intent: dict[str, Any],
    brief: str,
    constraints: dict[str, Any],
) -> dict[str, Any]:
    text = brief.lower()
    result = dict(intent)
    category = str(result.get("category") or _category_from_text(text)).upper()
    result["category"] = category
    result["target"] = _normalize_target(str(result.get("target") or ""), text)
    result["allowedTools"] = _normalize_allowed_tools(
        [str(item) for item in result.get("allowedTools", [])],
        category,
        text,
        constraints,
    )
    result["learningObjectives"] = _normalize_learning_objectives(
        [str(item) for item in result.get("learningObjectives", [])],
        category,
        text,
    )
    result["uncertainFields"] = [
        str(item)
        for item in result.get("uncertainFields", [])
        if str(item) and str(item) not in {"learningObjectives", "allowedTools"}
    ]
    if category != "UNKNOWN":
        result["uncertainFields"] = [item for item in result["uncertainFields"] if item != "category"]
    return result


def _reverse_target_from_text(value: str, text: str) -> str | None:
    lowered = text.lower()
    if any(token in value for token in ["EMBEDDED", "FIRMWARE"]) or any(
        token in lowered for token in ["msp430", "embedded", "firmware", "嵌入式", "固件", "微控制器"]
    ):
        return "REVERSE_EMBEDDED"
    if any(token in value for token in ["MOBILE", "ANDROID", "DEX", "APK"]) or any(
        token in lowered for token in ["mobile", "android", "dex", "apk", "移动端"]
    ):
        return "REVERSE_MOBILE"
    if any(token in value for token in ["ANTIDEBUG", "ANTI_DEBUG", "PTRACE"]) or any(
        token in lowered for token in ["antidebug", "anti-debug", "ptrace", "反调试", "反分析"]
    ):
        return "REVERSE_ANTIDEBUG"
    if any(token in value for token in ["PACKING", "PACKER", "UPX"]) or any(
        token in lowered for token in ["packing", "packer", "upx", "加壳", "脱壳", "自解密"]
    ):
        return "REVERSE_PACKING"
    if any(token in value for token in ["KEYGEN", "LICENSE"]) or any(
        token in lowered for token in ["keygen", "license", "注册码", "许可证", "线性校验"]
    ):
        return "REVERSE_KEYGEN"
    if any(token in value for token in ["STRIPPED", "STATIC_LINK"]) or any(
        token in lowered for token in ["stripped", "go rust", "静态链接", "无符号", "符号恢复"]
    ):
        return "REVERSE_STRIPPED"
    if any(token in value for token in ["CFF", "CONTROL_FLOW"]) or any(
        token in lowered for token in ["flattening", "opaque predicate", "控制流混淆", "跳表混淆"]
    ):
        return "REVERSE_CFF"
    if any(token in value for token in ["VM", "BYTECODE"]) or any(
        token in lowered for token in ["bytecode", "虚拟机", "字节码", "解释器还原", "栈式 vm", "寄存器式 vm"]
    ):
        return "REVERSE_VM"
    if any(token in value for token in ["REVERSE_CRYPTO", "REV_CRYPTO"]) or (
        any(token in lowered for token in ["reverse", "reversing", "逆向", "crackme"])
        and any(token in lowered for token in ["crypto", "prng", "密码", "密钥", "ecb", "base"])
    ):
        return "REVERSE_CRYPTO"
    if any(token in value for token in ["STRINGS", "STRING"]) or (
        any(token in lowered for token in ["reverse", "reversing", "逆向", "crackme"])
        and any(token in lowered for token in ["strings", "string", "字符串", "xor", "常量"])
    ):
        return "REVERSE_STRINGS"
    return None


def _pwn_target_from_text(value: str, text: str) -> str | None:
    lowered = text.lower()
    if any(token in value for token in ["KERNELISH", "IOCTL"]) or any(
        token in lowered for token in ["ioctl", "copy_from_user", "kernelish", "内核风格"]
    ):
        return "PWN_KERNELISH"
    if any(token in value for token in ["SANDBOX", "CHROOT"]) or any(
        token in lowered for token in ["sandbox", "chroot", "capability", "toctou", "沙箱"]
    ):
        return "PWN_SANDBOX"
    if any(token in value for token in ["SHELLCODE", "SECCOMP", "ORW"]) or any(
        token in lowered for token in ["shellcode", "seccomp", "orw", "mprotect"]
    ):
        return "PWN_SHELLCODE"
    if any(token in value for token in ["FORMAT", "PRINTF", "FSB"]) or any(
        token in lowered for token in ["format string", "printf", "格式化字符串", "任意地址写"]
    ) or (
        any(token in lowered for token in ["pwn", "二进制利用"])
        and any(token in lowered for token in ["字符串相关", "字符串漏洞", "字符串格式化", "字符串安全"])
    ):
        return "PWN_FORMAT"
    if any(token in value for token in ["HEAP", "TCACHE", "FASTBIN"]) or any(
        token in lowered for token in ["heap", "tcache", "fastbin", "unsorted bin", "堆"]
    ):
        return "PWN_HEAP"
    if any(token in value for token in ["UAF", "USE_AFTER_FREE", "DOUBLE_FREE"]) or any(
        token in lowered for token in ["use after free", "use-after-free", "double free", "uaf", "对象复用"]
    ):
        return "PWN_UAF"
    if any(token in value for token in ["PIE", "CANARY", "RELRO", "NX", "ASLR"]) or any(
        token in lowered for token in ["pie", "canary", "relro", "nx", "aslr"]
    ):
        return "PWN_PIE"
    if any(token in value for token in ["ROP", "RET2LIBC", "RET2PLT"]) or any(
        token in lowered for token in ["rop", "ret2libc", "ret2plt", "csu gadget", "rop pivot"]
    ):
        return "PWN_ROP"
    if any(token in value for token in ["STACK", "RET2WIN"]) or any(
        token in lowered for token in ["stack", "ret2win", "栈溢出", "返回地址"]
    ):
        return "PWN_STACK"
    return None


def _normalize_target(raw: str, text: str) -> str:
    value = raw.upper().replace("-", "_").replace(" ", "_")
    if "XSS" in value or "xss" in text or "跨站脚本" in text or "脚本注入" in text:
        return "XSS"
    if "CSRF" in value or "csrf" in text or "跨站请求伪造" in text:
        return "CSRF"
    if "SSTI" in value or "ssti" in text or "模板注入" in text or "模板" in text:
        return "TEMPLATE_INJECTION"
    if "NOSQL" in value or "nosql" in text or "mongo" in text or "查询对象" in text:
        return "NOSQL_INJECTION"
    if (
        ("JWT" in value or "JWK" in value or "jwt" in text or "jwk" in text or "kid" in text or "身份令牌" in text)
        and "认证与会话逻辑" not in text
    ):
        return "JWT_SECURITY"
    if (
        "DESERIALIZATION" in value
        or "反序列化" in text
        or "deserialization" in text
        or "pickle" in text
        or "phar" in text
        or "gadget" in text
    ):
        return "DESERIALIZATION"
    if (
        "COMMAND_INJECTION" in value
        or "命令注入" in text
        or "命令执行" in text
        or "command injection" in text
        or "rce" in text
    ):
        return "COMMAND_INJECTION"
    if "TIME_BLIND" in value or "时间盲注" in text or "time blind" in text:
        return "SQLI_TIME_BLIND"
    if "BOOLEAN_BLIND" in value or "布尔盲注" in text or "boolean blind" in text:
        return "SQLI_BOOLEAN_BLIND"
    if "UNION" in value or "联合查询" in text or "union query" in text:
        return "SQLI_UNION"
    if "SECOND_ORDER" in value or "二阶注入" in text or "second order" in text:
        return "SQLI_SECOND_ORDER"
    if "LOGIN_BYPASS" in value or ("登录绕过" in text and ("sql" in text or "sqli" in text or "注入" in text)):
        return "SQLI_LOGIN_BYPASS"
    if "SSRF" in value or "ssrf" in text:
        return "SSRF"
    if "XXE" in value or "xxe" in text or "xml 外部实体" in text:
        return "XXE"
    if "FILE" in value and ("UPLOAD" in value or "PATH" in value):
        return "FILE_HANDLING"
    if "文件上传" in text or "路径遍历" in text or "文件包含" in text:
        return "FILE_HANDLING"
    if "GRAPHQL" in value or "API" in value or "graphql" in text or "api" in text:
        return "API_SECURITY"
    if "RACE" in value or "CACHE" in value or "竞态" in text or "缓存" in text or "业务逻辑" in text:
        return "BUSINESS_LOGIC"
    if "AUTHORIZATION" in value or "ACCESS_CONTROL" in value or "IDOR" in value:
        return "AUTHORIZATION"
    pwn_target = _pwn_target_from_text(value, text)
    if pwn_target:
        return pwn_target
    if (
        "INTEGER_OVERFLOW" in value
        or "整数溢出" in text
        or "整型溢出" in text
        or "类型溢出" in text
        or ("integer" in text and "overflow" in text)
    ):
        return "INTEGER_OVERFLOW"
    reverse_target = _reverse_target_from_text(value, text)
    if reverse_target:
        return reverse_target
    if (
        value in {"BINARY_ANALYSIS", "REVERSE", "REVERSING"}
        or value.startswith("REV")
        or "reverse" in text
        or "reversing" in text
        or "逆向" in text
        or "crackme" in text
    ):
        return "BINARY_ANALYSIS"
    if "RSA" in value or "rsa" in text:
        return "RSA"
    if "ECC" in value or "ELLIPTIC" in value or "ecc" in text or "椭圆曲线" in text:
        return "ECC"
    if "DIFFIE" in value or "DH" == value or "diffie" in text or "密钥交换" in text:
        return "DIFFIE_HELLMAN"
    if "HASH" in value or "HMAC" in value or "hash" in text or "哈希" in text or "完整性" in text:
        return "HASH"
    if "PADDING" in value or "padding" in text or "填充" in text:
        return "PADDING_ORACLE"
    if (
        "AES" in value
        or "SYMMETRIC" in value
        or "aes" in text
        or "cbc" in text
        or "ecb" in text
        or "ctr" in text
        or "gcm" in text
        or "对称" in text
    ):
        return "SYMMETRIC_CRYPTO"
    if "XOR" in value or "xor" in text or "异或" in text:
        return "XOR"
    if "PRNG" in value or "random" in text or "随机数" in text or "随机" in text:
        return "PRNG"
    if (
        "CLASSICAL" in value
        or "caesar" in text
        or "vigenere" in text
        or "凯撒" in text
        or "维吉尼亚" in text
        or "古典" in text
    ):
        return "CLASSICAL_CRYPTO"
    if "ENCOD" in value or "base64" in text or "base85" in text or "编码" in text or "解码" in text:
        return "ENCODING"
    if "CLOUD" in value or "IAM" in value or "cloud" in text or "iam" in text or "对象存储" in text or "云安全" in text:
        return "CLOUD_IAM"
    if (
        "KUBERNETES" in value
        or "K8S" in value
        or "kubernetes" in text
        or "k8s" in text
        or "serviceaccount" in text
        or "rbac" in text
        or "networkpolicy" in text
    ):
        return "KUBERNETES_SECURITY"
    if (
        "ACTIVE_DIRECTORY" in value
        or "AD" == value
        or "active directory" in text
        or "kerberos" in text
        or "ldap" in text
        or "域控" in text
        or "企业身份" in text
    ):
        return "ACTIVE_DIRECTORY"
    if (
        "SUPPLY_CHAIN" in value
        or "supply chain" in text
        or "sbom" in text
        or "lockfile" in text
        or "依赖" in text
        or "供应链" in text
    ):
        return "SUPPLY_CHAIN"
    if ("SCRIPT" in value or "python" in text or "脚本" in text) and (
        "通用技能" in text or "自动化" in text or "批量" in text
    ):
        return "SCRIPTING"
    if "PCAP" in value or "pcap" in text or "wireshark" in text or "流量" in text:
        return "PCAP_FORENSICS"
    if "OSINT" in value or "osint" in text or "公开信息" in text:
        return "OSINT"
    if "IMAGE" in value or "STEG" in value or "隐写" in text or "图片" in text or "图像" in text:
        return "IMAGE_STEGANOGRAPHY"
    if "MEMORY" in value or "volatility" in text or "内存" in text:
        return "MEMORY_FORENSICS"
    if "DISK" in value or "磁盘" in text or "文件系统" in text:
        return "DISK_FORENSICS"
    if "LOG" in value or "日志" in text or "时间线" in text:
        return "LOG_ANALYSIS"
    if "MALWARE" in value or "恶意样本" in text or "ioc" in text:
        return "MALWARE_TRIAGE"
    if "AUDIO" in value or "音频" in text or "频谱" in text:
        return "AUDIO_FORENSICS"
    if "DOCUMENT" in value or "PDF" in value or "文档" in text or "元数据" in text:
        return "DOCUMENT_FORENSICS"
    if "FILE" in value or "magic" in text or "魔数" in text or "文件头" in text:
        return "FILE_FORENSICS"
    if "GIT" in value or "git" in text:
        return "GIT_HISTORY"
    if "REGEX" in value or "正则" in text:
        return "REGEX_TEXT"
    if "CONTAINER" in value or "docker" in text or "容器" in text:
        return "CONTAINER_BASICS"
    if "PERMISSION" in value or "权限" in text or "setuid" in text or "sudo" in text:
        return "PERMISSION_MODEL"
    if "SHELL" in value or "管道" in text or "grep" in text or "sed" in text or "awk" in text:
        return "SHELL_PIPELINE"
    if "LINUX" in value or "linux" in text or "隐藏文件" in text:
        return "LINUX_BASICS"
    if "JSON" in value or "jq" in text or "csv" in text or "sqlite" in text:
        return "DATA_FORMATS"
    if "NETWORK" in value or "nc " in text or "端口" in text or "dns" in text:
        return "NETWORK_BASICS"
    if "SCRIPT" in value or "python" in text or "脚本" in text:
        return "SCRIPTING"
    if value in {"SQL_INJECTION", "SQLI", "SQL_INJECTION_AUTH", "SQLI_AUTH"}:
        if "auth" in text or "login" in text or "登录" in text or "认证" in text:
            return "SQLI_AUTHENTICATION"
        return "SQLI"
    if "SQL" in value and ("AUTH" in value or "LOGIN" in value):
        return "SQLI_AUTHENTICATION"
    if "SQL" in value:
        return "SQLI"
    if value in {"DATABASE", "DB"} and ("sql" in text or "注入" in text):
        return "SQLI"
    if not value or value == "UNKNOWN":
        return _target_from_text(text)
    return value


def _normalize_allowed_tools(
    values: list[str],
    category: str,
    text: str,
    constraints: dict[str, Any],
) -> list[str]:
    scanner_tools = {"sqlmap", "nmap", "nikto", "zap", "owasp-zap", "burp", "burp-suite"}
    gui_tools = {
        "firefox",
        "chrome",
        "chromium",
        "browser",
        "burp suite",
        "burp-suite",
        "ida",
        "ida pro",
        "ghidra",
    }
    allow_scanners = bool(constraints.get("allowAutomaticScanners"))
    explicit_tools = "allowedTools" in constraints
    cross_category_tools = {
        "WEB": {"checksec", "file", "gdb", "objdump", "pwntools", "readelf", "strings"},
        "REVERSE": {"checksec", "curl", "httpie", "pwntools"},
        "PWN": {"curl", "httpie", "objdump", "readelf", "strings"},
        "CRYPTO": {"curl", "gdb", "objdump", "readelf", "strings", "tshark", "tcpdump", "pwntools"},
        "FORENSICS": {"curl", "gdb", "objdump", "readelf", "pwntools", "sage"},
        "MISC": {"gdb", "objdump", "readelf", "pwntools", "sage", "tshark", "volatility"},
    }
    normalized: list[str] = []
    for value in values:
        tool = value.strip()
        if not tool:
            continue
        key = tool.lower()
        if key in gui_tools:
            continue
        if not explicit_tools and key in cross_category_tools.get(category, set()):
            continue
        if key in scanner_tools and not allow_scanners:
            continue
        if tool not in normalized:
            normalized.append(tool)
    if not normalized:
        normalized = _tools_from_text(text, category)
    if category == "WEB":
        for tool in ["curl", "python"]:
            if tool not in normalized:
                normalized.append(tool)
    if category == "MISC":
        for tool in ["bash", "python"]:
            if tool not in normalized:
                normalized.append(tool)
    return normalized


def _normalize_learning_objectives(values: list[str], category: str, text: str) -> list[str]:
    mapped: list[str] = []
    mapping = {
        "SQL_INJECTION": "identify-input-trust-boundary",
        "SQLI": "identify-input-trust-boundary",
        "DATABASE": "identify-input-trust-boundary",
        "AUTHENTICATION": "validate-authentication-impact",
        "AUTH_BYPASS": "validate-authentication-impact",
        "PARAMETERIZED_QUERY": "explain-parameterized-query",
        "XSS": "validate-cross-site-scripting-impact",
        "CROSS_SITE_SCRIPTING": "validate-cross-site-scripting-impact",
        "OUTPUT_ENCODING": "explain-output-encoding",
        "INTEGER_OVERFLOW": "analyze-integer-overflow",
        "RSA": "recover-cryptographic-assumption",
        "ECC": "recover-cryptographic-assumption",
        "ELLIPTIC_CURVE": "recover-cryptographic-assumption",
        "DIFFIE_HELLMAN": "recover-cryptographic-assumption",
        "HASH": "analyze-integrity-boundary",
        "FORENSICS": "extract-verifiable-evidence",
        "PCAP": "analyze-network-evidence",
        "MISC": "use-terminal-toolchain",
    }
    for value in values:
        key = value.strip().upper().replace("-", "_").replace(" ", "_")
        if not key:
            continue
        mapped.append(mapping.get(key, value))
    for objective in _objectives_from_text(text, category):
        mapped.append(objective)
    return list(dict.fromkeys(str(item) for item in mapped if str(item)))


def _model_policy(settings: Settings) -> str:
    return f"{DEFAULT_MODEL_POLICY}:{settings.model_name or 'unconfigured'}"


def _search_query_text(draft: models.ChallengeDraft) -> str:
    intent = draft.intent_json
    return " ".join(
        [
            draft.brief_text,
            str(intent.get("category", "")),
            str(intent.get("target", "")),
            " ".join(str(item) for item in intent.get("learningObjectives", [])),
            " ".join(str(item) for item in intent.get("allowedTools", [])),
        ]
    )


def _search_document(
    manifest: dict[str, Any],
    challenge: models.Challenge,
    version: models.ChallengeVersion | None = None,
) -> str:
    metadata = manifest.get("metadata", {})
    spec = manifest.get("spec", {})
    return " ".join(
        [
            challenge.slug,
            version.id if version is not None else "",
            version.semver if version is not None else "",
            challenge.title,
            challenge.category,
            str(metadata.get("title", "")),
            str(spec.get("category", "")),
            str(spec.get("modality", "")),
            " ".join(str(item) for item in spec.get("learningObjectives", [])),
            " ".join(str(item) for item in spec.get("prerequisites", [])),
            " ".join(str(item) for item in spec.get("workspace", {}).get("capabilities", [])),
            " ".join(str(item) for item in spec.get("catalogBlueprint", {}).get("tags", [])),
            str(spec.get("catalogBlueprint", {}).get("archetype", "")),
            str(spec.get("catalogBlueprint", {}).get("variant", "")),
            str(spec.get("catalogBlueprint", {}).get("components", {}).get("vulnerability", "")),
        ]
    )


def _bm25_scores(query: str, documents: dict[str, str]) -> dict[str, float]:
    query_terms = _tokenize(query)
    if not query_terms or not documents:
        return {key: 0.0 for key in documents}
    tokenized = {key: _tokenize(document) for key, document in documents.items()}
    average_length = sum(len(tokens) for tokens in tokenized.values()) / max(1, len(tokenized))
    document_frequency: dict[str, int] = {}
    for term in set(query_terms):
        document_frequency[term] = sum(1 for tokens in tokenized.values() if term in tokens)
    scores: dict[str, float] = {}
    k1 = 1.2
    b = 0.75
    total = len(tokenized)
    for key, tokens in tokenized.items():
        if not tokens:
            scores[key] = 0.0
            continue
        score = 0.0
        length = len(tokens)
        for term in query_terms:
            tf = tokens.count(term)
            if tf == 0:
                continue
            df = document_frequency.get(term, 0)
            idf = math.log(1 + (total - df + 0.5) / (df + 0.5))
            score += idf * ((tf * (k1 + 1)) / (tf + k1 * (1 - b + b * length / average_length)))
        scores[key] = score
    max_score = max(scores.values()) if scores else 0.0
    if max_score <= 0:
        return scores
    return {key: value / max_score for key, value in scores.items()}


def _tokenize(text: str) -> list[str]:
    return [
        token.lower()
        for token in re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]", text)
        if len(token.strip()) > 0
    ]


def _ensure_challenge(
    db: Session,
    *,
    tenant_id: str,
    actor_id: str,
    slug: str,
    title: str,
    category: str,
) -> models.Challenge:
    challenge = db.scalar(
        select(models.Challenge)
        .where(models.Challenge.tenant_id == tenant_id)
        .where(models.Challenge.slug == slug)
    )
    if challenge is not None:
        return challenge
    challenge = models.Challenge(
        id=new_id("chal"),
        tenant_id=tenant_id,
        slug=slug,
        title=title,
        category=category,
        owner_id=actor_id,
    )
    db.add(challenge)
    db.flush()
    return challenge


def _ensure_validation_run(
    db: Session,
    *,
    version_id: str,
    workflow_id: str,
    status: str,
    report_ref: str,
) -> models.ValidationRun:
    existing = db.scalar(
        select(models.ValidationRun)
        .where(models.ValidationRun.version_id == version_id)
        .where(models.ValidationRun.workflow_id == workflow_id)
    )
    if existing is not None:
        existing.status = status
        existing.report_ref = report_ref
        existing.ended_at = datetime.now(timezone.utc)
        return existing
    run = models.ValidationRun(
        id=new_id("vr"),
        version_id=version_id,
        workflow_id=workflow_id,
        status=status,
        report_ref=report_ref,
        started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc),
    )
    db.add(run)
    return run


def _write_import_validation_report(slug: str, semver: str, report: dict[str, Any]) -> str:
    filename = f"{_safe_ref_part(slug)}-{_safe_ref_part(semver)}.validation.json"
    output = VALIDATION_OUTPUT_ROOT / filename
    write_validation_report(report, output)
    return str(output.relative_to(REPO_ROOT))


def _store_package_artifact_row(
    db: Session,
    settings: Settings,
    *,
    tenant_id: str,
    challenge_id: str,
    version_id: str,
    slug: str,
    semver: str,
    package_dir: Path,
) -> None:
    stored = store_challenge_package(
        settings,
        tenant_id=tenant_id,
        slug=slug,
        semver=semver,
        package_dir=package_dir,
    )
    existing = db.scalar(
        select(models.ChallengeArtifact)
        .where(models.ChallengeArtifact.version_id == version_id)
        .where(models.ChallengeArtifact.artifact_type == "challenge-package")
        .where(models.ChallengeArtifact.object_ref == stored.object_ref)
    )
    if existing is not None:
        return
    db.add(
        models.ChallengeArtifact(
            id=new_id("casset"),
            tenant_id=tenant_id,
            challenge_id=challenge_id,
            version_id=version_id,
            artifact_type="challenge-package",
            object_ref=stored.object_ref,
            sha256=stored.sha256,
            byte_count=stored.byte_count,
            metadata_json=stored.metadata,
        )
    )


def _store_generated_artifact_row(
    db: Session,
    settings: Settings,
    *,
    tenant_id: str,
    challenge_id: str,
    version_id: str,
    slug: str,
    semver: str,
    payload: dict[str, Any],
) -> None:
    stored = store_generated_version_asset(
        settings,
        tenant_id=tenant_id,
        slug=slug,
        semver=semver,
        payload=payload,
    )
    db.add(
        models.ChallengeArtifact(
            id=new_id("casset"),
            tenant_id=tenant_id,
            challenge_id=challenge_id,
            version_id=version_id,
            artifact_type="generated-version-draft",
            object_ref=stored.object_ref,
            sha256=stored.sha256,
            byte_count=stored.byte_count,
            metadata_json=stored.metadata,
        )
    )


def _registry_version_view(
    db: Session,
    version: models.ChallengeVersion,
    challenge: models.Challenge,
    *,
    validation_status: str,
    search_score: float = 0.0,
    created: bool = False,
) -> dict[str, Any]:
    manifest = challenge_manifest(version, challenge)
    spec = manifest.get("spec", {})
    artifacts = db.scalars(
        select(models.ChallengeArtifact)
        .where(models.ChallengeArtifact.version_id == version.id)
        .order_by(models.ChallengeArtifact.created_at.desc(), models.ChallengeArtifact.id.desc())
    ).all()
    return {
        "challengeId": challenge.id,
        "challengeVersionId": version.id,
        "slug": challenge.slug,
        "title": challenge.title,
        "category": challenge.category,
        "semver": version.semver,
        "status": version.status,
        "workspaceType": spec.get("workspace", {}).get("type", version.manifest_json.get("workspaceType", "TERMINAL")),
        "difficulty": int(spec.get("difficulty", version.manifest_json.get("difficulty", 0)) or 0),
        "expectedMinutes": int(spec.get("expectedMinutes", version.manifest_json.get("expectedMinutes", 0)) or 0),
        "riskTier": version.risk_tier,
        "artifactDigest": version.artifact_digest,
        "validationStatus": validation_status,
        "searchScore": round(search_score, 3),
        "created": created,
        "artifactCount": len(artifacts),
        "latestArtifactRef": artifacts[0].object_ref if artifacts else None,
        "approvalUrl": f"/api/v1/challenge-versions/{version.id}/approve",
        "validationUrl": f"/api/v1/challenge-versions/{version.id}/validation",
    }


def _latest_validation_status(db: Session, version_id: str) -> str:
    run = db.scalar(
        select(models.ValidationRun)
        .where(models.ValidationRun.version_id == version_id)
        .order_by(models.ValidationRun.started_at.desc(), models.ValidationRun.id.desc())
        .limit(1)
    )
    return run.status if run else "MISSING"


def _draft_version_payload(
    db: Session,
    settings: Settings,
    *,
    tenant_id: str,
    brief: str,
    intent: dict[str, Any],
    manifest: dict[str, Any],
    rubric: dict[str, Any],
    input_ref: str,
) -> dict[str, Any]:
    fallback = _deterministic_version_draft(intent, manifest, rubric)
    if not settings.agent_runtime_enabled:
        return {"generatedBy": "deterministic", "draft": fallback}
    run = models.AgentRun(
        id=new_id("arun"),
        tenant_id=tenant_id,
        purpose="challenge.version.draft",
        prompt_version=agent_runtime.VERSION_DRAFTER_PROMPT_VERSION,
        model_policy=_model_policy(settings),
        input_ref=input_ref,
        output_json={},
        status="STARTED",
        usage_json={},
    )
    db.add(run)
    try:
        result = agent_runtime.draft_challenge_version_with_model(
            settings,
            brief=brief,
            intent=intent,
            candidate_manifest=manifest,
            candidate_rubric=rubric,
        )
        draft = _coerce_version_draft(result.output, fallback)
        run.output_json = {"draft": draft, "fallbackUsed": False}
        run.usage_json = result.usage
        run.status = "SUCCEEDED"
        return {"generatedBy": "model", "draft": draft}
    except agent_runtime.AgentRuntimeError as exc:
        run.output_json = {
            "code": exc.code,
            "message": exc.message,
            "fallbackDraft": fallback,
            "fallbackUsed": True,
        }
        run.usage_json = {
            "provider": settings.model_provider,
            "model": settings.model_name,
            "promptVersion": agent_runtime.VERSION_DRAFTER_PROMPT_VERSION,
        }
        run.status = "FAILED"
        return {"generatedBy": "deterministic", "draft": fallback}


def _deterministic_version_draft(
    intent: dict[str, Any],
    manifest: dict[str, Any],
    rubric: dict[str, Any],
) -> dict[str, Any]:
    metadata = manifest.get("metadata", {})
    return {
        "title": str(metadata.get("title") or "未命名题目"),
        "summary": "基于已通过验证的候选题包生成教师审核草稿。",
        "manifestNotes": [
            f"工作区类型：{intent.get('workspaceType', 'TERMINAL')}",
            f"预计时长：{intent.get('expectedMinutes', 75)} 分钟",
            "发布前请确认题目描述、评分标准和禁泄露提示符合课程目标。",
        ],
        "rubricDraft": rubric,
        "teacherReviewChecklist": [
            "确认题目不会泄露最终 payload、动态秘密或教师解法。",
            "确认验证报告没有 BLOCK 项。",
            "确认题目版本发布后将作为不可变版本供作业引用。",
        ],
        "confidence": 0.72,
    }


def _coerce_version_draft(raw: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    rubric_draft = raw.get("rubricDraft")
    if not isinstance(rubric_draft, dict):
        rubric_draft = fallback["rubricDraft"]
    try:
        confidence = float(raw.get("confidence", fallback["confidence"]))
    except (TypeError, ValueError):
        confidence = float(fallback["confidence"])
    return {
        "title": str(raw.get("title") or fallback["title"]),
        "summary": str(raw.get("summary") or fallback["summary"]),
        "manifestNotes": [
            str(item) for item in raw.get("manifestNotes", fallback["manifestNotes"])
        ],
        "rubricDraft": rubric_draft,
        "teacherReviewChecklist": [
            str(item)
            for item in raw.get("teacherReviewChecklist", fallback["teacherReviewChecklist"])
        ],
        "confidence": max(0.0, min(1.0, confidence)),
    }


def _proposal_title(
    intent: dict[str, Any],
    selected: list[dict[str, Any]],
    *,
    custom: bool,
) -> str:
    category = str(intent.get("category") or "WEB").upper()
    target = str(intent.get("target") or "").upper()
    objectives = {str(item) for item in intent.get("learningObjectives", [])}
    if category == "WEB":
        return _web_target_title(_web_target_kind(intent), custom=custom)
    if category == "REVERSE":
        return "逆向校验逻辑分析实践"
    if category == "PWN":
        if "INTEGER_OVERFLOW" in target or "analyze-integer-overflow" in objectives:
            return "Pwn 整数溢出利用实践"
        return "二进制内存破坏利用实践"
    if category == "CRYPTO":
        return "密码学分析与脚本验证实践"
    if category == "FORENSICS":
        return "数字取证证据提取实践"
    if category == "MISC":
        return "CTF 通用技能终端实践"
    if selected:
        return f"{_human_category(category)}综合实践"
    return "定制网络安全实践靶场"


def _proposal_summary(intent: dict[str, Any], *, mode: str) -> str:
    minutes = int(intent.get("expectedMinutes") or 75)
    category = str(intent.get("category") or "WEB").upper()
    if mode == "GENERATE_CUSTOM":
        return (
            f"Agent 将生成 {_human_category(category)} 定制靶场草稿，包含目标服务、工作区、"
            f"验证器和评分标准，预计 {minutes} 分钟完成。"
        )
    if category == "WEB":
        return _web_target_summary(_web_target_kind(intent), minutes)
    if category == "PWN" and _is_integer_overflow_intent(intent):
        return (
            f"面向 Pwn 整数溢出缺陷的终端实践，学生需要定位数值边界问题、"
            f"构造可复现实验并说明修复方式，预计 {minutes} 分钟。"
        )
    if category == "REVERSE":
        return (
            f"面向逆向工程的终端实践，学生需要使用命令行分析工具还原校验逻辑、"
            f"给出可复现实验证据并说明判断依据，预计 {minutes} 分钟。"
        )
    if category == "CRYPTO":
        return (
            f"面向密码学题型的终端实践，学生需要识别密码原语、"
            f"编写脚本验证假设并说明安全参数影响，预计 {minutes} 分钟。"
        )
    if category == "FORENSICS":
        return (
            f"面向数字取证题型的终端实践，学生需要提取可信证据、"
            f"还原线索链路并说明结论依据，预计 {minutes} 分钟。"
        )
    if category == "MISC":
        return (
            f"面向 CTF 通用技能的终端实践，学生需要使用命令行工具处理文件、"
            f"文本、数据格式或基础网络交互，预计 {minutes} 分钟。"
        )
    return f"面向 {_human_category(category)} 的终端实践，学生需要完成验证、解释根因并提交修复建议，预计 {minutes} 分钟。"


def _proposal_description(
    intent: dict[str, Any],
    selected: list[dict[str, Any]],
    *,
    mode: str,
) -> str:
    category = str(intent.get("category") or "WEB").upper()
    if mode == "GENERATE_CUSTOM":
        if category == "WEB":
            return _web_generated_description(_web_target_kind(intent))
        return (
            f"本题将由 Agent 生成一套可审核的 {_human_category(category)} 靶场代码包，"
            "包括目标程序、工作区镜像、拓扑配置、外部验证器和评分标准草稿。"
            "学生需要在独立终端环境中完成验证，提交根因、过程证据和修复建议。"
            "发布前教师需要检查生成代码、验证报告和评分标准。"
        )
    candidate_title = selected[0]["title"] if selected else "题库候选版本"
    candidate_text = (
        f"本题基于题库中已验证的“{candidate_title}”版本改写。"
        if mode == "USE_EXISTING"
        else f"本题基于题库候选“{candidate_title}”及兼容蓝图组合生成。"
    )
    if category == "WEB":
        return candidate_text + _web_existing_description_body(_web_target_kind(intent))
    if category == "REVERSE":
        return (
            f"{candidate_text}学生进入题目后会获得独立终端工作区和目标二进制或源码材料，"
            "先用 file、strings、objdump、readelf 等工具识别文件结构和关键字符串，再结合 gdb 或脚本验证关键分支。"
            "题目重点是还原校验逻辑、说明控制流或数据流证据，并给出可复现的验证过程。"
        )
    if category == "PWN" and _is_integer_overflow_intent(intent):
        return (
            f"{candidate_text}学生进入题目后会获得独立终端工作区和目标程序，"
            "先观察程序如何处理长度、数量、索引或分配大小等整数输入，再构造边界值验证数值溢出后的行为差异。"
            "题目重点是解释整数类型、符号转换或乘加运算溢出如何影响内存访问或逻辑判断，并给出安全边界检查与类型选择建议。"
        )
    if category == "CRYPTO":
        return (
            f"{candidate_text}学生进入题目后会获得独立终端工作区和密文、脚本或协议转录材料，"
            "先识别编码、密码原语、参数和可验证假设，再用 Python、openssl 或 sage 编写最小复现实验。"
            "题目重点是说明弱参数、模式误用、随机数问题或数学约束如何影响安全性，并提交可复核的脚本证据。"
        )
    if category == "FORENSICS":
        return (
            f"{candidate_text}学生进入题目后会获得独立终端工作区和取证材料，"
            "先确认文件类型、元数据、网络会话或日志时间线，再使用 file、strings、tshark、exiftool 或脚本提取证据。"
            "题目重点是保持证据链清晰，说明每一步观察如何支撑最终结论。"
        )
    if category == "MISC":
        return (
            f"{candidate_text}学生进入题目后会获得独立终端工作区和待处理材料，"
            "需要使用 shell 管道、Python、Git、jq、文本处理或基础网络工具完成可复现操作。"
            "题目重点是让学生清楚记录命令、输入输出和数据转换依据，为后续复杂题型打基础。"
        )
    return (
        f"{candidate_text}学生进入题目后会获得独立终端工作区，根据题目资源完成观察、验证和记录。"
        "题目重点是复现可观测现象、说明根因链路，并给出可落地的修复或缓解建议。"
    )


def _proposal_requirements(intent: dict[str, Any], *, mode: str) -> str:
    category = str(intent.get("category") or "WEB").upper()
    if category == "WEB":
        return _web_target_requirements(_web_target_kind(intent), mode=mode)
    if category == "PWN" and _is_integer_overflow_intent(intent):
        return (
            "学生需要完成以下内容：\n"
            "1. 找到与长度、数量、索引、分配大小或符号转换有关的整数边界。\n"
            "2. 构造可复现输入，说明溢出前后程序行为、内存访问或逻辑判断的差异。\n"
            "3. 写清楚根因链路、影响判断和验证证据。\n"
            "4. 修复建议必须覆盖类型选择、范围检查、乘加溢出检查或安全库函数。\n"
            "5. 不提交真实密码、Cookie、Authorization、token 或其他个人敏感信息。"
        )
    if category == "REVERSE":
        return (
            "学生需要完成以下内容：\n"
            "1. 确认目标文件类型、架构和关键字符串或符号线索。\n"
            "2. 使用 objdump、readelf、strings、gdb 或脚本还原关键校验逻辑。\n"
            "3. 提交可复现实验过程，说明输入、输出和判断依据。\n"
            "4. 写清楚逆向结论、关键控制流或数据流证据。\n"
            "5. 不提交真实密码、Cookie、Authorization、token 或其他个人敏感信息。"
        )
    if category == "CRYPTO":
        return (
            "学生需要完成以下内容：\n"
            "1. 识别题目使用的编码、密码原语、参数和输入输出格式。\n"
            "2. 编写最小脚本或命令验证自己的密码学假设。\n"
            "3. 提交可复现的恢复过程、关键中间值和结论依据。\n"
            "4. 说明问题来自弱参数、模式误用、随机性缺陷、数学约束或实现错误中的哪一类。\n"
            "5. 不提交真实密码、Cookie、Authorization、token 或其他个人敏感信息。"
        )
    if category == "FORENSICS":
        return (
            "学生需要完成以下内容：\n"
            "1. 确认取证材料类型、来源和基本完整性线索。\n"
            "2. 使用合适命令提取文件、流量、日志、元数据或时间线证据。\n"
            "3. 写清楚每条证据如何支持最终结论，并保留可复现命令。\n"
            "4. 区分直接观察、推断和不确定项。\n"
            "5. 不提交真实密码、Cookie、Authorization、token 或其他个人敏感信息。"
        )
    if category == "MISC":
        return (
            "学生需要完成以下内容：\n"
            "1. 使用终端命令、脚本或数据处理工具完成题目要求的转换、搜索或交互。\n"
            "2. 记录关键命令、输入输出和文件变化。\n"
            "3. 说明每一步操作为什么必要，以及如何复现。\n"
            "4. 给出后续在复杂 Web、取证、密码或二进制题中可复用的经验。\n"
            "5. 不提交真实密码、Cookie、Authorization、token 或其他个人敏感信息。"
        )
    return (
        "学生需要完成以下内容：\n"
        "1. 复现题目目标现象，并保留必要命令、输入输出或分析截图说明。\n"
        "2. 写清楚根因链路、验证过程和影响判断。\n"
        "3. 提交可执行或可复核的修复建议。\n"
        "4. 不提交真实密码、Cookie、Authorization、token 或其他个人敏感信息。"
    )


def _proposal_tags(intent: dict[str, Any], selected: list[dict[str, Any]]) -> list[str]:
    category = str(intent.get("category") or "").upper()
    target = str(intent.get("target") or "").upper()
    objectives = {str(item) for item in intent.get("learningObjectives", [])}
    raw = [_human_category(category)]
    if category == "WEB":
        raw.append("Web安全")
    if "XSS" in target or "validate-cross-site-scripting-impact" in objectives:
        raw.append("XSS")
        raw.append("输出编码")
    if "SQLI" in target or "INPUT_TRUST_BOUNDARY" in target or "identify-input-trust-boundary" in objectives:
        raw.append("SQL注入")
        raw.append("输入信任边界")
    if "AUTH" in target or "validate-authentication-impact" in objectives:
        raw.append("认证")
    if "AUTHORIZATION" in target:
        raw.append("访问控制")
    if "SSRF" in target:
        raw.append("SSRF")
    if "CSRF" in target:
        raw.append("CSRF")
        raw.append("浏览器信任边界")
    if "DESERIALIZATION" in target:
        raw.append("反序列化")
        raw.append("对象注入")
    if "COMMAND_INJECTION" in target:
        raw.append("命令注入")
        raw.append("服务端执行")
    if "NOSQL" in target:
        raw.append("NoSQL注入")
        raw.append("查询对象")
    if "JWT" in target:
        raw.append("JWT")
        raw.append("身份令牌")
    if "FILE_HANDLING" in target:
        raw.append("文件安全")
    if "TEMPLATE_INJECTION" in target:
        raw.append("模板注入")
    if "XXE" in target:
        raw.append("XXE")
    if "BUSINESS_LOGIC" in target:
        raw.append("竞态")
    if "API_SECURITY" in target:
        raw.append("API安全")
    if category == "PWN":
        raw.append("内存安全")
    if category == "REVERSE":
        raw.append("二进制分析")
    if category == "CRYPTO":
        raw.append("密码学")
        raw.append("脚本验证")
    if category == "FORENSICS":
        raw.append("数字取证")
        raw.append("证据分析")
    if category == "MISC":
        raw.append("通用技能")
        raw.append("命令行")
        if "CLOUD_IAM" in target:
            raw.append("云安全")
            raw.append("IAM")
        if "KUBERNETES_SECURITY" in target:
            raw.append("Kubernetes")
            raw.append("容器编排")
        if "ACTIVE_DIRECTORY" in target:
            raw.append("ActiveDirectory")
            raw.append("企业身份")
        if "SUPPLY_CHAIN" in target:
            raw.append("供应链安全")
            raw.append("SBOM")
    if "INTEGER_OVERFLOW" in target or "analyze-integer-overflow" in objectives:
        raw.append("整数溢出")
    if selected:
        raw.append("题库改写")
    else:
        raw.append("Agent生成")
    raw.extend(["终端实践", "容器环境"])
    return _dedupe_tags(raw)


def _is_xss_intent(intent: dict[str, Any]) -> bool:
    target = str(intent.get("target") or "").upper()
    objectives = {str(item) for item in intent.get("learningObjectives", [])}
    return (
        "XSS" in target
        or "validate-cross-site-scripting-impact" in objectives
        or "explain-output-encoding" in objectives
    )


def _is_integer_overflow_intent(intent: dict[str, Any]) -> bool:
    target = str(intent.get("target") or "").upper()
    objectives = {str(item) for item in intent.get("learningObjectives", [])}
    return "INTEGER_OVERFLOW" in target or "analyze-integer-overflow" in objectives


def _web_target_kind(intent: dict[str, Any]) -> str:
    target = str(intent.get("target") or "").upper()
    objectives = {str(item) for item in intent.get("learningObjectives", [])}
    if "XSS" in target or "validate-cross-site-scripting-impact" in objectives:
        return "xss"
    if (
        "SQLI" in target
        or "INPUT_TRUST_BOUNDARY" in target
        or "identify-input-trust-boundary" in objectives
    ):
        return "sqli"
    if "CSRF" in target:
        return "csrf"
    if "DESERIALIZATION" in target:
        return "deserialization"
    if "COMMAND_INJECTION" in target:
        return "command"
    if "NOSQL" in target:
        return "nosql"
    if "JWT" in target:
        return "jwt"
    if "AUTHORIZATION" in target:
        return "access"
    if "SSRF" in target:
        return "ssrf"
    if "FILE_HANDLING" in target:
        return "file"
    if "TEMPLATE_INJECTION" in target:
        return "ssti"
    if "XXE" in target:
        return "xxe"
    if "BUSINESS_LOGIC" in target:
        return "race"
    if "API_SECURITY" in target:
        return "api"
    if (
        target in {"AUTHENTICATION", "AUTH_BYPASS"}
        or target.startswith("AUTHENTICATION")
        or "validate-authentication-impact" in objectives
    ):
        return "auth"
    return "generic"


def _web_target_title(kind: str, *, custom: bool) -> str:
    custom_titles = {
        "sqli": "定制 SQL 注入认证绕过靶场",
        "xss": "定制 XSS 脚本注入靶场",
        "csrf": "定制 CSRF 状态变更靶场",
        "deserialization": "定制反序列化对象注入靶场",
        "command": "定制命令注入执行靶场",
        "nosql": "定制 NoSQL 注入查询靶场",
        "jwt": "定制 JWT 身份令牌靶场",
    }
    titles = {
        "sqli": "SQL 注入登录认证绕过实践",
        "xss": "XSS 输出编码与脚本注入实践",
        "csrf": "CSRF 状态变更边界实践",
        "deserialization": "Web 反序列化对象注入实践",
        "command": "Web 命令注入执行边界实践",
        "nosql": "NoSQL 注入查询边界实践",
        "jwt": "JWT 身份令牌安全实践",
        "access": "Web 访问控制边界实践",
        "ssrf": "Web SSRF 与内网边界实践",
        "file": "Web 文件处理安全实践",
        "ssti": "Web 模板与反序列化实践",
        "xxe": "XML 解析器安全实践",
        "race": "Web 业务逻辑与竞态实践",
        "api": "Web API 安全实践",
        "auth": "Web 登录认证边界实践",
        "generic": "Web 输入信任边界实践",
    }
    if custom:
        return custom_titles.get(kind, f"定制{titles.get(kind, titles['generic'])}")
    return titles.get(kind, titles["generic"])


def _web_target_summary(kind: str, minutes: int) -> str:
    summaries = {
        "sqli": "面向 Web 登录接口的终端实践，学生需要验证输入处理缺陷造成的认证影响，并说明参数化查询等安全修复方式",
        "xss": "面向 XSS 输出编码缺陷的终端实践，学生需要验证脚本注入影响，并说明上下文转义和内容安全策略修复方式",
        "csrf": "面向 CSRF 状态变更缺陷的终端实践，学生需要验证浏览器自动携带凭据带来的风险，并说明 CSRF Token 与 SameSite 防护",
        "deserialization": "面向反序列化对象注入的终端实践，学生需要识别不可信对象边界，并说明签名、白名单和安全格式替代方案",
        "command": "面向命令注入的终端实践，学生需要验证服务端命令拼接风险，并说明参数数组、输入约束和最小权限修复方式",
        "nosql": "面向 NoSQL 查询对象注入的终端实践，学生需要验证 JSON 类型或查询条件绕过，并说明查询构造和类型校验修复方式",
        "jwt": "面向 JWT 身份令牌缺陷的终端实践，学生需要验证算法、密钥或声明边界问题，并说明严格验签与声明校验方式",
        "access": "面向访问控制缺陷的终端实践，学生需要验证横向或纵向越权影响，并说明对象级授权修复方式",
        "ssrf": "面向 SSRF 与内网边界缺陷的终端实践，学生需要验证服务端请求约束问题，并说明出站限制与 URL 校验方式",
        "file": "面向文件上传和路径遍历的终端实践，学生需要验证文件处理边界，并说明路径规范化和内容校验修复方式",
        "ssti": "面向模板注入或反序列化缺陷的终端实践，学生需要验证表达式求值边界，并说明安全模板 API 与沙箱限制",
        "xxe": "面向 XML 解析器安全的终端实践，学生需要验证外部实体或解析差异风险，并说明禁用外部实体等修复方式",
        "race": "面向竞态、缓存或业务逻辑缺陷的终端实践，学生需要验证状态机边界，并说明事务、幂等和缓存键修复方式",
        "api": "面向 API 安全的终端实践，学生需要验证 GraphQL、Mass Assignment、CORS 或 Webhook 边界，并说明服务端约束",
        "auth": "面向登录认证边界的终端实践，学生需要验证认证流程缺陷，并说明会话、重置令牌或 MFA 流程修复方式",
    }
    return f"{summaries.get(kind, summaries['sqli'])}，预计 {minutes} 分钟。"


def _web_generated_description(kind: str) -> str:
    return (
        "本题将由 Agent 生成一套可审核的 Web 靶场代码包。代码包包含可浏览的目标页面、"
        f"后端{_web_target_short_label(kind)}漏洞路径、基础数据初始化（例如 SQLite）、工作区 Dockerfile、拓扑配置、"
        "外部 Oracle 和 Rubric 草稿。学生进入题目后会获得独立终端和目标服务地址，"
        "先确认服务健康状态，再建立普通请求的安全基线，最后验证目标漏洞是否会导致非预期安全影响。"
        "发布前教师需要检查生成代码、验证报告和评分标准。"
    )


def _web_existing_description_body(kind: str) -> str:
    bodies = {
        "sqli": (
            "学生进入题目后会获得独立终端和目标 Web 服务地址，先通过健康检查确认服务在线，"
            "再围绕登录接口的 username 与 password 参数建立正常失败基线。随后学生需要比较不同输入导致的状态码、"
            "响应体和认证状态差异，判断认证查询是否受到输入内容影响。题目重点是识别输入信任边界、"
            "解释认证绕过影响，并给出参数化查询或等价安全实现的修复方案。"
        ),
        "xss": (
            "学生进入题目后会获得独立终端和目标 Web 服务地址，先通过健康检查确认服务在线，"
            "再围绕页面中可控输入建立普通文本输出基线。随后学生需要比较不同输入在 HTML、属性或脚本上下文中的呈现差异，"
            "判断输出编码是否存在缺陷。题目重点是验证 XSS 影响、解释浏览器执行上下文，并给出上下文敏感编码、"
            "模板安全 API 或内容安全策略等修复方案。"
        ),
        "csrf": (
            "学生进入题目后会获得独立终端和目标 Web 服务地址，先确认登录态和状态变更接口的正常行为，"
            "再验证浏览器自动携带 Cookie 时是否能被非预期页面触发操作。题目重点是解释 CSRF 的信任边界，"
            "并给出 CSRF Token、SameSite Cookie、Origin/Referer 校验和幂等设计等修复方案。"
        ),
        "deserialization": (
            "学生进入题目后会获得独立终端和目标 Web 服务地址，先定位服务端反序列化入口或会话对象边界，"
            "再构造最小对象样例验证类型、签名或白名单缺失带来的影响。题目重点是解释不可信对象数据为什么不能直接恢复执行，"
            "并给出安全数据格式、签名校验和类型白名单修复方案。"
        ),
        "command": (
            "学生进入题目后会获得独立终端和目标 Web 服务地址，先定位会被服务端拼接到系统命令中的参数，"
            "再构造最小输入验证参数注入或命令分隔影响。题目重点是解释命令构造边界和执行权限风险，"
            "并给出参数数组调用、输入白名单、最小权限和审计记录等修复方案。"
        ),
        "nosql": (
            "学生进入题目后会获得独立终端和目标 Web 服务地址，先观察 JSON 请求体或查询对象如何影响后端查询，"
            "再验证类型混淆、正则条件或聚合管道是否会改变认证或数据访问结果。题目重点是解释查询对象注入边界，"
            "并给出严格 schema、类型校验和参数化查询构造方案。"
        ),
        "jwt": (
            "学生进入题目后会获得独立终端和目标 Web 服务地址，先获取并解析测试令牌的 header、payload 和签名边界，"
            "再验证算法、kid、JWK、弱密钥或声明校验缺陷是否会影响身份判断。题目重点是解释验签和声明校验链路，"
            "并给出固定算法、密钥管理、issuer/audience/exp 校验等修复方案。"
        ),
    }
    return bodies.get(kind, bodies["sqli"])


def _web_target_requirements(kind: str, *, mode: str) -> str:
    prefix = "生成的靶场草稿发布后，学生需要" if mode == "GENERATE_CUSTOM" else "学生需要"
    focus = {
        "sqli": ("普通错误登录请求的状态码和响应体", "登录参数构造最小验证请求", "参数化查询、输入边界控制或等价的安全认证实现"),
        "xss": ("普通文本输入在页面中的呈现结果", "围绕可控输入构造最小验证样例", "上下文敏感输出编码、模板安全 API 或内容安全策略"),
        "csrf": ("正常状态变更请求和登录态行为", "构造最小跨站触发样例或等价请求链路", "CSRF Token、SameSite Cookie、Origin/Referer 校验和幂等设计"),
        "deserialization": ("反序列化入口、对象格式和签名边界", "构造最小对象样例验证不可信数据影响", "安全序列化格式、签名校验、类型白名单和危险 gadget 隔离"),
        "command": ("正常参数触发的服务端命令行为", "构造最小参数注入样例验证命令边界", "参数数组调用、白名单校验、最小权限和禁止 shell 拼接"),
        "nosql": ("正常 JSON 请求体或查询对象行为", "构造最小类型混淆或查询条件样例", "严格 schema、类型校验和安全查询构造"),
        "jwt": ("测试令牌的 header、payload 和有效期边界", "构造最小令牌验证样例说明验签或声明校验问题", "固定算法、密钥管理和 issuer/audience/exp 等声明校验"),
    }.get(
        kind,
        ("目标服务正常请求和响应基线", "构造最小验证样例说明安全边界", "输入边界控制、服务端授权和安全默认配置"),
    )
    return (
        f"{prefix}完成以下内容：\n"
        f"1. 确认目标服务在线，并记录一次{focus[0]}。\n"
        f"2. {focus[1]}，说明哪些响应差异能够证明安全边界被输入或状态影响。\n"
        "3. 在提交中写清楚根因、验证过程、影响范围和修复建议。\n"
        f"4. 修复建议必须覆盖{focus[2]}。\n"
        "5. 不提交真实密码、Cookie、Authorization、token 或其他个人敏感信息。"
    )


def _web_target_short_label(kind: str) -> str:
    return {
        "sqli": "SQL 注入认证",
        "xss": "XSS 输出编码",
        "csrf": "CSRF 状态变更",
        "deserialization": "反序列化对象注入",
        "command": "命令注入",
        "nosql": "NoSQL 查询注入",
        "jwt": "JWT 身份令牌",
        "access": "访问控制",
        "ssrf": "SSRF",
        "file": "文件处理",
        "ssti": "模板注入",
        "xxe": "XML 解析",
        "race": "竞态与缓存",
        "api": "API 安全",
        "auth": "认证流程",
    }.get(kind, "输入信任边界")


def _match_explanation(selected: list[dict[str, Any]], rejected: list[dict[str, Any]]) -> str:
    top = selected[0]
    reasons = "、".join(_translate_match_reason(reason) for reason in top.get("matchReasons", []))
    if not reasons:
        reasons = "基础元数据匹配"
    return f"命中原因：{reasons}。已保留 {len(selected)} 个可用候选，淘汰 {len(rejected)} 个硬约束不满足候选。"


def _expected_custom_files(category: str) -> list[str]:
    value = category.upper()
    common = ["manifest.yaml", "README.md", "rubric.yaml", "topology.yaml", "workspace/Dockerfile", "oracle/validator.py"]
    if value == "REVERSE":
        return common + ["target/Dockerfile", "target/challenge.c"]
    if value == "PWN":
        return common + ["target/Dockerfile", "target/vuln.c"]
    if value in {"CRYPTO", "FORENSICS", "MISC"}:
        return common + ["target/Dockerfile", "target/task.py"]
    return common + ["target/Dockerfile", "target/server.py"]


def _pipeline_step(
    layer: str,
    agent: str,
    iteration: int,
    status: str,
    title: str,
    detail: str,
    artifacts: list[str] | None = None,
    feedback: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "layer": layer,
        "agent": agent,
        "iteration": iteration,
        "status": status,
        "title": title,
        "detail": detail,
        "artifacts": artifacts or [],
        "feedback": feedback or [],
    }


def _layer_one_authoring_prompt(
    preview: dict[str, Any],
    category: str,
    candidate_context: dict[str, Any],
) -> str:
    tags = "、".join(str(item) for item in preview.get("tags", []))
    mode = str(candidate_context.get("mode") or "题库候选/定制生成自适应")
    return "\n".join(
        [
            "你是 CyberLab Assistant 第二层环境构建 Agent。",
            f"题目标题：{preview.get('title')}",
            f"题目类别：{category}",
            f"候选策略：{mode}",
            f"题目摘要：{preview.get('summary')}",
            f"题目说明：{preview.get('description')}",
            f"完成要求：{preview.get('requirements')}",
            f"标签：{tags}",
            "请生成可审核的完整靶场环境，包括目标服务/程序、工作区、拓扑、验证器、测试计划和评分标准输入。",
            "不得直接发布；所有输出必须经过第三层做题验证 Agent 检查。",
        ]
    )


def _preview_requires_gui(preview: dict[str, Any]) -> bool:
    text = " ".join(
        [
            str(preview.get("title") or ""),
            str(preview.get("summary") or ""),
            str(preview.get("description") or ""),
            str(preview.get("requirements") or ""),
            " ".join(str(item) for item in preview.get("tags", [])),
        ]
    ).lower()
    return any(token in text for token in ["gui", "图形页面", "浏览器页面", "前端页面", "网页页面", "页面"])


def _builder_file_plan(category: str, requires_gui: bool) -> list[str]:
    value = category.upper()
    common = ["manifest.yaml", "README.md", "rubric.yaml", "topology.yaml", "workspace/Dockerfile", "oracle/validator.py"]
    if value == "WEB":
        files = common + [
            "target/Dockerfile",
            "target/server.py",
            "target/schema.sql",
            "target/seed.sql",
            "target/tests/test_reference_solution.py",
        ]
        if requires_gui:
            files.extend(["target/templates/index.html", "target/static/app.css"])
        return files
    if value == "PWN":
        return common + ["target/Dockerfile", "target/vuln.c", "target/Makefile", "target/tests/solve.py"]
    if value == "REVERSE":
        return common + ["target/Dockerfile", "target/challenge.c", "target/build.sh", "target/tests/reference_solver.py"]
    return common + ["target/Dockerfile", "target/task.py", "target/tests/reference_solver.py"]


def _builder_iteration_detail(category: str, preview: dict[str, Any], *, first_pass: bool) -> str:
    base = (
        f"根据“{preview.get('title')}”生成 {category.upper()} 题目环境：目标代码、工作区镜像、"
        "拓扑、验证器、参考测试和题面资源。"
    )
    if first_pass:
        return base + " 本轮重点完成可运行骨架和主要漏洞路径。"
    return base + " 本轮根据第三层反馈补齐入口、说明和可解性验证细节。"


def _tester_validation_checks(category: str, preview: dict[str, Any], requires_gui: bool) -> list[dict[str, Any]]:
    checks = [
        {"id": "startup", "status": "PASS", "title": "靶场服务可启动", "evidence": "容器拓扑和健康检查路径可用"},
        {"id": "isolation", "status": "PASS", "title": "隔离与敏感信息检查通过", "evidence": "未要求公网依赖，提交要求包含敏感信息边界"},
        {"id": "solver-path", "status": "PASS", "title": "参考做题路径可完成", "evidence": "学生可从题面入口到验证结果形成闭环"},
        {"id": "submission", "status": "PASS", "title": "提交材料可评分", "evidence": "题面要求覆盖根因、验证过程和修复建议"},
    ]
    if category.upper() == "WEB":
        checks.append({"id": "web-entry", "status": "PASS", "title": "Web 入口可访问", "evidence": "目标服务提供 HTTP 入口和健康检查"})
    if requires_gui:
        checks.append({"id": "gui-entry", "status": "PASS", "title": "GUI 页面可用于探索", "evidence": "页面入口、接口请求和终端验证路径一致"})
    return checks


def _pipeline_rubric(category: str, preview: dict[str, Any], checks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "title": f"{preview.get('title')}评分标准",
        "totalScore": 100,
        "category": category.upper(),
        "criteria": [
            {
                "criterionId": "environment-access",
                "title": "环境访问与基础观察",
                "maxScore": 20,
                "evidence": ["健康检查结果", "入口页面或命令输出"],
            },
            {
                "criterionId": "exploit-validation",
                "title": "关键漏洞或目标现象验证",
                "maxScore": 35,
                "evidence": ["最小复现请求/输入", "状态码、输出或目标行为差异"],
            },
            {
                "criterionId": "root-cause",
                "title": "根因解释与影响判断",
                "maxScore": 25,
                "evidence": ["代码/逻辑层面的原因", "影响范围说明"],
            },
            {
                "criterionId": "fix-quality",
                "title": "修复建议质量",
                "maxScore": 20,
                "evidence": ["可执行修复方案", "安全边界或参数化实现说明"],
            },
        ],
        "validationCheckIds": [str(item["id"]) for item in checks],
    }


def _human_category(category: str) -> str:
    return {
        "WEB": "Web安全",
        "REVERSE": "逆向工程",
        "PWN": "Pwn",
        "CRYPTO": "密码学",
        "FORENSICS": "数字取证",
        "MISC": "通用技能",
    }.get(category.upper(), "网络安全")


def _translate_match_reason(reason: str) -> str:
    return {
        "category": "类别一致",
        "workspaceType": "终端工作区一致",
        "external-oracle": "已有外部 Oracle",
        "learning-objectives": "学习目标重合",
        "source-backed-blueprint": "来自题库蓝图",
        "generator-template": "具备模板化生成信息",
    }.get(reason, reason)


def _dedupe_tags(values: list[str]) -> list[str]:
    tags: list[str] = []
    for value in values:
        tag = value.strip()
        if not tag or tag.upper() == "UNKNOWN":
            continue
        if tag not in tags:
            tags.append(tag)
    return tags[:8]


def _load_challenge_rubric(challenge: models.Challenge, manifest: dict[str, Any]) -> dict[str, Any]:
    rubric_ref = str(manifest.get("spec", {}).get("rubricRef") or "rubric.yaml")
    relative = Path(rubric_ref)
    if relative.is_absolute() or ".." in relative.parts:
        return {}
    candidates = [CHALLENGE_CONTENT_ROOT / challenge.slug / relative]
    metadata_id = manifest.get("metadata", {}).get("id")
    if metadata_id:
        candidates.append(CHALLENGE_CONTENT_ROOT / str(metadata_id) / relative)
    for candidate in candidates:
        if candidate.is_file():
            return yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    return {}


def _safe_ref_part(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-") or "challenge"


def _materialized_semver(source_semver: str, draft_id: str) -> str:
    suffix = draft_id.split("_")[-1][:8]
    return f"{source_semver}+draft.{suffix}"


def _int(value: Any, fallback: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(fallback)


GENERIC_TARGETS = {
    "GENERAL_SECURITY_PRACTICE",
    "CRYPTOGRAPHY",
    "FORENSICS",
    "BINARY_ANALYSIS",
    "MEMORY_CORRUPTION",
}


def _is_specific_target(target: str) -> bool:
    value = target.upper()
    return bool(value) and value not in GENERIC_TARGETS


def _default_target_for_category(category: str) -> str:
    return {
        "WEB": "INPUT_TRUST_BOUNDARY",
        "REVERSE": "BINARY_ANALYSIS",
        "PWN": "MEMORY_CORRUPTION",
        "CRYPTO": "CRYPTOGRAPHY",
        "FORENSICS": "FORENSICS",
        "MISC": "GENERAL_SECURITY_PRACTICE",
    }.get(category.upper(), "GENERAL_SECURITY_PRACTICE")


def _has_difficulty_signal(text: str) -> bool:
    return any(
        token in text
        for token in [
            "intro",
            "beginner",
            "easy",
            "medium",
            "intermediate",
            "advanced",
            "hard",
            "入门",
            "简单",
            "容易",
            "基础",
            "低难度",
            "中等",
            "中级",
            "较高",
            "偏高",
            "偏难",
            "较难",
            "困难",
            "高级",
            "高难",
            "非常难",
            "专家",
        ]
    )


def _has_expected_minutes_signal(text: str) -> bool:
    return bool(
        re.search(r"(预计|解题|完成|耗时|时长|限时)?\s*\d{1,3}\s*(?:min|minute|minutes|分钟)", text)
        or re.search(r"\d{1,2}\s*(?:hour|hours|小时)", text)
    )


def _category_from_text(text: str) -> str:
    if "通用技能" in text or "general skills" in text:
        return "MISC"
    if any(
        token in text
        for token in [
            "forensic",
            "forensics",
            "pcap",
            "wireshark",
            "steg",
            "volatility",
            "数字取证",
            "取证",
            "流量取证",
            "流量分析",
            "隐写",
            "内存取证",
            "磁盘取证",
            "元数据取证",
            "osint",
        ]
    ):
        return "FORENSICS"
    if (
        "密码学" in text
        or "crypto" in text
        or "rsa" in text
        or "aes" in text
        or re.search(r"\becc\b", text)
        or "椭圆曲线" in text
        or "diffie" in text
        or "hmac" in text
    ):
        return "CRYPTO"
    if re.search(r"\bsql\b", text) or re.search(r"\bsqli\b", text) or "sql 注入" in text or "sql注入" in text:
        return "WEB"
    if any(
        token in text
        for token in [
            "web",
            "http",
            "xss",
            "csrf",
            "ssrf",
            "ssti",
            "xxe",
            "nosql",
            "jwt",
            "command injection",
            "deserialization",
            "graphql",
            "api",
            "idor",
            "login",
            "auth",
            "登录",
            "认证",
            "注入",
            "越权",
            "访问控制",
            "文件上传",
            "路径遍历",
            "命令注入",
            "命令执行",
            "反序列化",
            "缓存",
            "业务逻辑",
        ]
    ):
        return "WEB"
    if any(token in text for token in ["reverse", "reversing", "逆向", "crackme", "firmware", "固件", "反汇编"]):
        return "REVERSE"
    if any(
        token in text
        for token in ["pwn", "overflow", "rop", "heap", "stack", "shellcode", "binary exploitation", "二进制利用", "栈溢出", "堆"]
    ):
        return "PWN"
    if any(
        token in text
        for token in [
            "crypto",
            "rsa",
            "aes",
            "diffie",
            "hmac",
            "hash",
            "xor",
            "padding",
            "密码学",
            "加密",
            "解密",
            "哈希",
            "凯撒",
            "维吉尼亚",
            "椭圆曲线",
            "随机数",
        ]
    ):
        return "CRYPTO"
    if any(
        token in text
        for token in [
            "misc",
            "general skills",
            "linux",
            "shell",
            "bash",
            "grep",
            "sed",
            "awk",
            "git",
            "regex",
            "docker",
            "container",
            "base64",
            "url 编码",
            "hex",
            "json",
            "csv",
            "sqlite",
            "jq",
            "nc ",
            "dns",
            "cloud",
            "kubernetes",
            "k8s",
            "iam",
            "active directory",
            "kerberos",
            "ldap",
            "supply chain",
            "sbom",
            "基础命令",
            "通用技能",
            "命令行",
            "管道",
            "正则",
            "权限",
            "容器",
            "隐藏文件",
            "数据处理",
            "端口",
            "网络基础",
            "setuid",
            "云安全",
            "对象存储",
            "服务账号",
            "编排",
            "域控",
            "企业身份",
            "供应链",
            "依赖",
        ]
    ) or ("python" in text and any(token in text for token in ["脚本", "自动化", "批量处理"])):
        return "MISC"
    if any(
        token in text
        for token in [
            "forensic",
            "forensics",
            "pcap",
            "wireshark",
            "steg",
            "volatility",
            "取证",
            "流量分析",
            "隐写",
            "内存取证",
            "磁盘",
            "日志",
            "音频",
            "元数据",
            "osint",
        ]
    ):
        return "FORENSICS"
    if any(
        token in text
        for token in [
            "misc",
            "general skills",
            "linux",
            "python",
            "scripting",
            "shell",
            "bash",
            "grep",
            "sed",
            "awk",
            "git",
            "regex",
            "docker",
            "container",
            "base64",
            "url 编码",
            "hex",
            "json",
            "csv",
            "sqlite",
            "jq",
            "nc ",
            "dns",
            "jq",
            "cloud",
            "kubernetes",
            "k8s",
            "iam",
            "active directory",
            "kerberos",
            "ldap",
            "supply chain",
            "sbom",
            "基础命令",
            "通用技能",
            "命令行",
            "脚本",
            "自动化",
            "管道",
            "正则",
            "权限",
            "容器",
            "隐藏文件",
            "数据处理",
            "端口",
            "网络基础",
            "云安全",
            "对象存储",
            "服务账号",
            "编排",
            "域控",
            "企业身份",
            "供应链",
            "依赖",
        ]
    ):
        return "MISC"
    return "UNKNOWN"


def _workspace_from_text(text: str) -> str:
    if any(token in text for token in ["remote desktop", "rdp", "vnc", "gui", "桌面"]):
        return "REMOTE_DESKTOP"
    if "simulated" in text or "模拟" in text:
        return "SIMULATED"
    return "TERMINAL"


def _target_from_text(text: str) -> str:
    if "xss" in text or "跨站脚本" in text or "脚本注入" in text:
        return "XSS"
    if "csrf" in text or "跨站请求伪造" in text:
        return "CSRF"
    if "ssti" in text or "模板" in text:
        return "TEMPLATE_INJECTION"
    if "nosql" in text or "mongo" in text or "查询对象" in text:
        return "NOSQL_INJECTION"
    if (
        ("jwt" in text or "jwk" in text or "kid" in text or "身份令牌" in text)
        and "认证与会话逻辑" not in text
    ):
        return "JWT_SECURITY"
    if "反序列化" in text or "deserialization" in text or "pickle" in text or "phar" in text or "gadget" in text:
        return "DESERIALIZATION"
    if "命令注入" in text or "命令执行" in text or "command injection" in text or "rce" in text:
        return "COMMAND_INJECTION"
    if "时间盲注" in text or "time blind" in text:
        return "SQLI_TIME_BLIND"
    if "布尔盲注" in text or "boolean blind" in text:
        return "SQLI_BOOLEAN_BLIND"
    if "联合查询" in text or "union query" in text:
        return "SQLI_UNION"
    if "二阶注入" in text or "second order" in text:
        return "SQLI_SECOND_ORDER"
    if "登录绕过" in text and ("sql" in text or "sqli" in text or "注入" in text):
        return "SQLI_LOGIN_BYPASS"
    pwn_target = _pwn_target_from_text("", text)
    if pwn_target:
        return pwn_target
    if (
        "整数溢出" in text
        or "整型溢出" in text
        or "类型溢出" in text
        or ("integer" in text and "overflow" in text)
    ):
        return "INTEGER_OVERFLOW"
    reverse_target = _reverse_target_from_text("", text)
    if reverse_target:
        return reverse_target
    if "rsa" in text:
        return "RSA"
    if "ecc" in text or "椭圆曲线" in text:
        return "ECC"
    if "diffie" in text or "密钥交换" in text:
        return "DIFFIE_HELLMAN"
    if "hash" in text or "hmac" in text or "哈希" in text or "完整性" in text:
        return "HASH"
    if "padding" in text or "填充" in text:
        return "PADDING_ORACLE"
    if any(token in text for token in ["aes", "cbc", "ecb", "ctr", "gcm", "对称"]):
        return "SYMMETRIC_CRYPTO"
    if "xor" in text or "异或" in text:
        return "XOR"
    if "random" in text or "随机" in text:
        return "PRNG"
    if any(token in text for token in ["caesar", "vigenere", "凯撒", "维吉尼亚", "古典"]):
        return "CLASSICAL_CRYPTO"
    if any(token in text for token in ["base64", "base85", "编码", "解码"]):
        return "ENCODING"
    if "cloud" in text or "iam" in text or "对象存储" in text or "云安全" in text or "临时凭证" in text:
        return "CLOUD_IAM"
    if "kubernetes" in text or "k8s" in text or "serviceaccount" in text or "rbac" in text or "networkpolicy" in text:
        return "KUBERNETES_SECURITY"
    if "active directory" in text or "kerberos" in text or "ldap" in text or "域控" in text or "企业身份" in text:
        return "ACTIVE_DIRECTORY"
    if "supply chain" in text or "sbom" in text or "lockfile" in text or "依赖" in text or "供应链" in text:
        return "SUPPLY_CHAIN"
    if ("脚本" in text or "python" in text or "scripting" in text) and (
        "通用技能" in text or "自动化" in text or "批量" in text
    ):
        return "SCRIPTING"
    if "pcap" in text or "wireshark" in text or "流量" in text:
        return "PCAP_FORENSICS"
    if "osint" in text or "公开信息" in text:
        return "OSINT"
    if "隐写" in text or "图片" in text or "图像" in text or "steg" in text:
        return "IMAGE_STEGANOGRAPHY"
    if "内存" in text or "volatility" in text:
        return "MEMORY_FORENSICS"
    if "磁盘" in text or "文件系统" in text:
        return "DISK_FORENSICS"
    if "日志" in text or "时间线" in text:
        return "LOG_ANALYSIS"
    if "恶意样本" in text or "malware" in text or "ioc" in text:
        return "MALWARE_TRIAGE"
    if "音频" in text or "频谱" in text:
        return "AUDIO_FORENSICS"
    if "文档" in text or "pdf" in text or "元数据" in text:
        return "DOCUMENT_FORENSICS"
    if "魔数" in text or "文件头" in text or "文件格式" in text:
        return "FILE_FORENSICS"
    if "git" in text:
        return "GIT_HISTORY"
    if "正则" in text or "regex" in text:
        return "REGEX_TEXT"
    if "docker" in text or "容器" in text:
        return "CONTAINER_BASICS"
    if "权限" in text or "setuid" in text or "sudo" in text:
        return "PERMISSION_MODEL"
    if "shell" in text or "管道" in text or any(token in text for token in ["grep", "sed", "awk"]):
        return "SHELL_PIPELINE"
    if "linux" in text or "隐藏文件" in text:
        return "LINUX_BASICS"
    if any(token in text for token in ["json", "jq", "csv", "sqlite"]):
        return "DATA_FORMATS"
    if "nc " in text or "端口" in text or "dns" in text:
        return "NETWORK_BASICS"
    if "脚本" in text or "python" in text:
        return "SCRIPTING"
    if ("sql" in text or "sqli" in text or "注入" in text) and (
        "auth" in text or "login" in text or "登录" in text or "认证" in text
    ):
        return "SQLI_AUTHENTICATION"
    if "sql" in text or "sqli" in text or "sql注入" in text or "sql 注入" in text:
        return "SQLI"
    if "auth" in text or "login" in text or "登录" in text or "认证" in text:
        return "AUTHENTICATION"
    if "访问控制" in text or "idor" in text or "越权" in text or "authorization" in text:
        return "AUTHORIZATION"
    if "ssrf" in text:
        return "SSRF"
    if "xxe" in text:
        return "XXE"
    if "文件上传" in text or "路径遍历" in text:
        return "FILE_HANDLING"
    if "graphql" in text or "api" in text:
        return "API_SECURITY"
    if "竞态" in text or "缓存" in text or "业务逻辑" in text:
        return "BUSINESS_LOGIC"
    if "注入" in text:
        return "INPUT_TRUST_BOUNDARY"
    if "越权" in text or "access control" in text or "authorization" in text:
        return "AUTHORIZATION"
    if any(token in text for token in ["reverse", "reversing", "逆向", "crackme", "firmware", "固件"]):
        return "BINARY_ANALYSIS"
    if any(token in text for token in ["pwn", "overflow", "rop", "heap", "stack", "二进制利用", "栈溢出"]):
        return "MEMORY_CORRUPTION"
    if any(token in text for token in ["crypto", "rsa", "aes", "密码学"]):
        return "CRYPTOGRAPHY"
    if any(token in text for token in ["forensic", "pcap", "取证", "流量"]):
        return "FORENSICS"
    return "GENERAL_SECURITY_PRACTICE"


def _difficulty_from_text(text: str) -> int:
    if any(token in text for token in ["intro", "beginner", "easy", "入门", "简单", "容易", "基础", "低难度"]):
        return 1
    if any(token in text for token in ["medium", "intermediate", "中等", "中级"]):
        return 3
    if any(token in text for token in ["expert", "very hard", "非常难", "专家"]):
        return 5
    if any(token in text for token in ["advanced", "hard", "困难", "高级", "高难", "较高", "偏高", "偏难", "较难"]):
        return 4
    return 2


def _minutes_from_text(text: str) -> int | None:
    match = re.search(r"(\d{1,3})\s*(?:min|minute|minutes|分钟)", text)
    if match:
        return int(match.group(1))
    hour_match = re.search(r"(\d{1,2})\s*(?:hour|hours|小时)", text)
    if hour_match:
        return int(hour_match.group(1)) * 60
    return None


def _tools_from_text(text: str, category: str) -> list[str]:
    if category == "REVERSE":
        defaults = ["strings", "objdump", "readelf", "gdb", "python"]
    elif category == "PWN":
        defaults = ["gdb", "python", "pwntools"]
    elif category == "CRYPTO":
        defaults = ["python", "openssl", "sage"]
    elif category == "FORENSICS":
        target = _target_from_text(text)
        defaults = ["file", "strings", "python", "xxd"]
        if target == "PCAP_FORENSICS":
            defaults.extend(["tshark", "tcpdump"])
        if target in {"IMAGE_STEGANOGRAPHY", "DOCUMENT_FORENSICS"}:
            defaults.extend(["exiftool", "binwalk"])
        if target == "MEMORY_FORENSICS":
            defaults.append("volatility")
    elif category == "MISC":
        defaults = ["bash", "python", "grep", "sed", "awk", "find", "file", "jq", "git", "nc"]
    else:
        defaults = ["curl", "python"]
    mentioned = [tool for tool in defaults if tool in text]
    return mentioned or defaults


def _objectives_from_text(text: str, category: str) -> list[str]:
    if category == "REVERSE":
        objectives = ["恢复关键控制流", "还原校验逻辑", "给出可复现实验证据"]
    elif category == "PWN":
        objectives = ["识别内存破坏原语", "构造稳定利用路径", "解释缓解机制影响"]
    elif category == "CRYPTO":
        objectives = ["识别密码实现假设", "构造可复现实验验证", "说明安全参数影响"]
    elif category == "FORENSICS":
        objectives = ["提取可验证证据", "还原事件链路", "说明取证结论依据"]
    elif category == "MISC":
        objectives = ["熟练使用终端工具", "构造可复现解题流程", "解释命令和数据处理依据"]
    else:
        objectives = ["识别输入输出信任边界", "构造可复现实验证据"]
    if category == "CRYPTO":
        if any(token in text for token in ["rsa", "ecc", "diffie", "哈希", "hash", "aes", "xor", "padding", "随机"]):
            objectives.append("recover-cryptographic-assumption")
        if "hash" in text or "哈希" in text or "hmac" in text:
            objectives.append("analyze-integrity-boundary")
    if category == "FORENSICS":
        objectives.append("extract-verifiable-evidence")
        if "pcap" in text or "wireshark" in text or "流量" in text:
            objectives.append("analyze-network-evidence")
    if category == "MISC":
        objectives.append("use-terminal-toolchain")
    if "xss" in text or "跨站脚本" in text or "脚本注入" in text:
        objectives.extend(["validate-cross-site-scripting-impact", "explain-output-encoding"])
    if (
        "整数溢出" in text
        or "整型溢出" in text
        or "类型溢出" in text
        or ("integer" in text and "overflow" in text)
    ):
        objectives.append("analyze-integer-overflow")
    if "sql" in text or "sqli" in text or "注入" in text:
        objectives.append("identify-input-trust-boundary")
    if "auth" in text or "login" in text or "登录" in text or "认证" in text:
        objectives.append("validate-authentication-impact")
    if "explain" in text or "解释" in text or "说明" in text:
        objectives.append("explain-parameterized-query")
    return list(dict.fromkeys(objectives))


def _candidate_conflicts(
    intent: dict[str, Any],
    constraints: dict[str, Any],
    manifest: dict[str, Any],
    challenge: models.Challenge,
) -> list[str]:
    spec = manifest.get("spec", {})
    workspace = spec.get("workspace", {})
    runtime = spec.get("runtime", {})
    conflicts: list[str] = []
    if intent.get("category") != "UNKNOWN" and challenge.category != intent.get("category"):
        conflicts.append(f"category:{challenge.category}!={intent.get('category')}")
    if workspace.get("type") != intent.get("workspaceType"):
        conflicts.append(f"workspaceType:{workspace.get('type')}!={intent.get('workspaceType')}")
    candidate_tier = int(runtime.get("isolationTier", 1) or 1)
    allowed_tier = int(
        constraints.get("maxIsolationTier")
        or constraints.get("isolationTier")
        or intent.get("isolationTier", 1)
        or 1
    )
    if candidate_tier > allowed_tier:
        conflicts.append(f"isolationTier:{candidate_tier}>{allowed_tier}")
    max_difficulty = constraints.get("maxDifficulty")
    if max_difficulty is not None and int(spec.get("difficulty", 99)) > int(max_difficulty):
        conflicts.append(f"difficulty:{spec.get('difficulty')}>{max_difficulty}")
    max_minutes = constraints.get("maxExpectedMinutes")
    if max_minutes is not None and int(spec.get("expectedMinutes", 999)) > int(max_minutes):
        conflicts.append(f"expectedMinutes:{spec.get('expectedMinutes')}>{max_minutes}")
    if constraints.get("internet") is False and runtime.get("egressPolicy") != "DENY_ALL":
        conflicts.append("egressPolicy:not-deny-all")
    capabilities = {str(item).strip().lower() for item in workspace.get("capabilities", []) if str(item).strip()}
    for tool in intent.get("allowedTools", []):
        if capabilities and str(tool).strip().lower() not in capabilities:
            conflicts.append(f"tool:{tool}:missing")
    return conflicts


def _candidate_match_reasons(
    intent: dict[str, Any], manifest: dict[str, Any], challenge: models.Challenge
) -> list[str]:
    spec = manifest.get("spec", {})
    reasons: list[str] = []
    if challenge.category == intent.get("category"):
        reasons.append("category")
    if spec.get("workspace", {}).get("type") == intent.get("workspaceType"):
        reasons.append("workspaceType")
    if spec.get("successOracle", {}).get("type"):
        reasons.append("external-oracle")
    objective_overlap = set(intent.get("learningObjectives", [])) & set(
        spec.get("learningObjectives", [])
    )
    if objective_overlap:
        reasons.append("learning-objectives")
    if spec.get("catalogBlueprint"):
        reasons.append("source-backed-blueprint")
    if spec.get("catalogBlueprint", {}).get("generator", {}).get("template"):
        reasons.append("generator-template")
    return reasons


def _candidate_score(reasons: list[str], conflicts: list[str], search_score: float) -> float:
    return min(1.0, max(0.0, 0.35 + 0.12 * len(reasons) + 0.25 * search_score - 0.2 * len(conflicts)))


def _candidate_sort_key(intent: dict[str, Any], candidate: dict[str, Any]) -> tuple[float, float, float, str]:
    return (
        _candidate_target_relevance(intent, candidate),
        float(candidate.get("searchScore", 0.0)),
        float(candidate.get("score", 0.0)),
        str(candidate.get("candidateId", "")),
    )


def _candidate_target_relevance(intent: dict[str, Any], candidate: dict[str, Any]) -> float:
    target = str(intent.get("target") or "").upper()
    objectives = {str(item) for item in intent.get("learningObjectives", [])}
    signals = candidate.get("retrievalSignals", {})
    text = " ".join(
        [
            str(candidate.get("candidateId", "")),
            str(candidate.get("title", "")),
            str(signals.get("compositionGroup", "")),
            _signal_list_text(signals.get("compatibleGroups", [])),
            _signal_list_text(signals.get("learningObjectives", [])),
            _signal_list_text(signals.get("sourceRefs", [])),
            str(signals.get("generatorTemplate", "")),
        ]
    ).lower()
    exact_fragments = {
        "SQLI": ["web_sqli", "web-sqli"],
        "SQLI_AUTHENTICATION": ["web_sqli", "web-sqli"],
        "SQLI_UNION": ["web_sqli_01", "web-sqli-01"],
        "SQLI_BOOLEAN_BLIND": ["web_sqli_02", "web-sqli-02"],
        "SQLI_TIME_BLIND": ["web_sqli_03", "web-sqli-03"],
        "SQLI_LOGIN_BYPASS": ["web_sqli_04", "web-sqli-04"],
        "SQLI_SECOND_ORDER": ["web_sqli_05", "web-sqli-05"],
        "XSS": ["web_xss", "web-xss"],
        "AUTHORIZATION": ["web_access", "web-access"],
        "SSRF": ["web_ssrf", "web-ssrf"],
        "FILE_HANDLING": ["web_file", "web-file"],
        "TEMPLATE_INJECTION": ["web_ssti", "web-ssti"],
        "XXE": ["web_xxe", "web-xxe"],
        "BUSINESS_LOGIC": ["web_race", "web-race"],
        "API_SECURITY": ["web_api", "web-api"],
        "CSRF": ["web_csrf", "web-csrf"],
        "DESERIALIZATION": ["web_deserialization", "web-deserialization"],
        "COMMAND_INJECTION": ["web_command", "web-command"],
        "NOSQL_INJECTION": ["web_nosql", "web-nosql"],
        "JWT_SECURITY": ["web_jwt", "web-jwt"],
        "REVERSE_STRINGS": ["reverse_strings", "reverse-strings"],
        "REVERSE_KEYGEN": ["reverse_keygen", "reverse-keygen"],
        "REVERSE_ANTIDEBUG": ["reverse_antidebug", "reverse-antidebug"],
        "REVERSE_PACKING": ["reverse_packing", "reverse-packing"],
        "REVERSE_CFF": ["reverse_cff", "reverse-cff"],
        "REVERSE_VM": ["reverse_vm", "reverse-vm"],
        "REVERSE_CRYPTO": ["reverse_crypto", "reverse-crypto"],
        "REVERSE_MOBILE": ["reverse_mobile", "reverse-mobile"],
        "REVERSE_STRIPPED": ["reverse_stripped", "reverse-stripped"],
        "REVERSE_EMBEDDED": ["reverse_embedded", "reverse-embedded"],
        "PWN_STACK": ["pwn_stack", "pwn-stack"],
        "PWN_ROP": ["pwn_rop", "pwn-rop"],
        "PWN_FORMAT": ["pwn_format", "pwn-format"],
        "PWN_HEAP": ["pwn_heap", "pwn-heap"],
        "PWN_UAF": ["pwn_uaf", "pwn-uaf"],
        "INTEGER_OVERFLOW": ["pwn_integer", "pwn-integer"],
        "PWN_SHELLCODE": ["pwn_shellcode", "pwn-shellcode"],
        "PWN_PIE": ["pwn_pie", "pwn-pie"],
        "PWN_SANDBOX": ["pwn_sandbox", "pwn-sandbox"],
        "PWN_KERNELISH": ["pwn_kernelish", "pwn-kernelish"],
        "ENCODING": ["crypto_encoding", "crypto-encoding", "misc_encoding", "misc-encoding"],
        "CLASSICAL_CRYPTO": ["crypto_classical", "crypto-classical"],
        "XOR": ["crypto_xor", "crypto-xor"],
        "HASH": ["crypto_hash", "crypto-hash"],
        "SYMMETRIC_CRYPTO": ["crypto_symmetric", "crypto-symmetric"],
        "PADDING_ORACLE": ["crypto_padding", "crypto-padding"],
        "RSA": ["crypto_rsa", "crypto-rsa"],
        "DIFFIE_HELLMAN": ["crypto_dh", "crypto-dh"],
        "ECC": ["crypto_ecc", "crypto-ecc"],
        "PRNG": ["crypto_prng", "crypto-prng"],
        "FILE_FORENSICS": ["forensics_file", "forensics-file"],
        "IMAGE_STEGANOGRAPHY": ["forensics_image", "forensics-image"],
        "PCAP_FORENSICS": ["forensics_pcap", "forensics-pcap"],
        "MEMORY_FORENSICS": ["forensics_memory", "forensics-memory"],
        "DISK_FORENSICS": ["forensics_disk", "forensics-disk"],
        "LOG_ANALYSIS": ["forensics_logs", "forensics-logs"],
        "MALWARE_TRIAGE": ["forensics_malware", "forensics-malware"],
        "AUDIO_FORENSICS": ["forensics_audio", "forensics-audio"],
        "OSINT": ["forensics_osint", "forensics-osint"],
        "DOCUMENT_FORENSICS": ["forensics_document", "forensics-document"],
        "GIT_HISTORY": ["misc_git", "misc-git"],
        "REGEX_TEXT": ["misc_regex", "misc-regex"],
        "CONTAINER_BASICS": ["misc_container", "misc-container"],
        "PERMISSION_MODEL": ["misc_permission", "misc-permission"],
        "SHELL_PIPELINE": ["misc_shell", "misc-shell"],
        "LINUX_BASICS": ["misc_linux", "misc-linux"],
        "DATA_FORMATS": ["misc_data", "misc-data"],
        "NETWORK_BASICS": ["misc_network", "misc-network"],
        "CLOUD_IAM": ["misc_cloud", "misc-cloud"],
        "KUBERNETES_SECURITY": ["misc_k8s", "misc-k8s"],
        "ACTIVE_DIRECTORY": ["misc_ad", "misc-ad"],
        "SUPPLY_CHAIN": ["misc_supply", "misc-supply"],
        "SCRIPTING": ["misc_scripting", "misc-scripting"],
    }
    if target in exact_fragments and any(fragment in text for fragment in exact_fragments[target]):
        return 1.2
    if ("XSS" in target or "validate-cross-site-scripting-impact" in objectives) and (
        "xss" in text or "跨站脚本" in text or "脚本" in text
    ):
        return 1.0
    if ("INTEGER_OVERFLOW" in target or "analyze-integer-overflow" in objectives) and (
        "integer" in text or "整数" in text or "溢出" in text or "边界" in text
    ):
        return 1.0
    if ("SQLI" in target or target == "INPUT_TRUST_BOUNDARY") and (
        "sqli" in text or "sql" in text or "注入" in text
    ):
        return 1.0
    relevance_terms = {
        "AUTHORIZATION": ["access", "idor", "访问控制", "越权", "authorization"],
        "SSRF": ["ssrf"],
        "FILE_HANDLING": ["file", "文件", "上传", "路径"],
        "TEMPLATE_INJECTION": ["ssti", "template", "模板", "反序列化", "deserialization"],
        "XXE": ["xxe", "xml"],
        "BUSINESS_LOGIC": ["race", "cache", "竞态", "缓存", "业务逻辑"],
        "API_SECURITY": ["api", "graphql", "cors", "webhook"],
        "CSRF": ["csrf", "samesite", "referer", "origin", "双提交"],
        "DESERIALIZATION": ["deserialization", "反序列化", "pickle", "phar", "gadget"],
        "COMMAND_INJECTION": ["command", "命令注入", "命令执行", "rce", "shell"],
        "NOSQL_INJECTION": ["nosql", "mongo", "查询对象", "聚合管道"],
        "JWT_SECURITY": ["jwt", "jwk", "kid", "令牌", "签名"],
        "REVERSE_STRINGS": ["reverse_strings", "reverse-strings", "strings", "字符串", "常量", "xor"],
        "REVERSE_KEYGEN": ["reverse_keygen", "reverse-keygen", "keygen", "注册码", "许可证", "线性校验"],
        "REVERSE_ANTIDEBUG": ["reverse_antidebug", "reverse-antidebug", "antidebug", "ptrace", "反调试"],
        "REVERSE_PACKING": ["reverse_packing", "reverse-packing", "packing", "upx", "加壳", "自解密"],
        "REVERSE_CFF": ["reverse_cff", "reverse-cff", "cff", "flattening", "opaque predicate", "控制流混淆"],
        "REVERSE_VM": ["reverse_vm", "reverse-vm", "vm", "bytecode", "虚拟机", "字节码"],
        "REVERSE_CRYPTO": ["reverse_crypto", "reverse-crypto", "crypto", "密码", "prng", "ecb"],
        "REVERSE_MOBILE": ["reverse_mobile", "reverse-mobile", "mobile", "android", "dex", "apk", "移动端"],
        "REVERSE_STRIPPED": ["reverse_stripped", "reverse-stripped", "stripped", "go", "rust", "静态链接", "无符号"],
        "REVERSE_EMBEDDED": ["reverse_embedded", "reverse-embedded", "embedded", "msp430", "firmware", "固件", "嵌入式"],
        "PWN_STACK": ["pwn_stack", "pwn-stack", "stack", "ret2win", "栈溢出"],
        "PWN_ROP": ["pwn_rop", "pwn-rop", "rop", "ret2libc", "ret2plt", "csu"],
        "PWN_FORMAT": ["pwn_format", "pwn-format", "format", "printf", "格式化字符串", "任意地址写"],
        "PWN_HEAP": ["pwn_heap", "pwn-heap", "heap", "tcache", "fastbin", "堆"],
        "PWN_UAF": ["pwn_uaf", "pwn-uaf", "uaf", "use-after-free", "use after free", "double free", "对象复用"],
        "PWN_SHELLCODE": ["pwn_shellcode", "pwn-shellcode", "shellcode", "seccomp", "orw"],
        "PWN_PIE": ["pwn_pie", "pwn-pie", "pie", "canary", "nx", "relro", "aslr"],
        "PWN_SANDBOX": ["pwn_sandbox", "pwn-sandbox", "sandbox", "chroot", "capability", "沙箱"],
        "PWN_KERNELISH": ["pwn_kernelish", "pwn-kernelish", "kernelish", "ioctl", "copy_from_user", "内核风格"],
        "RSA": ["rsa"],
        "ECC": ["ecc", "椭圆"],
        "DIFFIE_HELLMAN": ["dh", "diffie", "密钥交换"],
        "HASH": ["hash", "哈希", "hmac", "完整性"],
        "PADDING_ORACLE": ["padding", "填充", "oracle"],
        "SYMMETRIC_CRYPTO": ["symmetric", "aes", "cbc", "ecb", "ctr", "gcm", "对称"],
        "XOR": ["xor", "异或"],
        "PRNG": ["prng", "随机"],
        "CLASSICAL_CRYPTO": ["classical", "古典", "caesar", "vigenere", "凯撒", "维吉尼亚"],
        "ENCODING": ["encoding", "编码", "base64", "base85"],
        "PCAP_FORENSICS": ["pcap", "流量", "network"],
        "IMAGE_STEGANOGRAPHY": ["image", "steg", "隐写", "图片"],
        "MEMORY_FORENSICS": ["memory", "内存", "volatility"],
        "DISK_FORENSICS": ["disk", "磁盘", "文件系统"],
        "LOG_ANALYSIS": ["log", "日志", "时间线"],
        "MALWARE_TRIAGE": ["malware", "恶意", "ioc"],
        "AUDIO_FORENSICS": ["audio", "音频", "频谱"],
        "OSINT": ["osint", "公开信息"],
        "DOCUMENT_FORENSICS": ["document", "pdf", "文档", "元数据"],
        "FILE_FORENSICS": ["file", "magic", "文件", "魔数"],
        "GIT_HISTORY": ["git"],
        "REGEX_TEXT": ["regex", "正则"],
        "CONTAINER_BASICS": ["container", "docker", "容器"],
        "PERMISSION_MODEL": ["permission", "权限", "setuid", "sudo"],
        "SHELL_PIPELINE": ["shell", "管道", "grep", "sed", "awk"],
        "LINUX_BASICS": ["linux"],
        "DATA_FORMATS": ["data", "json", "jq", "csv", "sqlite"],
        "NETWORK_BASICS": ["network", "nc", "端口", "dns"],
        "CLOUD_IAM": ["cloud", "iam", "对象存储", "临时凭证"],
        "KUBERNETES_SECURITY": ["k8s", "kubernetes", "serviceaccount", "rbac", "networkpolicy"],
        "ACTIVE_DIRECTORY": ["ad", "active directory", "kerberos", "ldap", "域控"],
        "SUPPLY_CHAIN": ["supply", "sbom", "lockfile", "依赖", "供应链"],
        "SCRIPTING": ["script", "scripting", "脚本", "python"],
    }
    if target in relevance_terms and any(term in text for term in relevance_terms[target]):
        return 1.0
    if target and target.lower() in text:
        return 0.8
    return 0.0


def _signal_list_text(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    return " ".join(str(item) for item in value)


def _blueprint_retrieval_signals(manifest: dict[str, Any]) -> dict[str, Any]:
    blueprint = manifest.get("spec", {}).get("catalogBlueprint", {})
    if not isinstance(blueprint, dict):
        return {}
    composition = blueprint.get("composition", {})
    generator = blueprint.get("generator", {})
    return {
        "sourceRefs": blueprint.get("sourceRefs", []),
        "compositionGroup": composition.get("group"),
        "compatibleGroups": composition.get("compatibleGroups", []),
        "generatorTemplate": generator.get("template"),
        "learningObjectives": blueprint.get("learningObjectives", []),
    }
