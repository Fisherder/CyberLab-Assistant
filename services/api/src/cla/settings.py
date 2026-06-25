from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
_DOTENV_LOADED = False


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./cla-dev.db"
    dev_mode: bool = True
    dev_oidc_issuer: str = "cla-dev-oidc"
    dev_oidc_audience: str = "cla-api"
    dev_oidc_secret: str = "change-me-dev-oidc"
    oidc_issuer: str = "https://oidc.example.edu"
    oidc_audience: str = "cla-api"
    oidc_discovery_url: str | None = None
    oidc_jwks_url: str | None = None
    oidc_jwks_json: str | None = None
    oidc_algorithms: tuple[str, ...] = ("RS256",)
    local_auth_enabled: bool = True
    local_auth_issuer: str = "cla-local-auth"
    local_auth_audience: str = "cla-web"
    local_auth_secret: str = "change-me-local-auth"
    local_auth_token_minutes: int = 720
    terminal_ticket_secret: str = "change-me-terminal-ticket"
    oracle_shared_secret: str = "change-me-oracle"
    internal_service_token: str = "change-me-internal"
    gateway_url: str = "ws://localhost:8081/ws/terminal"
    sessiond_endpoint: str = "127.0.0.1:7777"
    transcript_storage_backend: str = "local"
    transcript_object_root: str = "/tmp/cla-transcript-objects"
    transcript_s3_bucket: str = ""
    transcript_s3_prefix: str = "terminal-transcripts"
    transcript_s3_endpoint_url: str | None = None
    transcript_s3_region: str = "us-east-1"
    transcript_s3_force_path_style: bool = False
    transcript_encryption_key: str = "change-me-transcript-key"
    challenge_artifact_storage_backend: str = "local"
    challenge_artifact_object_root: str = "/tmp/cla-challenge-artifacts"
    challenge_artifact_s3_bucket: str = ""
    challenge_artifact_s3_prefix: str = "challenge-artifacts"
    challenge_artifact_s3_endpoint_url: str | None = None
    challenge_artifact_s3_region: str = "us-east-1"
    challenge_artifact_s3_force_path_style: bool = False
    agent_runtime_enabled: bool = False
    model_provider: str = "openai-compatible"
    model_base_url: str = ""
    model_name: str = ""
    model_api_key: str = ""
    model_timeout_seconds: int = 30
    model_max_tokens: int = 1200
    model_temperature: float = 0.0
    remote_desktop_enabled: bool = False
    simulated_workspace_enabled: bool = False


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    _load_dotenv_once()
    return Settings(
        database_url=os.getenv("CLA_DATABASE_URL", Settings.database_url),
        dev_mode=_bool(os.getenv("CLA_DEV_MODE"), Settings.dev_mode),
        dev_oidc_issuer=os.getenv("CLA_DEV_OIDC_ISSUER", Settings.dev_oidc_issuer),
        dev_oidc_audience=os.getenv("CLA_DEV_OIDC_AUDIENCE", Settings.dev_oidc_audience),
        dev_oidc_secret=os.getenv("CLA_DEV_OIDC_SECRET", Settings.dev_oidc_secret),
        oidc_issuer=os.getenv("CLA_OIDC_ISSUER", Settings.oidc_issuer),
        oidc_audience=os.getenv("CLA_OIDC_AUDIENCE", Settings.oidc_audience),
        oidc_discovery_url=os.getenv("CLA_OIDC_DISCOVERY_URL"),
        oidc_jwks_url=os.getenv("CLA_OIDC_JWKS_URL"),
        oidc_jwks_json=os.getenv("CLA_OIDC_JWKS_JSON"),
        oidc_algorithms=tuple(
            item.strip()
            for item in os.getenv("CLA_OIDC_ALGORITHMS", ",".join(Settings.oidc_algorithms)).split(",")
            if item.strip()
        ),
        local_auth_enabled=_bool(
            os.getenv("CLA_LOCAL_AUTH_ENABLED"), Settings.local_auth_enabled
        ),
        local_auth_issuer=os.getenv("CLA_LOCAL_AUTH_ISSUER", Settings.local_auth_issuer),
        local_auth_audience=os.getenv("CLA_LOCAL_AUTH_AUDIENCE", Settings.local_auth_audience),
        local_auth_secret=os.getenv("CLA_LOCAL_AUTH_SECRET", Settings.local_auth_secret),
        local_auth_token_minutes=int(
            os.getenv(
                "CLA_LOCAL_AUTH_TOKEN_MINUTES",
                str(Settings.local_auth_token_minutes),
            )
        ),
        terminal_ticket_secret=os.getenv(
            "CLA_TERMINAL_TICKET_SECRET", Settings.terminal_ticket_secret
        ),
        oracle_shared_secret=os.getenv("CLA_ORACLE_SHARED_SECRET", Settings.oracle_shared_secret),
        internal_service_token=os.getenv(
            "CLA_INTERNAL_SERVICE_TOKEN", Settings.internal_service_token
        ),
        gateway_url=os.getenv("CLA_GATEWAY_URL", Settings.gateway_url),
        sessiond_endpoint=os.getenv("CLA_SESSIOND_ENDPOINT", Settings.sessiond_endpoint),
        transcript_storage_backend=os.getenv(
            "CLA_TRANSCRIPT_STORAGE_BACKEND", Settings.transcript_storage_backend
        ).strip().lower(),
        transcript_object_root=os.getenv(
            "CLA_TRANSCRIPT_OBJECT_ROOT", Settings.transcript_object_root
        ),
        transcript_s3_bucket=os.getenv(
            "CLA_TRANSCRIPT_S3_BUCKET", Settings.transcript_s3_bucket
        ),
        transcript_s3_prefix=os.getenv(
            "CLA_TRANSCRIPT_S3_PREFIX", Settings.transcript_s3_prefix
        ),
        transcript_s3_endpoint_url=os.getenv("CLA_TRANSCRIPT_S3_ENDPOINT_URL"),
        transcript_s3_region=os.getenv(
            "CLA_TRANSCRIPT_S3_REGION", Settings.transcript_s3_region
        ),
        transcript_s3_force_path_style=_bool(
            os.getenv("CLA_TRANSCRIPT_S3_FORCE_PATH_STYLE"),
            Settings.transcript_s3_force_path_style,
        ),
        transcript_encryption_key=os.getenv(
            "CLA_TRANSCRIPT_ENCRYPTION_KEY", Settings.transcript_encryption_key
        ),
        challenge_artifact_storage_backend=os.getenv(
            "CLA_CHALLENGE_ARTIFACT_STORAGE_BACKEND",
            Settings.challenge_artifact_storage_backend,
        ).strip().lower(),
        challenge_artifact_object_root=os.getenv(
            "CLA_CHALLENGE_ARTIFACT_OBJECT_ROOT",
            Settings.challenge_artifact_object_root,
        ),
        challenge_artifact_s3_bucket=os.getenv(
            "CLA_CHALLENGE_ARTIFACT_S3_BUCKET",
            Settings.challenge_artifact_s3_bucket,
        ),
        challenge_artifact_s3_prefix=os.getenv(
            "CLA_CHALLENGE_ARTIFACT_S3_PREFIX",
            Settings.challenge_artifact_s3_prefix,
        ),
        challenge_artifact_s3_endpoint_url=os.getenv("CLA_CHALLENGE_ARTIFACT_S3_ENDPOINT_URL"),
        challenge_artifact_s3_region=os.getenv(
            "CLA_CHALLENGE_ARTIFACT_S3_REGION",
            Settings.challenge_artifact_s3_region,
        ),
        challenge_artifact_s3_force_path_style=_bool(
            os.getenv("CLA_CHALLENGE_ARTIFACT_S3_FORCE_PATH_STYLE"),
            Settings.challenge_artifact_s3_force_path_style,
        ),
        agent_runtime_enabled=_bool(
            os.getenv("CLA_AGENT_RUNTIME_ENABLED"), Settings.agent_runtime_enabled
        ),
        model_provider=os.getenv("CLA_MODEL_PROVIDER", Settings.model_provider),
        model_base_url=os.getenv("CLA_MODEL_BASE_URL", Settings.model_base_url),
        model_name=os.getenv("CLA_MODEL_NAME", Settings.model_name),
        model_api_key=os.getenv("CLA_MODEL_API_KEY", Settings.model_api_key),
        model_timeout_seconds=int(
            os.getenv("CLA_MODEL_TIMEOUT_SECONDS", str(Settings.model_timeout_seconds))
        ),
        model_max_tokens=int(os.getenv("CLA_MODEL_MAX_TOKENS", str(Settings.model_max_tokens))),
        model_temperature=float(
            os.getenv("CLA_MODEL_TEMPERATURE", str(Settings.model_temperature))
        ),
        remote_desktop_enabled=_bool(
            os.getenv("CLA_REMOTE_DESKTOP_ENABLED"), Settings.remote_desktop_enabled
        ),
        simulated_workspace_enabled=_bool(
            os.getenv("CLA_SIMULATED_WORKSPACE_ENABLED"), Settings.simulated_workspace_enabled
        ),
    )


def _load_dotenv_once() -> None:
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    dotenv_path = REPO_ROOT / ".env"
    if not dotenv_path.is_file():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = _dotenv_value(value.strip())


def _dotenv_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
