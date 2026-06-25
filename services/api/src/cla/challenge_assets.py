from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import hashlib
import json
from pathlib import Path
import tarfile
from typing import Any

from cla.settings import Settings


SKIPPED_PACKAGE_PARTS = {"__pycache__", ".git"}
SKIPPED_PACKAGE_SUFFIXES = {".pyc", ".pyo"}


@dataclass(frozen=True)
class StoredChallengeArtifact:
    object_ref: str
    sha256: str
    byte_count: int
    metadata: dict[str, Any]


class ChallengeArtifactStoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def challenge_package_digest(package_dir: Path) -> str:
    package_dir = package_dir.resolve()
    digest = hashlib.sha256()
    for path in _package_files(package_dir):
        relative = path.relative_to(package_dir).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def store_challenge_package(
    settings: Settings,
    *,
    tenant_id: str,
    slug: str,
    semver: str,
    package_dir: Path,
) -> StoredChallengeArtifact:
    package_dir = package_dir.resolve()
    digest = challenge_package_digest(package_dir)
    archive = _build_deterministic_tar(package_dir)
    object_ref = _store_bytes(
        settings,
        tenant_id=tenant_id,
        slug=slug,
        semver=semver,
        name=f"{_digest_value(digest)}.tar",
        payload=archive,
        content_type="application/x-tar",
    )
    return StoredChallengeArtifact(
        object_ref=object_ref,
        sha256=f"sha256:{hashlib.sha256(archive).hexdigest()}",
        byte_count=len(archive),
        metadata={
            "artifactKind": "challenge-package",
            "packageDigest": digest,
            "sourcePath": str(package_dir),
        },
    )


def store_generated_version_asset(
    settings: Settings,
    *,
    tenant_id: str,
    slug: str,
    semver: str,
    payload: dict[str, Any],
) -> StoredChallengeArtifact:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    sha256 = f"sha256:{hashlib.sha256(data).hexdigest()}"
    object_ref = _store_bytes(
        settings,
        tenant_id=tenant_id,
        slug=slug,
        semver=semver,
        name=f"generated-version-{_digest_value(sha256)}.json",
        payload=data,
        content_type="application/json",
    )
    return StoredChallengeArtifact(
        object_ref=object_ref,
        sha256=sha256,
        byte_count=len(data),
        metadata={"artifactKind": "generated-version-draft"},
    )


def store_generated_challenge_package(
    settings: Settings,
    *,
    tenant_id: str,
    slug: str,
    semver: str,
    files: dict[str, str],
) -> StoredChallengeArtifact:
    archive = _build_deterministic_tar_from_files(files)
    sha256 = f"sha256:{hashlib.sha256(archive).hexdigest()}"
    object_ref = _store_bytes(
        settings,
        tenant_id=tenant_id,
        slug=slug,
        semver=semver,
        name=f"generated-package-{_digest_value(sha256)}.tar",
        payload=archive,
        content_type="application/x-tar",
    )
    return StoredChallengeArtifact(
        object_ref=object_ref,
        sha256=sha256,
        byte_count=len(archive),
        metadata={
            "artifactKind": "generated-challenge-package",
            "fileCount": len(files),
            "files": sorted(files),
        },
    )


def _build_deterministic_tar(package_dir: Path) -> bytes:
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for path in _package_files(package_dir):
            relative = path.relative_to(package_dir).as_posix()
            info = archive.gettarinfo(str(path), arcname=relative)
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = 0
            with path.open("rb") as file_obj:
                archive.addfile(info, file_obj)
    return buffer.getvalue()


def _build_deterministic_tar_from_files(files: dict[str, str]) -> bytes:
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for relative in sorted(files):
            if relative.startswith("/") or ".." in Path(relative).parts:
                raise ChallengeArtifactStoreError(
                    "GENERATED_PACKAGE_PATH_INVALID",
                    f"Generated package path is invalid: {relative}",
                )
            data = files[relative].encode("utf-8")
            info = tarfile.TarInfo(relative)
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = 0
            info.size = len(data)
            archive.addfile(info, BytesIO(data))
    return buffer.getvalue()


def _package_files(package_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in package_dir.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(package_dir)
        if any(part in SKIPPED_PACKAGE_PARTS for part in relative.parts):
            continue
        if path.suffix in SKIPPED_PACKAGE_SUFFIXES or path.name == ".DS_Store":
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(package_dir).as_posix())


def _store_bytes(
    settings: Settings,
    *,
    tenant_id: str,
    slug: str,
    semver: str,
    name: str,
    payload: bytes,
    content_type: str,
) -> str:
    backend = settings.challenge_artifact_storage_backend
    if backend == "local":
        root = Path(settings.challenge_artifact_object_root)
        relative = Path(tenant_id) / slug / semver / name
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return f"local://challenge-artifacts/{relative.as_posix()}"
    if backend == "s3":
        return _store_s3(
            settings,
            tenant_id=tenant_id,
            slug=slug,
            semver=semver,
            name=name,
            payload=payload,
            content_type=content_type,
        )
    raise ChallengeArtifactStoreError(
        "CHALLENGE_ARTIFACT_BACKEND_UNSUPPORTED",
        f"Unsupported challenge artifact backend: {backend}",
    )


def _store_s3(
    settings: Settings,
    *,
    tenant_id: str,
    slug: str,
    semver: str,
    name: str,
    payload: bytes,
    content_type: str,
) -> str:
    if not settings.challenge_artifact_s3_bucket:
        raise ChallengeArtifactStoreError(
            "CHALLENGE_ARTIFACT_BUCKET_REQUIRED",
            "Challenge artifact S3 bucket is required",
        )
    import boto3
    from botocore.config import Config

    s3_config = (
        {"addressing_style": "path"}
        if settings.challenge_artifact_s3_force_path_style
        else {}
    )
    client = boto3.client(
        "s3",
        endpoint_url=settings.challenge_artifact_s3_endpoint_url,
        region_name=settings.challenge_artifact_s3_region,
        config=Config(s3=s3_config),
    )
    prefix = settings.challenge_artifact_s3_prefix.strip("/")
    key_parts = [part for part in [prefix, tenant_id, slug, semver, name] if part]
    key = "/".join(key_parts)
    client.put_object(
        Bucket=settings.challenge_artifact_s3_bucket,
        Key=key,
        Body=payload,
        ContentType=content_type,
    )
    return f"s3://{settings.challenge_artifact_s3_bucket}/{key}"


def _digest_value(value: str) -> str:
    return value.split(":", 1)[-1]
