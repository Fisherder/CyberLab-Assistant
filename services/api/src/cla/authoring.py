from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
import yaml

from cla import models
from cla.content_validation import DEFAULT_CHALLENGE_DIR, validate_challenge


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_VALIDATION_REPORT_REF = "content/validation/web-sqli-auth-001-1.3.0.validation.json"


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
    for version, challenge in rows:
        candidate = challenge_candidate_view(db, draft, version, challenge)
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
) -> dict:
    manifest = challenge_manifest(version, challenge)
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
        "score": round(_candidate_score(match_reasons, conflicts), 2),
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


def _candidate_score(reasons: list[str], conflicts: list[str]) -> float:
    return max(0.0, 0.4 + 0.15 * len(reasons) - 0.2 * len(conflicts))
