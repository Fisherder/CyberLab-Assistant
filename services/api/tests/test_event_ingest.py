from __future__ import annotations

import base64
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from cla import models
from cla.main import create_app
from cla.settings import Settings
from cla.transcripts import (
    TranscriptRestoreError,
    delete_transcript_object,
    load_transcript_object_for_test,
    object_path_from_ref,
    s3_object_from_ref,
    store_transcript_object,
    verify_transcript_object,
)

from test_terminal_vertical_slice import auth, create_attempt, ensure_session


class _FakeS3Body:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def read(self) -> bytes:
        return self.data


class _FakeS3NotFound(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict] = {}

    def put_object(self, **kwargs) -> None:
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = {
            "Body": kwargs["Body"],
            "Metadata": kwargs["Metadata"],
            "ContentType": kwargs["ContentType"],
        }

    def get_object(self, **kwargs) -> dict:
        key = (kwargs["Bucket"], kwargs["Key"])
        if key not in self.objects:
            raise _FakeS3NotFound()
        return {"Body": _FakeS3Body(self.objects[key]["Body"])}

    def delete_object(self, **kwargs) -> None:
        key = (kwargs["Bucket"], kwargs["Key"])
        if key not in self.objects:
            raise _FakeS3NotFound()
        del self.objects[key]


def test_internal_event_ingest_appends_command_completed_and_updates_stream(
    client: TestClient, settings: Settings, student_token: str
) -> None:
    attempt = create_attempt(client, student_token, "event-ingest-attempt")
    ensure_session(client, student_token, attempt["attemptId"])

    unauthorized = client.post(
        f"/internal/attempts/{attempt['attemptId']}/events",
        json={
            "events": [
                {
                    "sessionEpoch": 1,
                    "source": "cla-shell-hook",
                    "type": "terminal.command.completed",
                    "payload": {"command_redacted": "curl [REDACTED]"},
                }
            ]
        },
    )
    assert unauthorized.status_code == 401

    response = client.post(
        f"/internal/attempts/{attempt['attemptId']}/events",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={
            "events": [
                {
                    "sessionEpoch": 1,
                    "source": "cla-shell-hook",
                    "type": "terminal.command.completed",
                    "traceId": "trace-command-1",
                    "payload": {
                        "command_id": "cmd_1",
                        "command_redacted": "curl -i http://target:8080/login -d '[REDACTED]'",
                        "command_fingerprint": "sha256:" + "a" * 64,
                        "command_class": "http_request",
                        "cwd": "/workspace",
                        "exit_code": 0,
                        "duration_ms": 184,
                        "output_segment_refs": ["seg_1"],
                        "redactions": ["request_body"],
                    },
                }
            ]
        },
    )
    assert response.status_code == 202, response.text
    event_id = response.json()["eventIds"][0]
    with client.app.state.SessionLocal() as db:
        event = db.get(models.Event, event_id)
        assert event is not None
        assert event.type == "terminal.command.completed"
        assert event.sequence == 0
        assert event.trace_id == "trace-command-1"
        assert event.payload_json["command_redacted"].endswith("'[REDACTED]'")
        assert "password" not in str(event.payload_json).lower()
        stream = db.scalar(
            select(models.EventStream).where(
                models.EventStream.attempt_id == attempt["attemptId"],
                models.EventStream.session_epoch == 1,
                models.EventStream.source == "cla-shell-hook",
            )
        )
        assert stream is not None
        assert stream.last_sequence == 0
        audit = db.scalar(
            select(models.AuditLog).where(
                models.AuditLog.action == "events.append_batch",
                models.AuditLog.resource_id == attempt["attemptId"],
                models.AuditLog.decision == "ALLOW",
            )
        )
        assert audit is not None


