from __future__ import annotations

import hmac
import hashlib
import json

from cla.settings import Settings


def canonical_json(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign_oracle_payload(settings: Settings, payload: dict) -> str:
    return hmac.new(
        settings.oracle_shared_secret.encode(), canonical_json(payload), hashlib.sha256
    ).hexdigest()


def verify_oracle_signature(settings: Settings, payload: dict, signature: str) -> bool:
    expected = sign_oracle_payload(settings, payload)
    return hmac.compare_digest(expected, signature)

