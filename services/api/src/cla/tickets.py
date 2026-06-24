from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets

import jwt
from sqlalchemy.orm import Session

from cla import models
from cla.settings import Settings


class TicketError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def issue_terminal_ticket(
    db: Session,
    settings: Settings,
    *,
    principal_user_id: str,
    tenant_id: str,
    attempt: models.Attempt,
    lab_session: models.LabSession,
) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=60)
    nonce = secrets.token_urlsafe(32)
    claims = {
        "iss": "cla-api",
        "aud": "cla-terminal-gateway",
        "sub": principal_user_id,
        "tenant_id": tenant_id,
        "attempt_id": attempt.id,
        "session_id": lab_session.id,
        "session_epoch": lab_session.epoch,
        "route_ref": lab_session.route_ref,
        "permissions": ["terminal.connect", "terminal.resize"],
        "nonce": nonce,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(claims, settings.terminal_ticket_secret, algorithm="HS256")
    db.add(
        models.TerminalTicketNonce(
            nonce=nonce,
            tenant_id=tenant_id,
            user_id=principal_user_id,
            attempt_id=attempt.id,
            session_id=lab_session.id,
            expires_at=expires_at,
        )
    )
    return token, expires_at


def consume_terminal_ticket(db: Session, settings: Settings, token: str) -> dict:
    try:
        claims = jwt.decode(
            token,
            settings.terminal_ticket_secret,
            algorithms=["HS256"],
            issuer="cla-api",
            audience="cla-terminal-gateway",
        )
    except jwt.ExpiredSignatureError as exc:
        raise TicketError("TERMINAL_TICKET_EXPIRED", "Terminal ticket expired") from exc
    except jwt.PyJWTError as exc:
        raise TicketError("TERMINAL_TICKET_EXPIRED", "Terminal ticket invalid") from exc

    nonce = db.get(models.TerminalTicketNonce, str(claims["nonce"]))
    now = datetime.now(timezone.utc)
    if nonce is None or nonce.status != "ISSUED":
        raise TicketError("TERMINAL_TICKET_EXPIRED", "Terminal ticket already consumed")
    expires_at = nonce.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        nonce.status = "EXPIRED"
        raise TicketError("TERMINAL_TICKET_EXPIRED", "Terminal ticket expired")
    if (
        nonce.tenant_id != claims["tenant_id"]
        or nonce.user_id != claims["sub"]
        or nonce.attempt_id != claims["attempt_id"]
        or nonce.session_id != claims["session_id"]
    ):
        raise TicketError("TERMINAL_TICKET_EXPIRED", "Terminal ticket binding mismatch")
    nonce.status = "CONSUMED"
    nonce.consumed_at = now
    return claims