def test_transcript_segment_indexes_object_ref_without_raw_terminal_text(
    client: TestClient, settings: Settings, student_token: str
) -> None:
    attempt = create_attempt(client, student_token, "transcript-attempt")
    ensure_session(client, student_token, attempt["attemptId"])
    raw_secret = "password=dynamic-secret"

    response = client.post(
        f"/internal/attempts/{attempt['attemptId']}/transcript-segments",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={
            "sessionEpoch": 1,
            "direction": "OUTPUT",
            "seqFrom": 0,
            "seqTo": 3,
            "objectRef": "s3://tenant_dev/course_websec/attempt/transcript/seg-0001.zst.enc",
            "sha256": "sha256:" + "b" * 64,
            "redactionState": "ENCRYPTED",
        },
    )
    assert response.status_code == 202, response.text
    segment_id = response.json()["segmentId"]
    with client.app.state.SessionLocal() as db:
        segment = db.get(models.TranscriptSegment, segment_id)
        assert segment is not None
        assert segment.attempt_id == attempt["attemptId"]
        assert segment.seq_from == 0
        assert segment.seq_to == 3
        assert segment.redaction_state == "ENCRYPTED"
        assert raw_secret not in str(segment.__dict__)
        audit = db.scalar(
            select(models.AuditLog).where(
                models.AuditLog.action == "transcript.segment.index",
                models.AuditLog.resource_id == attempt["attemptId"],
                models.AuditLog.decision == "ALLOW",
            )
        )
        assert audit is not None

    bad_range = client.post(
        f"/internal/attempts/{attempt['attemptId']}/transcript-segments",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={
            "sessionEpoch": 1,
            "direction": "OUTPUT",
            "seqFrom": 10,
            "seqTo": 3,
            "objectRef": "s3://logical/seg",
            "sha256": "sha256:" + "c" * 64,
            "redactionState": "INDEX_ONLY",
        },
    )
    assert bad_range.status_code == 422
    assert bad_range.json()["detail"]["code"] == "INVALID_TRANSCRIPT_RANGE"

    extra_route_field = client.post(
        f"/internal/attempts/{attempt['attemptId']}/transcript-segments",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={
            "sessionEpoch": 1,
            "direction": "OUTPUT",
            "seqFrom": 0,
            "seqTo": 1,
            "objectRef": "s3://logical/seg",
            "sha256": "sha256:" + "e" * 64,
            "routeRef": "route_should_not_be_accepted_here",
        },
    )
    assert extra_route_field.status_code == 422


