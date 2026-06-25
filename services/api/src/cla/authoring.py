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
    allowed_tools = [str(tool) for tool in constraints.get("allowedTools", _tools_from_text(text))]
    learning_objectives = constraints.get("learningObjectives") or _objectives_from_text(text)
    confidence = 0.93 if not uncertain_fields else 0.62
    return {
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
        intent = _coerce_course_intent(result.output, fallback)
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


def search_challenge_candidates(db: Session, draft: models.ChallengeDraft) -> dict[str, list[dict]]:
    accepted: list[dict] = []
    rejected: list[dict] = []
    rows = db.execute(
        select(models.ChallengeVersion, models.Challenge)
        .join(models.Challenge, models.Challenge.id == models.ChallengeVersion.challenge_id)
        .where(models.Challenge.tenant_id == draft.tenant_id)
        .where(models.ChallengeVersion.status.notin_(["ARCHIVED", "REVOKED"]))
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
    return {"candidates": accepted[:10], "rejectedCandidates": rejected[:10]}


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
    if any(token in text for token in ["web", "http", "sql", "sqli", "login", "auth", "登录"]):
        return "WEB"
    if any(token in text for token in ["pwn", "binary", "reverse"]):
        return "PWN"
    return "UNKNOWN"


def _workspace_from_text(text: str) -> str:
    if any(token in text for token in ["remote desktop", "rdp", "vnc", "gui", "桌面"]):
        return "REMOTE_DESKTOP"
    if "simulated" in text or "模拟" in text:
        return "SIMULATED"
    return "TERMINAL"


def _target_from_text(text: str) -> str:
    if "auth" in text or "login" in text or "登录" in text:
        return "AUTHENTICATION"
    if "sql" in text or "sqli" in text:
        return "INPUT_TRUST_BOUNDARY"
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


def _tools_from_text(text: str) -> list[str]:
    tools = [tool for tool in ["curl", "python"] if tool in text]
    return tools or ["curl"]


def _objectives_from_text(text: str) -> list[str]:
    objectives = ["validate-authentication-impact"]
    if "sql" in text or "sqli" in text:
        objectives.append("identify-input-trust-boundary")
    if "explain" in text or "解释" in text:
        objectives.append("explain-parameterized-query")
    return objectives


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
    return reasons


def _candidate_score(reasons: list[str], conflicts: list[str], search_score: float) -> float:
    return max(0.0, 0.35 + 0.12 * len(reasons) + 0.25 * search_score - 0.2 * len(conflicts))
