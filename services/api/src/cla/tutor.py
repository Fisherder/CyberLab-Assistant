from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from cla import models
from cla.events import append_event, latest_session_epoch
from cla.ids import new_id


DETECTOR_VERSION = "cla-rule-stuck-detector/0.1.0"
TUTOR_VERSION = "cla-static-hint-library/0.1.0"

HintLevel = Literal["L1", "L2", "L3"]

HINT_LIBRARY: dict[HintLevel, str] = {
    "L1": "目前几次尝试集中在同一个维度。除了字段值，请求里还有哪些属性会影响服务端解析和认证路径？",
    "L2": "优先比较请求方法、内容类型、Cookie、编码和响应长度，而不只比较用户名或密码字段值。",
    "L3": "保存一份基线请求，每次只改变一个维度，再比较状态码、响应长度和会话状态变化；记录哪一类变化真正改变了服务端行为。",
}

FORBIDDEN_HINT_TERMS = ["final payload", "dynamic secret", "teacher solution", "最终 payload", "动态 secret", "教师解法"]


@dataclass(frozen=True)
class StuckAssessmentResult:
    state: str
    score: float
    window_from: int
    window_to: int
    features: dict
    excluded_reasons: list[str]
    evidence_refs: list[str]


def assess_attempt(
    db: Session,
    attempt: models.Attempt,
    *,
    explicit_help: bool = False,
) -> StuckAssessmentResult:
    events = db.scalars(
        select(models.Event)
        .where(models.Event.attempt_id == attempt.id)
        .order_by(models.Event.occurred_at.desc(), models.Event.sequence.desc())
        .limit(12)
    ).all()
    ordered_events = list(reversed(events))
    if any(
        event.type == "oracle.observed" and event.payload_json.get("passed") is True
        for event in ordered_events
    ):
        return StuckAssessmentResult(
            state="NORMAL",
            score=0.0,
            window_from=0,
            window_to=0,
            features={
                "oracle_passed": 1,
                "reason": "objective milestone already reached",
            },
            excluded_reasons=["oracle_passed"],
            evidence_refs=[
                event.id
                for event in ordered_events
                if event.type == "oracle.observed" and event.payload_json.get("passed") is True
            ],
        )

    command_events = [
        event for event in ordered_events if event.type == "terminal.command.completed"
    ][-8:]
    active_actions = len(command_events)
    if active_actions == 0:
        score = 0.06 if explicit_help else 0.0
        return StuckAssessmentResult(
            state="NORMAL",
            score=score,
            window_from=0,
            window_to=0,
            features={
                "active_actions": 0,
                "explicit_help_signal": 1 if explicit_help else 0,
            },
            excluded_reasons=["insufficient_activity"],
            evidence_refs=[],
        )

    fingerprints = [_command_fingerprint(event) for event in command_events]
    class_names = [
        str(event.payload_json.get("command_class", "unknown")) for event in command_events
    ]
    repeated_command_ratio = _max_ratio(fingerprints)
    same_error_signature_ratio = _max_ratio(
        [_error_signature(event) for event in command_events if _is_error(event)]
    )
    no_milestone_progress = 0 if _has_milestone_progress(ordered_events) else 1
    output_stasis_under_activity = 1 if repeated_command_ratio >= 0.67 else 0
    exploration_novelty = len(set(class_names)) / max(active_actions, 1)
    legitimate_long_running_operation = 1 if _has_long_running_progress(ordered_events) else 0
    explicit_help_signal = 1 if explicit_help else 0
    score = _clamp(
        0.24 * repeated_command_ratio
        + 0.22 * same_error_signature_ratio
        + 0.18 * no_milestone_progress
        + 0.12 * output_stasis_under_activity
        + 0.06 * explicit_help_signal
        - 0.14 * legitimate_long_running_operation
        - 0.10 * exploration_novelty
    )
    evidence_refs = [event.id for event in command_events[-4:]]
    excluded_reasons = []
    if active_actions < 3:
        excluded_reasons.append("insufficient_activity")
    if legitimate_long_running_operation:
        excluded_reasons.append("legitimate_long_running_operation")
    if active_actions < 3 or legitimate_long_running_operation:
        state = "NORMAL"
    elif score >= 0.72:
        state = "CONFIRMED"
    elif score >= 0.58:
        state = "SUSPECTED"
    else:
        state = "NORMAL"
    return StuckAssessmentResult(
        state=state,
        score=round(score, 4),
        window_from=min(event.sequence for event in command_events),
        window_to=max(event.sequence for event in command_events),
        features={
            "active_actions": active_actions,
            "repeated_command_ratio": round(repeated_command_ratio, 4),
            "same_error_signature_ratio": round(same_error_signature_ratio, 4),
            "no_milestone_progress": no_milestone_progress,
            "output_stasis_under_activity": output_stasis_under_activity,
            "exploration_novelty": round(exploration_novelty, 4),
            "legitimate_long_running_operation": legitimate_long_running_operation,
            "explicit_help_signal": explicit_help_signal,
        },
        excluded_reasons=excluded_reasons,
        evidence_refs=evidence_refs,
    )


