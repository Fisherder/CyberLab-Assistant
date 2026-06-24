from __future__ import annotations

import hashlib
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cla import models
from cla.ids import new_id


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def append_event(
    db: Session,
    *,
    tenant_id: str,
    attempt_id: str,
    session_epoch: int,
    source: str,
    event_type: str,
    payload: dict,
) -> models.Event:
    stream = db.scalar(
        select(models.EventStream).where(
            models.EventStream.attempt_id == attempt_id,
            models.EventStream.session_epoch == session_epoch,
            models.EventStream.source == source,
        )
    )
    if stream is None:
        stream = models.EventStream(
            id=new_id("stream"),
            attempt_id=attempt_id,
            session_epoch=session_epoch,
            source=source,
            last_sequence=-1,
            status="ACTIVE",
        )
        db.add(stream)
    last = db.scalar(
        select(models.Event)
        .where(
            models.Event.attempt_id == attempt_id,
            models.Event.session_epoch == session_epoch,
            models.Event.source == source,
        )
        .order_by(models.Event.sequence.desc())
        .limit(1)
    )
    sequence = 0 if last is None else last.sequence + 1
    previous_hash = None if last is None else last.hash
    material = {
        "attempt_id": attempt_id,
        "session_epoch": session_epoch,
        "source": source,
        "sequence": sequence,
        "type": event_type,
        "payload": payload,
        "previous_hash": previous_hash,
    }
    event_hash = hashlib.sha256(_canonical(material)).hexdigest()
    event = models.Event(
        id=new_id("evt"),
        tenant_id=tenant_id,
        attempt_id=attempt_id,
        session_epoch=session_epoch,
        source=source,
        sequence=sequence,
        type=event_type,
        payload_json=payload,
        previous_hash=previous_hash,
        hash=event_hash,
    )
    stream.last_sequence = sequence
    db.add(event)
    db.flush()
    return event


def latest_session_epoch(db: Session, attempt_id: str) -> int:
    epoch = db.scalar(
        select(func.max(models.LabSession.epoch)).where(models.LabSession.attempt_id == attempt_id)
    )
    return int(epoch or 1)
