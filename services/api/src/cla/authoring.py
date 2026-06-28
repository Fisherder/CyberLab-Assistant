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
    text = brief.lower()
    uncertain_fields: list[str] = []

    category = str(constraints.get("category") or _category_from_text(text))
    if category == "UNKNOWN":
        uncertain_fields.append("category")

    workspace_type = str(constraints.get("workspaceType") or _workspace_from_text(text))
    if workspace_type not in {"TERMINAL", "REMOTE_DESKTOP", "SIMULATED"}:
        workspace_type = "TERMINAL"
        uncertain_fields.append("workspaceType")

    target = str(constraints.get("target") or _target_from_text(text))
    difficulty = int(constraints.get("difficulty") or _difficulty_from_text(text))
    expected_minutes = int(constraints.get("expectedMinutes") or _minutes_from_text(text) or 75)
    isolation_tier = int(constraints.get("isolationTier") or 1)
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
    accepted.sort(key=lambda item: item["score"], reverse=True)
    rejected.sort(key=lambda item: item["score"], reverse=True)
    accepted = accepted[:10]
    rejected = rejected[:10]
    composition_plan = composition_plan_for_candidates(draft.intent_json, accepted, rejected)
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
        "agentMessage": (
            f"已按 CourseIntent 完成题库检索，选用{source_text} {top['title']}@{top['semver']}，"
            f"当前匹配度约 {percent}%。我已根据候选环境、学习目标和约束生成题面提案，"
            "标题、说明和完成要求不会直接复用教师原句。"
        ),
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
            "没有找到同时满足硬约束和教学目标的现有候选或组合。我将生成定制靶场代码包草稿，"
            "包括题目 manifest、学生说明、目标服务代码、工作区镜像、拓扑、Oracle 和 Rubric。"
            "生成结果仍需教师审核和验证报告确认后才能发布。"
        ),
        "matchExplanation": (
            f"已淘汰 {len(rejected)} 个不满足硬约束的候选；"
            "进入自定义代码包生成路径，Agent 只生成可审核资产，不直接部署或发布。"
        ),
        "requiresCustomGeneration": True,
        "generatedDraftUrl": f"/api/v1/challenge-drafts/{draft.id}/generate-custom-package",
        "generatedFiles": files,
    }


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


