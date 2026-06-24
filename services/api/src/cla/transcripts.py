from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
from pathlib import Path
import secrets
from typing import Any, Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from cla.settings import Settings


class S3Client(Protocol):
    def put_object(self, **kwargs: Any) -> Any: ...

    def get_object(self, **kwargs: Any) -> dict[str, Any]: ...

    def delete_object(self, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class StoredTranscriptObject:
    object_ref: str
    object_sha256: str
    plaintext_sha256: str
    byte_count: int


@dataclass(frozen=True)
class RestoredTranscriptObject:
    object_ref: str
    object_sha256: str
    byte_count: int


class TranscriptRestoreError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TranscriptObjectDeleteError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TranscriptObjectStoreError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def store_transcript_object(
    settings: Settings,
    *,
    tenant_id: str,
    attempt_id: str,
    epoch: int,
    direction: str,
    seq_from: int,
    seq_to: int,
    plaintext: bytes,
    s3_client: S3Client | None = None,
) -> StoredTranscriptObject:
    nonce = secrets.token_bytes(12)
    key = _derive_key(settings.transcript_encryption_key)
    aad = f"{tenant_id}:{attempt_id}:{epoch}:{direction}:{seq_from}:{seq_to}".encode()
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
    plaintext_sha = hashlib.sha256(plaintext).hexdigest()
    material = nonce + ciphertext
    object_sha = hashlib.sha256(material).hexdigest()
    rel_path = _transcript_object_relative_path(
        tenant_id=tenant_id,
        attempt_id=attempt_id,
        epoch=epoch,
        direction=direction,
        seq_from=seq_from,
        seq_to=seq_to,
        object_sha=object_sha,
    )
    object_ref = _write_transcript_material(
        settings,
        rel_path=rel_path,
        material=material,
        plaintext_sha=plaintext_sha,
        object_sha=object_sha,
        s3_client=s3_client,
    )
    return StoredTranscriptObject(
        object_ref=object_ref,
        object_sha256=f"sha256:{object_sha}",
        plaintext_sha256=f"sha256:{plaintext_sha}",
        byte_count=len(plaintext),
    )


def verify_transcript_object(
    settings: Settings,
    *,
    object_ref: str,
    expected_object_sha256: str,
    tenant_id: str,
    attempt_id: str,
    epoch: int,
    direction: str,
    seq_from: int,
    seq_to: int,
    s3_client: S3Client | None = None,
) -> RestoredTranscriptObject:
    try:
        material = read_transcript_object_material(
            settings, object_ref=object_ref, s3_client=s3_client
        )
    except ValueError as exc:
        raise TranscriptRestoreError("UNSUPPORTED_OBJECT_REF", str(exc)) from exc
    except FileNotFoundError as exc:
        raise TranscriptRestoreError("OBJECT_NOT_FOUND", "transcript object not found") from exc
    except OSError as exc:
        raise TranscriptRestoreError("OBJECT_READ_FAILED", "transcript object read failed") from exc
    except Exception as exc:
        if _is_s3_missing_error(exc):
            raise TranscriptRestoreError("OBJECT_NOT_FOUND", "transcript object not found") from exc
        raise TranscriptRestoreError("OBJECT_READ_FAILED", "transcript object read failed") from exc

    if len(material) <= 12:
        raise TranscriptRestoreError("OBJECT_FORMAT_INVALID", "transcript object is too short")

    object_sha = f"sha256:{hashlib.sha256(material).hexdigest()}"
    if _normalize_sha256(expected_object_sha256) != object_sha:
        raise TranscriptRestoreError(
            "OBJECT_HASH_MISMATCH",
            "transcript object hash does not match the database index",
        )

    nonce, ciphertext = material[:12], material[12:]
    aad = f"{tenant_id}:{attempt_id}:{epoch}:{direction}:{seq_from}:{seq_to}".encode()
    try:
        plaintext = AESGCM(_derive_key(settings.transcript_encryption_key)).decrypt(
            nonce, ciphertext, aad
        )
    except Exception as exc:
        raise TranscriptRestoreError(
            "OBJECT_DECRYPT_FAILED",
            "transcript object could not be decrypted with indexed metadata",
        ) from exc

    return RestoredTranscriptObject(
        object_ref=object_ref,
        object_sha256=object_sha,
        byte_count=len(plaintext),
    )


def load_transcript_object_for_test(
    settings: Settings,
    *,
    object_ref: str,
    tenant_id: str,
    attempt_id: str,
    epoch: int,
    direction: str,
    seq_from: int,
    seq_to: int,
    s3_client: S3Client | None = None,
) -> bytes:
    material = read_transcript_object_material(settings, object_ref=object_ref, s3_client=s3_client)
    nonce, ciphertext = material[:12], material[12:]
    aad = f"{tenant_id}:{attempt_id}:{epoch}:{direction}:{seq_from}:{seq_to}".encode()
    return AESGCM(_derive_key(settings.transcript_encryption_key)).decrypt(nonce, ciphertext, aad)


def decode_segment_base64(value: str) -> bytes:
    return base64.b64decode(value.encode(), validate=True)


def object_path_from_ref(settings: Settings, object_ref: str) -> Path:
    if not object_ref.startswith("local://"):
        raise ValueError("unsupported transcript object ref")
    root = Path(settings.transcript_object_root).resolve()
    relative = Path(object_ref.removeprefix("local://"))
    candidate = (root / relative).resolve()
    if relative.is_absolute() or not candidate.is_relative_to(root):
        raise ValueError("transcript object ref escapes object root")
    return candidate


def s3_object_from_ref(object_ref: str) -> tuple[str, str]:
    if not object_ref.startswith("s3://"):
        raise ValueError("unsupported transcript object ref")
    without_scheme = object_ref.removeprefix("s3://")
    bucket, sep, key = without_scheme.partition("/")
    if not sep or not bucket or not key:
        raise ValueError("invalid s3 transcript object ref")
    if key.startswith("/") or _has_unsafe_path_component(key):
        raise ValueError("s3 transcript object ref contains unsafe path components")
    return bucket, key


def read_transcript_object_material(
    settings: Settings,
    *,
    object_ref: str,
    s3_client: S3Client | None = None,
) -> bytes:
    if object_ref.startswith("local://"):
        return object_path_from_ref(settings, object_ref).read_bytes()
    if object_ref.startswith("s3://"):
        bucket, key = s3_object_from_ref(object_ref)
        _validate_s3_object_ref(settings, bucket, key)
        client = s3_client or _default_s3_client(settings)
        response = client.get_object(Bucket=bucket, Key=key)
        body = response["Body"]
        if isinstance(body, bytes):
            return body
        return body.read()
    raise ValueError("unsupported transcript object ref")


def delete_transcript_object(
    settings: Settings, object_ref: str, s3_client: S3Client | None = None
) -> str:
    if object_ref.startswith("s3://"):
        try:
            bucket, key = s3_object_from_ref(object_ref)
            _validate_s3_object_ref(settings, bucket, key)
            client = s3_client or _default_s3_client(settings)
            client.delete_object(Bucket=bucket, Key=key)
            return "DELETED"
        except ValueError as exc:
            raise TranscriptObjectDeleteError("UNSUPPORTED_OBJECT_REF", str(exc)) from exc
        except Exception as exc:
            if _is_s3_missing_error(exc):
                return "MISSING"
            raise TranscriptObjectDeleteError("OBJECT_DELETE_FAILED", "object delete failed") from exc

    try:
        path = object_path_from_ref(settings, object_ref)
    except ValueError as exc:
        raise TranscriptObjectDeleteError("UNSUPPORTED_OBJECT_REF", str(exc)) from exc

    try:
        path.unlink()
    except FileNotFoundError:
        return "MISSING"
    except OSError as exc:
        raise TranscriptObjectDeleteError("OBJECT_DELETE_FAILED", str(exc)) from exc

    _remove_empty_parents(path.parent, Path(settings.transcript_object_root).resolve())
    return "DELETED"


def _write_transcript_material(
    settings: Settings,
    *,
    rel_path: Path,
    material: bytes,
    plaintext_sha: str,
    object_sha: str,
    s3_client: S3Client | None,
) -> str:
    backend = settings.transcript_storage_backend.strip().lower()
    if backend == "local":
        root = Path(settings.transcript_object_root)
        path = root / rel_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(material)
        except OSError as exc:
            raise TranscriptObjectStoreError(
                "OBJECT_STORE_WRITE_FAILED", "transcript object write failed"
            ) from exc
        return f"local://{rel_path.as_posix()}"
    if backend == "s3":
        if not settings.transcript_s3_bucket:
            raise TranscriptObjectStoreError(
                "OBJECT_STORE_NOT_CONFIGURED", "transcript S3 bucket is not configured"
            )
        key = _s3_key(settings.transcript_s3_prefix, rel_path)
        metadata = {
            "cla-object-sha256": object_sha,
            "cla-plaintext-sha256": plaintext_sha,
            "cla-encryption": "aesgcm-client-side",
        }
        try:
            client = s3_client or _default_s3_client(settings)
            client.put_object(
                Bucket=settings.transcript_s3_bucket,
                Key=key,
                Body=material,
                Metadata=metadata,
                ContentType="application/octet-stream",
            )
        except TranscriptObjectStoreError:
            raise
        except Exception as exc:
            raise TranscriptObjectStoreError(
                "OBJECT_STORE_WRITE_FAILED", "transcript object write failed"
            ) from exc
        return f"s3://{settings.transcript_s3_bucket}/{key}"
    raise TranscriptObjectStoreError(
        "OBJECT_STORE_NOT_CONFIGURED",
        f"unsupported transcript storage backend: {settings.transcript_storage_backend}",
    )


def _transcript_object_relative_path(
    *,
    tenant_id: str,
    attempt_id: str,
    epoch: int,
    direction: str,
    seq_from: int,
    seq_to: int,
    object_sha: str,
) -> Path:
    _require_safe_path_component(tenant_id, "tenant_id")
    _require_safe_path_component(attempt_id, "attempt_id")
    _require_safe_path_component(str(epoch), "epoch")
    _require_safe_path_component(direction.lower(), "direction")
    return (
        Path(tenant_id)
        / attempt_id
        / str(epoch)
        / direction.lower()
        / f"{seq_from}-{seq_to}-{object_sha[:16]}.claenc"
    )


def _s3_key(prefix: str, rel_path: Path) -> str:
    normalized_prefix = _normalize_s3_prefix(prefix)
    rel = rel_path.as_posix()
    if normalized_prefix:
        return f"{normalized_prefix}/{rel}"
    return rel


def _normalize_s3_prefix(prefix: str) -> str:
    stripped = prefix.strip("/")
    if not stripped:
        return ""
    if _has_unsafe_path_component(stripped):
        raise TranscriptObjectStoreError(
            "OBJECT_STORE_NOT_CONFIGURED", "transcript S3 prefix contains unsafe path components"
        )
    return stripped


def _validate_s3_object_ref(settings: Settings, bucket: str, key: str) -> None:
    if settings.transcript_s3_bucket and bucket != settings.transcript_s3_bucket:
        raise ValueError("s3 transcript object ref uses unconfigured bucket")
    normalized_prefix = _normalize_s3_prefix(settings.transcript_s3_prefix)
    if normalized_prefix and not key.startswith(f"{normalized_prefix}/"):
        raise ValueError("s3 transcript object ref escapes transcript prefix")


def _has_unsafe_path_component(value: str) -> bool:
    return any(part in {"", ".", ".."} for part in value.split("/"))


def _require_safe_path_component(value: str, name: str) -> None:
    if not value or "/" in value or "\\" in value or value in {".", ".."}:
        raise TranscriptObjectStoreError(
            "OBJECT_STORE_NOT_CONFIGURED", f"unsafe transcript object path component: {name}"
        )


def _default_s3_client(settings: Settings) -> S3Client:
    try:
        import boto3
    except ModuleNotFoundError as exc:
        raise TranscriptObjectStoreError(
            "OBJECT_STORE_NOT_CONFIGURED", "boto3 is required for transcript S3 storage"
        ) from exc

    kwargs: dict[str, Any] = {"region_name": settings.transcript_s3_region}
    if settings.transcript_s3_endpoint_url:
        kwargs["endpoint_url"] = settings.transcript_s3_endpoint_url
    if settings.transcript_s3_force_path_style:
        from botocore.config import Config

        kwargs["config"] = Config(s3={"addressing_style": "path"})
    return boto3.client("s3", **kwargs)


def _is_s3_missing_error(exc: BaseException) -> bool:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    code = str(response.get("Error", {}).get("Code", ""))
    return code in {"NoSuchKey", "NoSuchBucket", "404", "NotFound"}


def _derive_key(key_material: str) -> bytes:
    return hashlib.sha256(key_material.encode()).digest()


def _normalize_sha256(value: str) -> str:
    digest = value.removeprefix("sha256:")
    return f"sha256:{digest.lower()}"


def _remove_empty_parents(path: Path, root: Path) -> None:
    current = path.resolve()
    while current != root and current.is_relative_to(root):
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent
