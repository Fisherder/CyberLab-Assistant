from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cla.main import create_app
from cla.security import create_dev_token
from cla.settings import Settings


@pytest.fixture()
def settings(tmp_path) -> Settings:
    return Settings(
        database_url="sqlite+pysqlite:///:memory:",
        dev_mode=True,
        dev_oidc_secret="test-oidc-secret",
        terminal_ticket_secret="test-terminal-secret",
        oracle_shared_secret="test-oracle-secret",
        internal_service_token="test-internal",
        gateway_url="ws://gateway.test/ws/terminal",
        transcript_object_root=str(tmp_path / "transcripts"),
        transcript_encryption_key="test-transcript-key",
        agent_runtime_enabled=False,
    )


@pytest.fixture()
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


@pytest.fixture()
def teacher_token(settings: Settings) -> str:
    return create_dev_token(settings, subject="teacher@example.edu", roles=["teacher"])


@pytest.fixture()
def student_token(settings: Settings) -> str:
    return create_dev_token(settings, subject="student@example.edu", roles=["student"])


@pytest.fixture()
def other_student_token(settings: Settings) -> str:
    return create_dev_token(settings, subject="other@example.edu", roles=["student"])


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