def test_student_cannot_call_internal_ingest(
    client: TestClient, student_token: str
) -> None:
    attempt = create_attempt(client, student_token, "student-ingest-attempt")
    ensure_session(client, student_token, attempt["attemptId"])
    response = client.post(
        f"/internal/attempts/{attempt['attemptId']}/transcript-segments",
        headers=auth(student_token),
        json={
            "sessionEpoch": 1,
            "direction": "OUTPUT",
            "seqFrom": 0,
            "seqTo": 1,
            "objectRef": "s3://logical/seg",
            "sha256": "sha256:" + "d" * 64,
            "redactionState": "INDEX_ONLY",
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "UNAUTHENTICATED"


def test_transcript_upload_encrypts_object_and_indexes_segment(
    client: TestClient, settings: Settings, student_token: str
) -> None:
    attempt = create_attempt(client, student_token, "transcript-upload-attempt")
    ensure_session(client, student_token, attempt["attemptId"])
    plaintext = b"curl output contains password=dynamic-secret and must stay out of DB"
    response = client.post(
        f"/internal/attempts/{attempt['attemptId']}/transcript-segments/upload",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={
            "sessionEpoch": 1,
            "direction": "OUTPUT",
            "seqFrom": 4,
            "seqTo": 7,
            "segmentBase64": base64.b64encode(plaintext).decode(),
        },
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["byteCount"] == len(plaintext)
    assert body["objectRef"].startswith("local://")
    assert body["objectSha256"].startswith("sha256:")
    assert body["plaintextSha256"].startswith("sha256:")

    object_path = object_path_from_ref(settings, body["objectRef"])
    assert object_path.exists()
    encrypted = object_path.read_bytes()
    assert plaintext not in encrypted
    assert b"dynamic-secret" not in encrypted
    assert (
        load_transcript_object_for_test(
            settings,
            object_ref=body["objectRef"],
            tenant_id="tenant_dev",
            attempt_id=attempt["attemptId"],
            epoch=1,
            direction="OUTPUT",
            seq_from=4,
            seq_to=7,
        )
        == plaintext
    )

    with client.app.state.SessionLocal() as db:
        segment = db.get(models.TranscriptSegment, body["segmentId"])
        assert segment is not None
        assert segment.object_ref == body["objectRef"]
        assert segment.sha256 == body["objectSha256"]
        assert segment.redaction_state == "ENCRYPTED"
        assert "dynamic-secret" not in str(segment.__dict__)
        audit = db.scalar(
            select(models.AuditLog).where(
                models.AuditLog.action == "transcript.segment.upload",
                models.AuditLog.resource_id == attempt["attemptId"],
                models.AuditLog.decision == "ALLOW",
            )
        )
        assert audit is not None

    restore = client.post(
        f"/internal/attempts/{attempt['attemptId']}/transcript-segments/verify-restore",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={"sessionEpoch": 1},
    )
    assert restore.status_code == 200, restore.text
    restore_body = restore.json()
    assert restore_body["attemptId"] == attempt["attemptId"]
    assert restore_body["checked"] == 1
    assert restore_body["passed"] == 1
    assert restore_body["failed"] == 0
    assert restore_body["restorable"] is True
    assert restore_body["results"][0]["status"] == "PASS"
    assert restore_body["results"][0]["code"] is None
    assert restore_body["results"][0]["byteCount"] == len(plaintext)
    assert "dynamic-secret" not in str(restore_body)
    assert "endpoint" not in str(restore_body)
    assert "routeRef" not in str(restore_body)

    with client.app.state.SessionLocal() as db:
        audit = db.scalar(
            select(models.AuditLog).where(
                models.AuditLog.action == "transcript.restore.verify",
                models.AuditLog.resource_id == attempt["attemptId"],
                models.AuditLog.decision == "ALLOW",
            )
        )
        assert audit is not None
        assert audit.after_ref == "checked=1 failed=0"

    object_path.write_bytes(b"corrupted transcript object")
    corrupt_restore = client.post(
        f"/internal/attempts/{attempt['attemptId']}/transcript-segments/verify-restore",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={"sessionEpoch": 1},
    )
    assert corrupt_restore.status_code == 200, corrupt_restore.text
    corrupt_body = corrupt_restore.json()
    assert corrupt_body["checked"] == 1
    assert corrupt_body["passed"] == 0
    assert corrupt_body["failed"] == 1
    assert corrupt_body["restorable"] is False
    assert corrupt_body["results"][0]["status"] == "FAIL"
    assert corrupt_body["results"][0]["code"] == "OBJECT_HASH_MISMATCH"
    assert "dynamic-secret" not in str(corrupt_body)

    bad_base64 = client.post(
        f"/internal/attempts/{attempt['attemptId']}/transcript-segments/upload",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={
            "sessionEpoch": 1,
            "direction": "OUTPUT",
            "seqFrom": 1,
            "seqTo": 2,
            "segmentBase64": "not-base64",
        },
    )
    assert bad_base64.status_code == 422
    assert bad_base64.json()["detail"]["code"] == "INVALID_TRANSCRIPT_SEGMENT"

    extra_endpoint_field = client.post(
        f"/internal/attempts/{attempt['attemptId']}/transcript-segments/upload",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={
            "sessionEpoch": 1,
            "direction": "OUTPUT",
            "seqFrom": 1,
            "seqTo": 2,
            "segmentBase64": base64.b64encode(b"ok").decode(),
            "endpoint": "sessiond:7777",
        },
    )
    assert extra_endpoint_field.status_code == 422


def test_transcript_object_ref_cannot_escape_object_root(settings: Settings) -> None:
    with pytest.raises(ValueError, match="escapes object root"):
        object_path_from_ref(settings, "local://../../outside.claenc")


def test_transcript_s3_backend_encrypts_verifies_and_deletes_objects(
    settings: Settings,
) -> None:
    s3_settings = Settings(
        database_url=settings.database_url,
        dev_mode=True,
        transcript_storage_backend="s3",
        transcript_s3_bucket="cla-transcript-raw",
        transcript_s3_prefix="raw/terminal",
        transcript_encryption_key="test-transcript-key",
    )
    fake_s3 = _FakeS3Client()
    plaintext = b"terminal bytes with password=dynamic-secret"

    stored = store_transcript_object(
        s3_settings,
        tenant_id="tenant_dev",
        attempt_id="att_s3_123",
        epoch=2,
        direction="OUTPUT",
        seq_from=8,
        seq_to=12,
        plaintext=plaintext,
        s3_client=fake_s3,
    )

    bucket, key = s3_object_from_ref(stored.object_ref)
    assert bucket == "cla-transcript-raw"
    assert key.startswith("raw/terminal/tenant_dev/att_s3_123/2/output/8-12-")
    encrypted = fake_s3.objects[(bucket, key)]["Body"]
    assert plaintext not in encrypted
    assert b"dynamic-secret" not in encrypted
    assert fake_s3.objects[(bucket, key)]["Metadata"]["cla-encryption"] == "aesgcm-client-side"

    restored = verify_transcript_object(
        s3_settings,
        object_ref=stored.object_ref,
        expected_object_sha256=stored.object_sha256,
        tenant_id="tenant_dev",
        attempt_id="att_s3_123",
        epoch=2,
        direction="OUTPUT",
        seq_from=8,
        seq_to=12,
        s3_client=fake_s3,
    )
    assert restored.byte_count == len(plaintext)

    with pytest.raises(TranscriptRestoreError) as wrong_bucket:
        verify_transcript_object(
            s3_settings,
            object_ref=stored.object_ref.replace("cla-transcript-raw", "other-bucket", 1),
            expected_object_sha256=stored.object_sha256,
            tenant_id="tenant_dev",
            attempt_id="att_s3_123",
            epoch=2,
            direction="OUTPUT",
            seq_from=8,
            seq_to=12,
            s3_client=fake_s3,
        )
    assert wrong_bucket.value.code == "UNSUPPORTED_OBJECT_REF"

    delete_status = delete_transcript_object(s3_settings, stored.object_ref, s3_client=fake_s3)
    assert delete_status == "DELETED"
    assert (bucket, key) not in fake_s3.objects

    with pytest.raises(TranscriptRestoreError) as exc:
        verify_transcript_object(
            s3_settings,
            object_ref=stored.object_ref,
            expected_object_sha256=stored.object_sha256,
            tenant_id="tenant_dev",
            attempt_id="att_s3_123",
            epoch=2,
            direction="OUTPUT",
            seq_from=8,
            seq_to=12,
            s3_client=fake_s3,
        )
    assert exc.value.code == "OBJECT_NOT_FOUND"


def test_transcript_s3_backend_upload_restore_and_retention_via_api(
    settings: Settings, student_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    s3_settings = replace(
        settings,
        transcript_storage_backend="s3",
        transcript_s3_bucket="cla-transcript-raw",
        transcript_s3_prefix="raw/terminal",
    )
    fake_s3 = _FakeS3Client()
    monkeypatch.setattr("cla.transcripts._default_s3_client", lambda _: fake_s3)
    with TestClient(create_app(s3_settings)) as s3_client:
        attempt = create_attempt(s3_client, student_token, "transcript-s3-api-attempt")
        ensure_session(s3_client, student_token, attempt["attemptId"])
        plaintext = b"api transcript bytes with password=dynamic-secret"

        response = s3_client.post(
            f"/internal/attempts/{attempt['attemptId']}/transcript-segments/upload",
            headers={"X-CLA-Service-Token": s3_settings.internal_service_token},
            json={
                "sessionEpoch": 1,
                "direction": "OUTPUT",
                "seqFrom": 40,
                "seqTo": 45,
                "segmentBase64": base64.b64encode(plaintext).decode(),
            },
        )
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["objectRef"].startswith(
            f"s3://cla-transcript-raw/raw/terminal/tenant_dev/{attempt['attemptId']}/1/output/"
        )
        bucket, key = s3_object_from_ref(body["objectRef"])
        encrypted = fake_s3.objects[(bucket, key)]["Body"]
        assert plaintext not in encrypted
        assert b"dynamic-secret" not in encrypted

        restore = s3_client.post(
            f"/internal/attempts/{attempt['attemptId']}/transcript-segments/verify-restore",
            headers={"X-CLA-Service-Token": s3_settings.internal_service_token},
            json={"sessionEpoch": 1},
        )
        assert restore.status_code == 200, restore.text
        restore_body = restore.json()
        assert restore_body["checked"] == 1
        assert restore_body["passed"] == 1
        assert restore_body["failed"] == 0
        assert restore_body["results"][0]["byteCount"] == len(plaintext)
        assert "dynamic-secret" not in str(restore_body)
        assert "endpoint" not in str(restore_body)
        assert "routeRef" not in str(restore_body)

        expired_at = datetime.now(timezone.utc) - timedelta(days=45)
        with s3_client.app.state.SessionLocal() as db:
            segment = db.get(models.TranscriptSegment, body["segmentId"])
            assert segment is not None
            assert segment.object_ref == body["objectRef"]
            segment.created_at = expired_at
            db.commit()

        applied = s3_client.post(
            "/internal/transcript-segments/apply-retention",
            headers={"X-CLA-Service-Token": s3_settings.internal_service_token},
            json={"dryRun": False},
        )
        assert applied.status_code == 200, applied.text
        applied_body = applied.json()
        assert applied_body["deleted"] == 1
        assert applied_body["failed"] == 0
        assert applied_body["results"][0]["objectRef"] == body["objectRef"]
        assert applied_body["results"][0]["code"] == "DELETED"
        assert "dynamic-secret" not in str(applied_body)
        assert (bucket, key) not in fake_s3.objects
        with s3_client.app.state.SessionLocal() as db:
            assert db.get(models.TranscriptSegment, body["segmentId"]) is None


def test_transcript_retention_dry_run_and_apply_delete_expired_local_objects(
    client: TestClient, settings: Settings, student_token: str
) -> None:
    attempt = create_attempt(client, student_token, "transcript-retention-attempt")
    ensure_session(client, student_token, attempt["attemptId"])
    plaintext = b"expired transcript bytes password=dynamic-secret"
    response = client.post(
        f"/internal/attempts/{attempt['attemptId']}/transcript-segments/upload",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={
            "sessionEpoch": 1,
            "direction": "OUTPUT",
            "seqFrom": 20,
            "seqTo": 27,
            "segmentBase64": base64.b64encode(plaintext).decode(),
        },
    )
    assert response.status_code == 202, response.text
    body = response.json()
    object_path = object_path_from_ref(settings, body["objectRef"])
    assert object_path.exists()

    expired_at = datetime.now(timezone.utc) - timedelta(days=45)
    with client.app.state.SessionLocal() as db:
        segment = db.get(models.TranscriptSegment, body["segmentId"])
        assert segment is not None
        segment.created_at = expired_at
        db.commit()

    dry_run = client.post(
        "/internal/transcript-segments/apply-retention",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={"dryRun": True},
    )
    assert dry_run.status_code == 200, dry_run.text
    dry_body = dry_run.json()
    assert dry_body["dryRun"] is True
    assert dry_body["cutoff"] is None
    assert dry_body["candidates"] == 1
    assert dry_body["deleted"] == 0
    assert dry_body["results"][0]["status"] == "CANDIDATE"
    assert dry_body["results"][0]["retentionDays"] == 30
    assert dry_body["results"][0]["policyRef"] == "policy/retention.yaml"
    assert "dynamic-secret" not in str(dry_body)
    assert object_path.exists()
    with client.app.state.SessionLocal() as db:
        assert db.get(models.TranscriptSegment, body["segmentId"]) is not None

    applied = client.post(
        "/internal/transcript-segments/apply-retention",
        headers={"X-CLA-Service-Token": settings.internal_service_token},
        json={"dryRun": False},
    )
    assert applied.status_code == 200, applied.text
    applied_body = applied.json()
    assert applied_body["dryRun"] is False
    assert applied_body["candidates"] == 1
    assert applied_body["deleted"] == 1
    assert applied_body["skipped"] == 0
    assert applied_body["failed"] == 0
    assert applied_body["results"][0]["status"] == "DELETED"
    assert applied_body["results"][0]["code"] == "DELETED"
    assert applied_body["results"][0]["retentionDays"] == 30
    assert applied_body["results"][0]["policyRef"] == "policy/retention.yaml"
    assert "dynamic-secret" not in str(applied_body)
    assert "endpoint" not in str(applied_body)
    assert "routeRef" not in str(applied_body)
    assert not object_path.exists()
    with client.app.state.SessionLocal() as db:
        assert db.get(models.TranscriptSegment, body["segmentId"]) is None
        audits = db.scalars(
            select(models.AuditLog).where(
                models.AuditLog.action == "transcript.retention.apply",
                models.AuditLog.decision == "ALLOW",
            )
        ).all()
        assert any("deleted=1" in (audit.after_ref or "") for audit in audits)
