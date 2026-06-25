from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import binascii
from functools import lru_cache
import hashlib
import hmac
import json
import secrets
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import jwt
from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from cla import models
from cla.settings import Settings

PBKDF2_ITERATIONS = 210_000


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    user_id: str
    oidc_subject: str
    roles: frozenset[str]


def create_dev_token(
    settings: Settings,
    *,
    subject: str,
    tenant_id: str = "tenant_dev",
    roles: list[str] | None = None,
    expires_minutes: int = 60,
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "iss": settings.dev_oidc_issuer,
            "aud": settings.dev_oidc_audience,
            "sub": subject,
            "tenant_id": tenant_id,
            "roles": roles or [],
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=expires_minutes)).timestamp()),
        },
        settings.dev_oidc_secret,
        algorithm="HS256",
    )


def create_local_auth_token(
    settings: Settings,
    *,
    subject: str,
    tenant_id: str,
    roles: list[str],
) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.local_auth_token_minutes)
    token = jwt.encode(
        {
            "iss": settings.local_auth_issuer,
            "aud": settings.local_auth_audience,
            "sub": subject,
            "tenant_id": tenant_id,
            "roles": roles,
            "auth_provider": "local",
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        },
        settings.local_auth_secret,
        algorithm="HS256",
    )
    return token, expires_at


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return "$".join(
        [
            "pbkdf2_sha256",
            str(PBKDF2_ITERATIONS),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        algorithm, iterations_raw, salt_raw, digest_raw = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        salt = base64.b64decode(salt_raw.encode("ascii"))
        expected = base64.b64decode(digest_raw.encode("ascii"))
    except (binascii.Error, ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def authenticate_request(request: Request, db: Session, settings: Settings) -> Principal:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise api_error(status.HTTP_401_UNAUTHORIZED, "UNAUTHENTICATED", "Missing bearer token")
    token = header.removeprefix("Bearer ").strip()
    claims = _decode_bearer_token(token, settings)
    tenant_id = str(claims.get("tenant_id", ""))
    subject = str(claims.get("sub", ""))
    if not tenant_id or not subject:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "UNAUTHENTICATED", "Invalid token claims")
    user = db.scalar(
        select(models.User).where(
            models.User.tenant_id == tenant_id,
            models.User.oidc_subject == subject,
            models.User.status == "ACTIVE",
        )
    )
    if user is None:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "UNAUTHENTICATED", "Unknown user")
    return Principal(
        tenant_id=tenant_id,
        user_id=user.id,
        oidc_subject=subject,
        roles=frozenset(str(role) for role in claims.get("roles", [])),
    )


def _decode_bearer_token(token: str, settings: Settings) -> dict[str, Any]:
    issuer = _unverified_issuer(token)
    if settings.local_auth_enabled and issuer == settings.local_auth_issuer:
        return _decode_local_auth_token(token, settings)
    return _decode_oidc_token(token, settings)


def _unverified_issuer(token: str) -> str | None:
    try:
        claims = jwt.decode(
            token,
            options={"verify_signature": False, "verify_aud": False, "verify_exp": False},
        )
    except jwt.PyJWTError:
        return None
    return str(claims.get("iss", ""))


def _decode_local_auth_token(token: str, settings: Settings) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            settings.local_auth_secret,
            algorithms=["HS256"],
            issuer=settings.local_auth_issuer,
            audience=settings.local_auth_audience,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise api_error(
            status.HTTP_401_UNAUTHORIZED,
            "UNAUTHENTICATED",
            "Invalid local session",
        ) from exc


def _decode_oidc_token(token: str, settings: Settings) -> dict[str, Any]:
    if settings.dev_mode:
        return _decode_dev_oidc_token(token, settings)
    return _decode_jwks_oidc_token(token, settings)


def _decode_dev_oidc_token(token: str, settings: Settings) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            settings.dev_oidc_secret,
            algorithms=["HS256"],
            issuer=settings.dev_oidc_issuer,
            audience=settings.dev_oidc_audience,
        )
    except jwt.PyJWTError as exc:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "UNAUTHENTICATED", "Invalid token") from exc


