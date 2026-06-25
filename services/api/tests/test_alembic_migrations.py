from __future__ import annotations

import os
from pathlib import Path
import uuid

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from cla.database import init_db


ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "services/api"


CORE_TABLES = {
    "tenants",
    "users",
    "courses",
    "course_members",
    "challenges",
    "challenge_versions",
    "validation_runs",
    "challenge_artifacts",
    "challenge_drafts",
    "assignments",
    "attempts",
    "lab_sessions",
    "event_streams",
    "events",
    "transcript_segments",
    "hints",
    "stuck_assessments",
    "terminal_ticket_nonces",
    "grade_revisions",
    "criterion_results",
    "appeals",
    "agent_runs",
    "audit_logs",
    "outbox_events",
    "idempotency_records",
}


def alembic_config(database_url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def assert_core_schema(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert CORE_TABLES <= tables
        assert "alembic_version" in tables

        transcript_columns = {
            column["name"] for column in inspector.get_columns("transcript_segments")
        }
        assert {"object_ref", "sha256", "redaction_state"} <= transcript_columns
        assert not {"raw_text", "content", "plaintext"} & transcript_columns
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        assert {"password_hash", "created_at", "last_login_at"} <= user_columns
        appeal_columns = {column["name"] for column in inspector.get_columns("appeals")}
        assert {"grade_revision_id", "criterion_id", "reason", "status"} <= appeal_columns

        with engine.connect() as connection:
            version = connection.execute(
                text("select version_num from alembic_version")
            ).scalar_one()
        assert version == "0003_challenge_artifacts"
    finally:
        engine.dispose()


def test_alembic_upgrade_head_creates_versioned_core_schema(tmp_path: Path) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'cla-migration-smoke.db'}"

    command.upgrade(alembic_config(db_url), "head")

    assert_core_schema(db_url)


def test_init_db_reconciles_legacy_sqlite_appeals_schema(tmp_path: Path) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'cla-legacy-dev.db'}"
    engine = create_engine(db_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE appeals (
                        id VARCHAR(64) PRIMARY KEY,
                        grade_revision_id VARCHAR(64) NOT NULL,
                        student_id VARCHAR(64) NOT NULL,
                        reason TEXT NOT NULL,
                        status VARCHAR(32) NOT NULL,
                        resolution TEXT,
                        resolved_by VARCHAR(64),
                        created_at DATETIME
                    )
                    """
                )
            )

        init_db(engine)

        appeal_columns = {
            column["name"] for column in inspect(engine).get_columns("appeals")
        }
        assert "criterion_id" in appeal_columns

        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO appeals (
                        id, grade_revision_id, criterion_id, student_id, reason, status
                    ) VALUES (
                        'ap_test', 'gr_test', 'root-cause-explanation', 'u_student',
                        '请复核解释项。', 'OPEN'
                    )
                    """
                )
            )
    finally:
        engine.dispose()


def test_alembic_upgrade_head_on_postgresql_when_configured() -> None:
    admin_url = os.getenv("CLA_TEST_POSTGRES_URL")
    if not admin_url:
        pytest.skip("CLA_TEST_POSTGRES_URL is not configured")

    database = f"cla_migration_{uuid.uuid4().hex}"
    target_url = make_url(admin_url).set(database=database).render_as_string(
        hide_password=False
    )
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database}"'))

        command.upgrade(alembic_config(target_url), "head")

        assert_core_schema(target_url)
    finally:
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        admin_engine.dispose()
