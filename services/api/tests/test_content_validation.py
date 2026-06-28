from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import socket
import threading
import urllib.request

from sqlalchemy import func, select
from fastapi.testclient import TestClient

from cla import models
from cla.content_validation import validate_challenge, write_validation_report
from cla.seed import DEV_IDS

from test_terminal_vertical_slice import auth


ROOT = Path(__file__).resolve().parents[3]
CHALLENGE_DIR = ROOT / "content/challenges/web-sqli-auth"
CONTRACTS_DIR = ROOT / "packages/contracts/json-schema"
VALIDATION_REPORT = ROOT / "content/validation/web-sqli-auth-001-1.3.0.validation.json"


def test_content_validation_runner_generates_teacher_visible_report(tmp_path: Path) -> None:
    report = validate_challenge(CHALLENGE_DIR, CONTRACTS_DIR)

    assert report == json.loads(VALIDATION_REPORT.read_text(encoding="utf-8"))
    assert report["overallStatus"] == "PASS"
    assert report["summary"] == {"passed": 8, "warnings": 1, "blocked": 0}
    checks = {check["id"]: check for check in report["checks"]}
    assert checks["schema-lint"]["status"] == "PASS"
    assert checks["reference-solve"]["status"] == "PASS"
    assert checks["negative-controls"]["status"] == "PASS"
    assert checks["supply-chain-scan"]["status"] == "WARN"
    encoded = json.dumps(report, ensure_ascii=False)
    forbidden_terms = ["final payload", "dynamic secret", "teacher solution", "Authorization"]
    assert all(term.lower() not in encoded.lower() for term in forbidden_terms)

    output = tmp_path / "validation.json"
    write_validation_report(report, output)
    assert json.loads(output.read_text(encoding="utf-8")) == report