def _decode_jwks_oidc_token(token: str, settings: Settings) -> dict[str, Any]:
    if settings.oidc_jwks_json:
        return _decode_with_inline_jwks(token, settings)
    jwks_url = settings.oidc_jwks_url
    if jwks_url is None and settings.oidc_discovery_url:
        jwks_url = _discover_oidc_jwks_url(settings.oidc_discovery_url, settings.oidc_issuer)
    if jwks_url:
        try:
            signing_key = jwt.PyJWKClient(jwks_url).get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=list(settings.oidc_algorithms),
                issuer=settings.oidc_issuer,
                audience=settings.oidc_audience,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise api_error(status.HTTP_401_UNAUTHORIZED, "UNAUTHENTICATED", "Invalid token") from exc
    raise api_error(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "OIDC_NOT_CONFIGURED",
        "OIDC JWKS is not configured",
    )


@lru_cache(maxsize=32)
def _discover_oidc_jwks_url(discovery_url: str, expected_issuer: str) -> str:
    try:
        with urlopen(discovery_url, timeout=5) as response:
            document = json.loads(response.read().decode("utf-8"))
    except (
        HTTPError,
        URLError,
        OSError,
        TimeoutError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise api_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "OIDC_DISCOVERY_FAILED",
            "OIDC discovery failed",
        ) from exc

    if not isinstance(document, dict):
        raise api_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "OIDC_DISCOVERY_INVALID",
            "OIDC discovery document is invalid",
        )
    if document.get("issuer") != expected_issuer or not isinstance(document.get("jwks_uri"), str):
        raise api_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "OIDC_DISCOVERY_INVALID",
            "OIDC discovery document is invalid",
        )
    return document["jwks_uri"]


def _decode_with_inline_jwks(token: str, settings: Settings) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(token)
        key_id = header.get("kid")
        jwks = json.loads(settings.oidc_jwks_json or "{}")
        keys = jwks.get("keys", [])
        key_data = next((key for key in keys if key.get("kid") == key_id), None)
        if key_data is None:
            raise jwt.InvalidTokenError("kid not found")
        key = jwt.PyJWK(key_data).key
        return jwt.decode(
            token,
            key,
            algorithms=list(settings.oidc_algorithms),
            issuer=settings.oidc_issuer,
            audience=settings.oidc_audience,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except (jwt.PyJWTError, json.JSONDecodeError) as exc:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "UNAUTHENTICATED", "Invalid token") from exc


def api_error(status_code: int, code: str, message: str, details: dict | None = None) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "details": details or {}, "traceId": None},
    )


def require_course_role(
    db: Session, principal: Principal, course_id: str, allowed_roles: set[str]
) -> models.CourseMember:
    member = db.get(models.CourseMember, {"course_id": course_id, "user_id": principal.user_id})
    if member is None or member.role not in allowed_roles:
        raise api_error(403, "FORBIDDEN_SCOPE", "User is not allowed for this course")
    return member


def require_attempt_owner_or_teacher(db: Session, principal: Principal, attempt: models.Attempt) -> None:
    assignment = db.get(models.Assignment, attempt.assignment_id)
    if assignment is None:
        raise api_error(404, "NOT_FOUND", "Assignment not found")
    if attempt.tenant_id != principal.tenant_id:
        raise api_error(403, "FORBIDDEN_SCOPE", "Attempt belongs to another tenant")
    if attempt.student_id == principal.user_id:
        return
    require_course_role(db, principal, assignment.course_id, {"TEACHER", "TA"})


def require_attempt_owner(db: Session, principal: Principal, attempt: models.Attempt) -> None:
    if attempt.tenant_id != principal.tenant_id or attempt.student_id != principal.user_id:
        raise api_error(403, "FORBIDDEN_SCOPE", "Attempt belongs to another user")