def persist_assessment(
    db: Session,
    attempt: models.Attempt,
    result: StuckAssessmentResult,
    *,
    decision: str,
) -> models.StuckAssessment:
    assessment = models.StuckAssessment(
        id=new_id("assessment"),
        attempt_id=attempt.id,
        window_from=result.window_from,
        window_to=result.window_to,
        score=result.score,
        state=result.state,
        features_json={
            "feature_contributions": result.features,
            "excluded_reasons": result.excluded_reasons,
            "evidence_refs": result.evidence_refs,
        },
        detector_version=DETECTOR_VERSION,
        decision=decision,
    )
    db.add(assessment)
    return assessment


def latest_assessment(db: Session, attempt_id: str) -> models.StuckAssessment | None:
    return db.scalar(
        select(models.StuckAssessment)
        .where(models.StuckAssessment.attempt_id == attempt_id)
        .order_by(models.StuckAssessment.created_at.desc(), models.StuckAssessment.id.desc())
        .limit(1)
    )


def create_hint(
    db: Session,
    attempt: models.Attempt,
    *,
    level: HintLevel,
    trigger_type: str,
    assessment: models.StuckAssessment,
    evidence_refs: list[str],
) -> models.Hint:
    content = HINT_LIBRARY[level]
    if any(term.lower() in content.lower() for term in FORBIDDEN_HINT_TERMS):
        raise ValueError("hint content contains forbidden disclosure")
    hint = models.Hint(
        id=new_id("hint"),
        attempt_id=attempt.id,
        level=level,
        trigger_type=trigger_type,
        content=content,
        evidence_refs=[assessment.id, *evidence_refs],
        tutor_version=TUTOR_VERSION,
        shown_at=datetime.now(timezone.utc),
        status="SHOWN",
    )
    db.add(hint)
    append_event(
        db,
        tenant_id=attempt.tenant_id,
        attempt_id=attempt.id,
        session_epoch=latest_session_epoch(db, attempt.id),
        source="cla-tutor",
        event_type="hint.shown",
        payload={
            "hint_id": hint.id,
            "level": level,
            "trigger_type": trigger_type,
            "assessment_id": assessment.id,
            "tutor_version": TUTOR_VERSION,
        },
    )
    return hint


def latest_hint(db: Session, attempt_id: str) -> models.Hint | None:
    return db.scalar(
        select(models.Hint)
        .where(models.Hint.attempt_id == attempt_id)
        .order_by(models.Hint.shown_at.desc(), models.Hint.id.desc())
        .limit(1)
    )


def auto_hints_disabled(db: Session, attempt_id: str) -> bool:
    return (
        db.scalar(
            select(models.Hint.id)
            .where(models.Hint.attempt_id == attempt_id, models.Hint.status == "AUTO_DISABLED")
            .limit(1)
        )
        is not None
    )


def cooldown_active(hint: models.Hint | None) -> bool:
    return hint is not None and hint.status in {"SHOWN", "LATER", "ACCEPTED"}


def _command_fingerprint(event: models.Event) -> str:
    payload = event.payload_json
    return str(
        payload.get("command_fingerprint")
        or payload.get("command_redacted")
        or payload.get("command_class")
        or event.id
    )


def _error_signature(event: models.Event) -> str:
    payload = event.payload_json
    return str(
        payload.get("error_fingerprint")
        or f"{payload.get('command_class', 'unknown')}:{payload.get('exit_code', 'unknown')}"
    )


def _is_error(event: models.Event) -> bool:
    exit_code = event.payload_json.get("exit_code")
    return isinstance(exit_code, int) and exit_code != 0


def _has_milestone_progress(events: list[models.Event]) -> bool:
    return any(event.type in {"milestone.reached", "oracle.observed"} for event in events)


def _has_long_running_progress(events: list[models.Event]) -> bool:
    return any(
        event.type == "terminal.process.progress"
        or event.payload_json.get("long_running_progress") is True
        for event in events
    )


def _max_ratio(values: list[str]) -> float:
    if not values:
        return 0.0
    counts = {value: values.count(value) for value in set(values)}
    return max(counts.values()) / len(values)


def _clamp(value: float) -> float:
    return min(max(value, 0.0), 1.0)
