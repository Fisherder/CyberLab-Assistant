from __future__ import annotations

import json
from urllib.parse import quote
from urllib.request import urlopen
import urllib.error

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cla import models
from cla.events import append_event, latest_session_epoch
from cla.ids import new_id
from cla.settings import Settings


HINT_INDEPENDENCE_DEDUCTIONS = {"L1": 0.06, "L2": 0.12, "L3": 0.18}
COUNTED_HINT_STATUSES = {"SHOWN", "ACCEPTED", "LATER", "AUTO_DISABLED"}
MAX_INDEPENDENCE_DEDUCTION = 0.40
GRADER_VERSION = "cla-deterministic-grader/0.2.0"
ORACLE_VERSION = "web-sqli-auth-oracle/1.3.0"
ORACLE_PROBE_TIMEOUT_SECONDS = 5


def publish_grade_revision(db: Session, attempt: models.Attempt, answer_text: str) -> models.GradeRevision:
    latest_revision_no = db.scalar(
        select(func.max(models.GradeRevision.revision_no)).where(
            models.GradeRevision.attempt_id == attempt.id
        )
    )
    revision_no = int(latest_revision_no or 0) + 1
    oracle_event = db.scalar(
        select(models.Event)
        .where(models.Event.attempt_id == attempt.id, models.Event.type == "oracle.observed")
        .order_by(models.Event.occurred_at.desc())
        .limit(1)
    )
    oracle_passed = bool(oracle_event and oracle_event.payload_json.get("passed") is True)
    normalized = answer_text.lower()
    mentions_root_cause = any(
        word in normalized
        for word in ["parameter", "prepared", "参数化", "绑定参数", "输入信任", "信任边界"]
    )
    oracle_score = 60.0 if oracle_passed else 0.0
    explanation_score = 40.0 if mentions_root_cause else 15.0 if answer_text.strip() else 0.0
    total = oracle_score + explanation_score
    grade = models.GradeRevision(
        id=new_id("gr"),
        attempt_id=attempt.id,
        revision_no=revision_no,
        status="PUBLISHED",
        total_score=total,
        independence_index=calculate_independence_index(db, attempt.id),
        rubric_version="web-sqli-auth-001@1.3.0-rubric.1",
        grader_version=GRADER_VERSION,
    )
    grade.criteria = [
        models.CriterionResult(
            grade_revision_id=grade.id,
            criterion_id="oracle-auth-bypass",
            score=oracle_score,
            max_score=60.0,
            grader_type="DETERMINISTIC_ORACLE",
            confidence=1.0 if oracle_passed else 0.8,
            explanation=(
                "外部 Oracle 已观察到会话特定目标状态。"
                if oracle_passed
                else "未找到通过外部 Oracle 签名的成功证据。"
            ),
            evidence_refs=[oracle_event.id] if oracle_event else [],
        ),
        models.CriterionResult(
            grade_revision_id=grade.id,
            criterion_id="root-cause-explanation",
            score=explanation_score,
            max_score=40.0,
            grader_type="EVENT_PATTERN",
            confidence=0.72,
            explanation="解释中提到输入信任边界或参数化查询。" if mentions_root_cause else "解释较泛化。",
            evidence_refs=["submission.answer.root-cause"],
        ),
    ]
    db.add(grade)
    attempt.status = "GRADED"
    return grade


def request_oracle_check_for_attempt(
    db: Session, settings: Settings, attempt: models.Attempt
) -> models.Event | None:
    """在提交时触发声明式外部 Oracle 检查，生成可追溯的 S4 证据事件。"""
    if _latest_passing_oracle_event(db, attempt.id) is not None:
        return None
    if not _attempt_declares_external_http_oracle(attempt):
        return None
    return _append_oracle_probe_event(db, settings, attempt)


def calculate_independence_index(db: Session, attempt_id: str) -> float:
    hints = db.scalars(select(models.Hint).where(models.Hint.attempt_id == attempt_id)).all()
    deduction = sum(
        HINT_INDEPENDENCE_DEDUCTIONS.get(hint.level, 0.0)
        for hint in hints
        if hint.status in COUNTED_HINT_STATUSES
    )
    capped = min(deduction, MAX_INDEPENDENCE_DEDUCTION)
    return round(1.0 - capped, 4)


def _latest_passing_oracle_event(db: Session, attempt_id: str) -> models.Event | None:
    events = db.scalars(
        select(models.Event)
        .where(models.Event.attempt_id == attempt_id, models.Event.type == "oracle.observed")
        .order_by(models.Event.occurred_at.desc())
        .limit(20)
    ).all()
    return next(
        (event for event in events if event.payload_json.get("passed") is True),
        None,
    )


def _attempt_declares_external_http_oracle(attempt: models.Attempt) -> bool:
    assignment = attempt.assignment
    version = assignment.challenge_version if assignment else None
    if version is None:
        return False
    manifest = version.manifest_json or {}
    spec = manifest.get("spec")
    if not isinstance(spec, dict):
        spec = manifest
    oracle = spec.get("successOracle")
    if not isinstance(oracle, dict):
        return False
    return str(oracle.get("type") or "").upper() == "EXTERNAL_HTTP_PREDICATE"


def _append_oracle_probe_event(
    db: Session, settings: Settings, attempt: models.Attempt
) -> models.Event:
    passed, evidence = _probe_local_http_oracle(settings)
    return append_event(
        db,
        tenant_id=attempt.tenant_id,
        attempt_id=attempt.id,
        session_epoch=latest_session_epoch(db, attempt.id),
        source="cla-oracle",
        event_type="oracle.observed",
        payload={
            "oracle_version": ORACLE_VERSION,
            "passed": passed,
            "target_session_key": settings.local_target_session_key,
            "evidence": evidence,
            "trust": "S4",
            "requested_by": "attempt.submit",
        },
    )


def _probe_local_http_oracle(settings: Settings) -> tuple[bool, dict]:
    base_url = settings.local_target_base_url.rstrip("/")
    state_url = f"{base_url}/oracle/state?key={quote(settings.local_target_session_key)}"
    evidence: dict[str, object] = {
        "predicate": "auth_bypass_observed",
        "source": "external_http",
        "target": "local-dev",
    }
    try:
        with urlopen(state_url, timeout=ORACLE_PROBE_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode())
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
        evidence["error"] = type(exc).__name__
        return False, evidence
    passed = body.get("auth_bypass_observed") is True
    evidence["http_status"] = 200
    evidence["observed"] = passed
    return passed, evidence
