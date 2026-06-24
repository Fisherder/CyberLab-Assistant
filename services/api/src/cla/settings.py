from __future__ import annotations

from dataclasses import dataclass
import os


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
    agent_runtime_enabled: bool = False
    remote_desktop_enabled: bool = False
    simulated_workspace_enabled: bool = False


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
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
        agent_runtime_enabled=_bool(
            os.getenv("CLA_AGENT_RUNTIME_ENABLED"), Settings.agent_runtime_enabled
        ),
        remote_desktop_enabled=_bool(
            os.getenv("CLA_REMOTE_DESKTOP_ENABLED"), Settings.remote_desktop_enabled
        ),
        simulated_workspace_enabled=_bool(
            os.getenv("CLA_SIMULATED_WORKSPACE_ENABLED"), Settings.simulated_workspace_enabled
        ),
    )
