from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from cla.main import create_app
from cla.database import Base
from cla import models  # noqa: F401
from cla.settings import Settings


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_ROOT = ROOT / "packages/contracts/json-schema"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def validator(schema_name: str) -> Draft202012Validator:
    schemas = {path.name: load_json(path) for path in SCHEMA_ROOT.glob("*.schema.json")}
    schema = schemas[schema_name]
    registry = Registry().with_resources(
        (doc["$id"], Resource.from_contents(doc, default_specification=DRAFT202012))
        for doc in schemas.values()
    )
    return Draft202012Validator(schema, registry=registry)


def test_challenge_manifest_validates_against_schema() -> None:
    manifest = load_yaml(ROOT / "content/challenges/web-sqli-auth/manifest.yaml")
    validator("challenge.schema.json").validate(manifest)


def test_rubric_validates_against_schema() -> None:
    rubric = load_yaml(ROOT / "content/challenges/web-sqli-auth/rubric.yaml")
    validator("rubric.schema.json").validate(rubric)
    assert sum(criterion["maxScore"] for criterion in rubric["criteria"]) == 100


def test_terminal_ticket_claims_validate_against_schema() -> None:
    now = int(datetime.now(timezone.utc).timestamp())
    claims = {
        "iss": "cla-api",
        "aud": "cla-terminal-gateway",
        "sub": "user_student",
        "tenant_id": "tenant_dev",
        "attempt_id": "a_123",
        "session_id": "ls_123",
        "session_epoch": 1,
        "route_ref": "route_123",
        "permissions": ["terminal.connect", "terminal.resize"],
        "nonce": "single-use-random-nonce",
        "iat": now,
        "exp": now + 60,
    }
    validator("terminal-ticket.schema.json").validate(claims)


def test_event_labsession_and_agentrun_schemas_validate_samples() -> None:
    validator("event.schema.json").validate(
        {
            "event_id": "evt_123",
            "schema_version": "event/1.2",
            "tenant_id": "tenant_dev",
            "course_id": "course_websec",
            "assignment_id": "asg_web_sqli_auth",
            "attempt_id": "a_123",
            "session_epoch": 1,
            "stream_id": "stream_terminal_123",
            "sequence": 1,
            "occurred_at": "2026-06-24T08:18:20Z",
            "type": "terminal.command.completed",
            "actor": {"kind": "student", "id": "user_student"},
            "source": {"service": "cla-shell-hook", "version": "0.1.0"},
            "trace_id": "trace-1",
            "payload": {"command_class": "http_request", "exit_code": 0},
            "privacy": {"classification": "COURSE_PROCESS", "contains_raw_text": False},
            "integrity": {"previous_hash": None, "hash": "sha256:abc"},
        }
    )
    validator("labsession.schema.json").validate(
        {
            "id": "ls_123",
            "attemptId": "a_123",
            "epoch": 1,
            "workspaceType": "TERMINAL",
            "runtimeTier": 1,
            "status": "READY",
            "routeRef": "route_123",
            "expiresAt": "2026-06-24T09:18:20Z",
            "workflowId": "session/a_123/1",
        }
    )
    validator("agent-run.schema.json").validate(
        {
            "id": "ar_123",
            "tenantId": "tenant_dev",
            "purpose": "TUTOR_HINT",
            "promptVersion": "hint/0.1.0",
            "modelPolicy": "disabled-local",
            "status": "REJECTED",
            "usage": {},
        }
    )


def normalize_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def test_openapi_paths_are_backed_by_fastapi_routes() -> None:
    spec = load_yaml(ROOT / "packages/contracts/openapi/cla-api.yaml")
    documented = {
        normalize_path(path if path.startswith("/internal/") else f"/api/v1{path}")
        for path in spec["paths"]
        if path not in {"/audit"}
    }
    app = create_app(
        Settings(
            database_url="sqlite+pysqlite:///:memory:",
            dev_oidc_secret="contract-oidc",
            terminal_ticket_secret="contract-terminal",
            oracle_shared_secret="contract-oracle",
        )
    )
    implemented = {normalize_path(route.path) for route in app.routes if hasattr(route, "methods")}
    missing = sorted(documented - implemented)
    assert missing == []


def test_invalid_workspace_type_fails_schema() -> None:
    with pytest.raises(Exception):
        validator("workspace-type.schema.json").validate("GUI")


def test_core_tables_exist_in_metadata_and_migration() -> None:
    required_tables = {
        "tenants",
        "users",
        "courses",
        "course_members",
        "challenges",
        "challenge_versions",
        "validation_runs",
        "challenge_drafts",
        "assignments",
        "attempts",
        "lab_sessions",
        "event_streams",
        "events",
        "transcript_segments",
        "hints",
        "stuck_assessments",
        "grade_revisions",
        "criterion_results",
        "appeals",
        "agent_runs",
        "audit_logs",
        "outbox_events",
    }
    metadata_tables = set(Base.metadata.tables)
    missing_metadata = sorted(required_tables - metadata_tables)
    assert missing_metadata == []

    migration = (ROOT / "services/api/alembic/versions/0001_core.py").read_text()
    missing_migration = sorted(
        table for table in required_tables if f'"{table}"' not in migration
    )
    assert missing_migration == []