def _normalize_target(raw: str, text: str) -> str:
    value = raw.upper().replace("-", "_").replace(" ", "_")
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
    allow_scanners = bool(constraints.get("allowAutomaticScanners"))
    normalized: list[str] = []
    for value in values:
        tool = value.strip()
        if not tool:
            continue
        key = tool.lower()
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
    if category == "WEB" and (
        "SQLI" in target
        or "INPUT_TRUST_BOUNDARY" in target
        or "identify-input-trust-boundary" in objectives
    ):
        return "定制 SQL 注入认证绕过靶场" if custom else "SQL 注入登录认证绕过实践"
    if category == "WEB" and ("AUTH" in target or "validate-authentication-impact" in objectives):
        return "Web 登录认证边界实践"
    if category == "WEB":
        return "Web 输入信任边界实践"
    if category == "REVERSE":
        return "逆向校验逻辑分析实践"
    if category == "PWN":
        return "二进制内存破坏利用实践"
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
        return (
            f"面向 Web 登录接口的终端实践，学生需要验证输入处理缺陷造成的认证影响，"
            f"并说明安全修复方式，预计 {minutes} 分钟。"
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
            return (
                "本题将由 Agent 生成一套可审核的 Web 靶场代码包。代码包包含可浏览的目标页面、"
                "后端登录接口、SQLite 初始化数据、工作区 Dockerfile、拓扑配置、外部 Oracle 和 Rubric 草稿。"
                "学生进入题目后会获得独立终端和目标服务地址，先确认服务健康状态，再围绕登录请求建立正常失败基线，"
                "最后验证输入处理缺陷是否会影响认证结果。发布前教师需要检查生成代码、验证报告和评分标准。"
            )
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
        return (
            f"{candidate_text}学生进入题目后会获得独立终端和目标 Web 服务地址，"
            "先通过健康检查确认服务在线，再围绕登录接口的 username 与 password 参数建立正常失败基线。"
            "随后学生需要比较不同输入导致的状态码、响应体和认证状态差异，判断认证查询是否受到输入内容影响。"
            "题目重点是识别输入信任边界、解释认证绕过影响，并给出参数化查询或等价安全实现的修复方案。"
        )
    return (
        f"{candidate_text}学生进入题目后会获得独立终端工作区，根据题目资源完成观察、验证和记录。"
        "题目重点是复现可观测现象、说明根因链路，并给出可落地的修复或缓解建议。"
    )


def _proposal_requirements(intent: dict[str, Any], *, mode: str) -> str:
    category = str(intent.get("category") or "WEB").upper()
    if category == "WEB":
        prefix = "生成的靶场草稿发布后，学生需要" if mode == "GENERATE_CUSTOM" else "学生需要"
        return (
            f"{prefix}完成以下内容：\n"
            "1. 确认目标服务在线，并记录一次普通错误登录请求的状态码和响应体。\n"
            "2. 围绕登录参数构造最小验证请求，说明哪些响应差异能够证明认证边界被输入影响。\n"
            "3. 在提交中写清楚根因、验证过程、影响范围和修复建议。\n"
            "4. 修复建议必须覆盖参数化查询、输入边界控制或等价的安全认证实现。\n"
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
    if "SQLI" in target or "INPUT_TRUST_BOUNDARY" in target or "identify-input-trust-boundary" in objectives:
        raw.append("SQL注入")
        raw.append("输入信任边界")
    if "AUTH" in target or "validate-authentication-impact" in objectives:
        raw.append("认证")
    if selected:
        raw.append("题库改写")
    else:
        raw.append("Agent生成")
    raw.extend(["终端实践", "容器环境"])
    return _dedupe_tags(raw)


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
    return common + ["target/Dockerfile", "target/server.py"]


def _human_category(category: str) -> str:
    return {
        "WEB": "Web安全",
        "REVERSE": "逆向工程",
        "PWN": "Pwn",
        "CRYPTO": "密码学",
        "FORENSICS": "数字取证",
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


def _category_from_text(text: str) -> str:
    if any(
        token in text
        for token in [
            "web",
            "http",
            "sql",
            "sqli",
            "xss",
            "csrf",
            "login",
            "auth",
            "登录",
            "认证",
            "注入",
            "越权",
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
    if any(token in text for token in ["crypto", "rsa", "aes", "ecc", "密码学", "加密", "解密"]):
        return "CRYPTO"
    if any(token in text for token in ["forensic", "forensics", "pcap", "wireshark", "取证", "流量分析"]):
        return "FORENSICS"
    return "UNKNOWN"


def _workspace_from_text(text: str) -> str:
    if any(token in text for token in ["remote desktop", "rdp", "vnc", "gui", "桌面"]):
        return "REMOTE_DESKTOP"
    if "simulated" in text or "模拟" in text:
        return "SIMULATED"
    return "TERMINAL"


def _target_from_text(text: str) -> str:
    if ("sql" in text or "sqli" in text or "注入" in text) and (
        "auth" in text or "login" in text or "登录" in text or "认证" in text
    ):
        return "SQLI_AUTHENTICATION"
    if "sql" in text or "sqli" in text or "sql注入" in text or "sql 注入" in text:
        return "SQLI"
    if "auth" in text or "login" in text or "登录" in text or "认证" in text:
        return "AUTHENTICATION"
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
    if any(token in text for token in ["intro", "beginner", "easy", "入门"]):
        return 1
    if any(token in text for token in ["advanced", "hard", "困难"]):
        return 4
    return 2


def _minutes_from_text(text: str) -> int | None:
    match = re.search(r"(\d{1,3})\s*(?:min|minute|minutes|分钟)", text)
    return int(match.group(1)) if match else None


def _tools_from_text(text: str, category: str) -> list[str]:
    if category == "REVERSE":
        defaults = ["strings", "objdump", "readelf", "gdb", "python"]
    elif category == "PWN":
        defaults = ["gdb", "python", "pwntools"]
    elif category == "CRYPTO":
        defaults = ["python", "sage"]
    elif category == "FORENSICS":
        defaults = ["tshark", "python", "file", "strings"]
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
    else:
        objectives = ["validate-authentication-impact"]
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
    if int(runtime.get("isolationTier", 0)) != int(intent.get("isolationTier", 0)):
        conflicts.append(
            f"isolationTier:{runtime.get('isolationTier')}!={intent.get('isolationTier')}"
        )
    max_difficulty = constraints.get("maxDifficulty")
    if max_difficulty is not None and int(spec.get("difficulty", 99)) > int(max_difficulty):
        conflicts.append(f"difficulty:{spec.get('difficulty')}>{max_difficulty}")
    max_minutes = constraints.get("maxExpectedMinutes")
    if max_minutes is not None and int(spec.get("expectedMinutes", 999)) > int(max_minutes):
        conflicts.append(f"expectedMinutes:{spec.get('expectedMinutes')}>{max_minutes}")
    if constraints.get("internet") is False and runtime.get("egressPolicy") != "DENY_ALL":
        conflicts.append("egressPolicy:not-deny-all")
    capabilities = set(workspace.get("capabilities", []))
    for tool in intent.get("allowedTools", []):
        if tool not in capabilities:
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