def test_web_target_root_serves_student_gui() -> None:
    module_path = CHALLENGE_DIR / "target/server.py"
    spec = importlib.util.spec_from_file_location("web_sqli_auth_target", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = module.ThreadingHTTPServer(("127.0.0.1", port), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
            body = response.read().decode("utf-8")
        assert response.status == 200
        assert "Web 登录认证调试页" in body
        assert "TARGET_BASE_URL" in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_content_validation_blocks_broken_oracle_package(tmp_path: Path) -> None:
    challenge_copy = tmp_path / "web-sqli-auth"
    shutil.copytree(CHALLENGE_DIR, challenge_copy)
    (challenge_copy / "oracle/validator.py").unlink()

    report = validate_challenge(challenge_copy, CONTRACTS_DIR)

    checks = {check["id"]: check for check in report["checks"]}
    assert report["overallStatus"] == "BLOCK"
    assert report["summary"]["blocked"] >= 1
    assert checks["schema-lint"]["status"] == "BLOCK"
    assert checks["reference-solve"]["status"] == "BLOCK"
    assert checks["negative-controls"]["status"] == "BLOCK"


def test_teacher_can_read_validation_report_without_forbidden_disclosures(
    client: TestClient,
    student_token: str,
    other_student_token: str,
    teacher_token: str,
) -> None:
    student_forbidden = client.get(
        f"/api/v1/challenge-versions/{DEV_IDS['challenge_version']}/validation",
        headers=auth(student_token),
    )
    assert student_forbidden.status_code == 403

    other_forbidden = client.get(
        f"/api/v1/challenge-versions/{DEV_IDS['challenge_version']}/validation",
        headers=auth(other_student_token),
    )
    assert other_forbidden.status_code == 403

    response = client.get(
        f"/api/v1/challenge-versions/{DEV_IDS['challenge_version']}/validation",
        headers=auth(teacher_token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["challengeVersionId"] == DEV_IDS["challenge_version"]
    assert body["validationRunId"] == DEV_IDS["validation_run"]
    assert body["overallStatus"] == "PASS"
    assert body["summary"] == {"passed": 8, "warnings": 1, "blocked": 0}
    check_ids = {check["id"] for check in body["checks"]}
    assert {
        "schema-lint",
        "reference-solve",
        "negative-controls",
        "resource-budget",
        "hint-leakage",
    }.issubset(check_ids)
    encoded = str(body)
    forbidden_terms = ["final payload", "dynamic secret", "teacher solution", "Authorization"]
    assert all(term.lower() not in encoded.lower() for term in forbidden_terms)

    with client.app.state.SessionLocal() as db:
        run = db.get(models.ValidationRun, DEV_IDS["validation_run"])
        assert run is not None
        assert run.report_ref == "content/validation/web-sqli-auth-001-1.3.0.validation.json"
        audit = db.scalar(
            select(models.AuditLog).where(
                models.AuditLog.action == "challenge.validation.read",
                models.AuditLog.resource_id == DEV_IDS["challenge_version"],
            )
        )
        assert audit is not None


def test_unknown_validation_report_returns_404(client: TestClient, teacher_token: str) -> None:
    response = client.get(
        "/api/v1/challenge-versions/not-a-version/validation",
        headers=auth(teacher_token),
    )
    assert response.status_code == 404


def test_teacher_approves_validated_version_and_publication_is_audited(
    client: TestClient,
    student_token: str,
    teacher_token: str,
) -> None:
    with client.app.state.SessionLocal() as db:
        version = db.get(models.ChallengeVersion, DEV_IDS["challenge_version"])
        assert version is not None
        version.status = "PENDING_APPROVAL"
        db.commit()

    student_response = client.post(
        f"/api/v1/challenge-versions/{DEV_IDS['challenge_version']}/approve",
        headers=auth(student_token),
    )
    assert student_response.status_code == 403

    response = client.post(
        f"/api/v1/challenge-versions/{DEV_IDS['challenge_version']}/approve",
        headers=auth(teacher_token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "challengeVersionId": DEV_IDS["challenge_version"],
        "challengeId": DEV_IDS["challenge"],
        "semver": "1.3.0",
        "status": "PUBLISHED",
        "artifactDigest": "sha256:dev-fixture-web-sqli-auth",
        "validationRunId": DEV_IDS["validation_run"],
        "validationStatus": "PASS",
        "overallStatus": "PASS",
        "published": True,
        "alreadyPublished": False,
    }

    idempotent_response = client.post(
        f"/api/v1/challenge-versions/{DEV_IDS['challenge_version']}/approve",
        headers=auth(teacher_token),
    )
    assert idempotent_response.status_code == 200, idempotent_response.text
    assert idempotent_response.json()["alreadyPublished"] is True

    with client.app.state.SessionLocal() as db:
        version = db.get(models.ChallengeVersion, DEV_IDS["challenge_version"])
        assert version is not None
        assert version.status == "PUBLISHED"
        publish_events = db.scalar(
            select(func.count(models.OutboxEvent.id)).where(
                models.OutboxEvent.aggregate_type == "challenge_version",
                models.OutboxEvent.aggregate_id == DEV_IDS["challenge_version"],
                models.OutboxEvent.event_type == "challenge.version.published",
            )
        )
        assert publish_events == 1
        audit = db.scalar(
            select(models.AuditLog)
            .where(
                models.AuditLog.action == "challenge.version.approve",
                models.AuditLog.resource_id == DEV_IDS["challenge_version"],
                models.AuditLog.before_ref == "PENDING_APPROVAL",
                models.AuditLog.after_ref == "PUBLISHED",
            )
            .limit(1)
        )
        assert audit is not None


def test_blocking_validation_status_prevents_approval(
    client: TestClient,
    teacher_token: str,
) -> None:
    with client.app.state.SessionLocal() as db:
        version = db.get(models.ChallengeVersion, DEV_IDS["challenge_version"])
        run = db.get(models.ValidationRun, DEV_IDS["validation_run"])
        assert version is not None
        assert run is not None
        version.status = "PENDING_APPROVAL"
        run.status = "BLOCK"
        db.commit()

    response = client.post(
        f"/api/v1/challenge-versions/{DEV_IDS['challenge_version']}/approve",
        headers=auth(teacher_token),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "VALIDATION_NOT_PASSING"

    with client.app.state.SessionLocal() as db:
        version = db.get(models.ChallengeVersion, DEV_IDS["challenge_version"])
        assert version is not None
        assert version.status == "PENDING_APPROVAL"
        publish_events = db.scalar(
            select(func.count(models.OutboxEvent.id)).where(
                models.OutboxEvent.event_type == "challenge.version.published"
            )
        )
        assert publish_events == 0
