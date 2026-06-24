from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
from typing import Iterator

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from cla.main import create_app
from cla.settings import Settings


def test_production_oidc_rs256_token_authenticates_known_user(tmp_path) -> None:
    private_key, jwks_json = oidc_keypair("cla-test-key")
    settings = production_oidc_settings(tmp_path, jwks_json)
    client = TestClient(create_app(settings))

    token = sign_oidc_token(private_key, kid="cla-test-key", subject="student@example.edu")
    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tenantId"] == "tenant_dev"
    assert body["userId"] == "user_student"


def test_production_oidc_discovery_document_resolves_jwks_uri(tmp_path) -> None:
    private_key, jwks_json = oidc_keypair("cla-discovery-key")
    with oidc_discovery_server(jwks_json) as discovery_url:
        settings = production_oidc_settings(
            tmp_path,
            jwks_json=None,
            discovery_url=discovery_url,
        )
        client = TestClient(create_app(settings))

        token = sign_oidc_token(
            private_key,
            kid="cla-discovery-key",
            subject="student@example.edu",
        )
        response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200, response.text
    assert response.json()["userId"] == "user_student"


def test_production_oidc_discovery_rejects_issuer_mismatch(tmp_path) -> None:
    private_key, jwks_json = oidc_keypair("cla-discovery-key")
    with oidc_discovery_server(jwks_json, issuer="https://wrong-issuer.example.edu") as discovery_url:
        settings = production_oidc_settings(
            tmp_path,
            jwks_json=None,
            discovery_url=discovery_url,
        )
        client = TestClient(create_app(settings))

        token = sign_oidc_token(
            private_key,
            kid="cla-discovery-key",
            subject="student@example.edu",
        )
        response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "OIDC_DISCOVERY_INVALID"


def test_production_oidc_rejects_wrong_audience_expired_and_unknown_kid(tmp_path) -> None:
    private_key, jwks_json = oidc_keypair("cla-test-key")
    settings = production_oidc_settings(tmp_path, jwks_json)
    client = TestClient(create_app(settings))

    wrong_audience = sign_oidc_token(
        private_key,
        kid="cla-test-key",
        subject="student@example.edu",
        audience="another-api",
    )
    expired = sign_oidc_token(
        private_key,
        kid="cla-test-key",
        subject="student@example.edu",
        expires_delta=timedelta(seconds=-30),
    )
    unknown_kid = sign_oidc_token(private_key, kid="unknown", subject="student@example.edu")

    for token in [wrong_audience, expired, unknown_kid]:
        response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "UNAUTHENTICATED"


def test_production_oidc_rejects_missing_bearer_token(tmp_path) -> None:
    _, jwks_json = oidc_keypair("cla-test-key")
    client = TestClient(create_app(production_oidc_settings(tmp_path, jwks_json)))
    response = client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "UNAUTHENTICATED"


def oidc_keypair(kid: str) -> tuple[rsa.RSAPrivateKey, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk["kid"] = kid
    jwk["use"] = "sig"
    jwk["alg"] = "RS256"
    return private_key, json.dumps({"keys": [jwk]})


def production_oidc_settings(
    tmp_path,
    jwks_json: str | None,
    *,
    discovery_url: str | None = None,
) -> Settings:
    return Settings(
        database_url="sqlite+pysqlite:///:memory:",
        dev_mode=False,
        oidc_issuer="https://issuer.example.edu",
        oidc_audience="cla-api",
        oidc_discovery_url=discovery_url,
        oidc_jwks_json=jwks_json,
        terminal_ticket_secret="test-terminal-secret",
        oracle_shared_secret="test-oracle-secret",
        internal_service_token="test-internal",
        transcript_object_root=str(tmp_path / "transcripts"),
        transcript_encryption_key="test-transcript-key",
    )


@contextmanager
def oidc_discovery_server(
    jwks_json: str,
    *,
    issuer: str = "https://issuer.example.edu",
) -> Iterator[str]:
    jwks = json.loads(jwks_json)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            port = self.server.server_address[1]
            if self.path == "/.well-known/openid-configuration":
                self.send_json(
                    {
                        "issuer": issuer,
                        "jwks_uri": f"http://127.0.0.1:{port}/jwks.json",
                    }
                )
                return
            if self.path == "/jwks.json":
                self.send_json(jwks)
                return
            self.send_response(404)
            self.end_headers()

        def send_json(self, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/.well-known/openid-configuration"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def sign_oidc_token(
    private_key: rsa.RSAPrivateKey,
    *,
    kid: str,
    subject: str,
    audience: str = "cla-api",
    expires_delta: timedelta = timedelta(minutes=10),
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "iss": "https://issuer.example.edu",
            "aud": audience,
            "sub": subject,
            "tenant_id": "tenant_dev",
            "roles": ["student"],
            "iat": int(now.timestamp()),
            "exp": int((now + expires_delta).timestamp()),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )
