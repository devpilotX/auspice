"""The content addressed raw store.

Section 6.1 engineering rule 1: every fetched byte stream is saved under the SHA-256 of its
content, with a sidecar recording the URL, the fetch time, the response headers and the
jurisdiction. Never overwrite. Never delete.

That rule is the compounding asset and the entire reason a late competitor cannot catch up.
Extraction methods improve; the corpus is only re-processable if you kept it.

Two backends. ``local`` writes under a directory and is what development uses. ``s3`` targets
Cloudflare R2 or any S3 compatible endpoint, chosen in section 7.2 for zero egress, because the
corpus gets re-read every time a prompt changes.

The key layout is ``ab/cd/abcdef...`` so no directory ends up with a million entries. That
matters on a local filesystem and it matters for listing cost on object storage.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from auspice.config import RawStoreBackend, Settings, get_settings
from auspice.logging import get_logger

log = get_logger(__name__, _stage="ingest")

SIDECAR_SUFFIX = ".meta.json"


def content_hash(data: bytes) -> str:
    """Lowercase hex SHA-256. The document primary key."""
    return hashlib.sha256(data).hexdigest()


def storage_key(digest: str, *, suffix: str = "") -> str:
    if len(digest) != 64:
        raise ValueError(f"expected a 64 character sha256 hex digest, got {len(digest)}")
    return f"{digest[:2]}/{digest[2:4]}/{digest}{suffix}"


@dataclass(frozen=True, slots=True)
class StoredObject:
    digest: str
    key: str
    byte_size: int
    already_present: bool
    metadata: dict[str, Any]


class RawStore(ABC):
    """Write once, read many. There is no update and no delete."""

    @abstractmethod
    def put(self, data: bytes, *, metadata: dict[str, Any], suffix: str = "") -> StoredObject: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def get_metadata(self, key: str) -> dict[str, Any]: ...

    @abstractmethod
    def describe(self) -> str: ...


class LocalRawStore(RawStore):
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / key

    def put(self, data: bytes, *, metadata: dict[str, Any], suffix: str = "") -> StoredObject:
        digest = content_hash(data)
        key = storage_key(digest, suffix=suffix)
        path = self._path(key)

        if path.exists():
            # Same content hash means the same bytes. Nothing to do, and nothing downstream
            # needs to re-run. This is the idempotent re-fetch from section 6.1 rule 3.
            return StoredObject(
                digest=digest,
                key=key,
                byte_size=path.stat().st_size,
                already_present=True,
                metadata=self.get_metadata(key),
            )

        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temporary name and move, so a crash mid write cannot leave a truncated
        # object under a hash that claims to describe complete content.
        staging = path.with_suffix(path.suffix + ".partial")
        staging.write_bytes(data)
        staging.replace(path)

        enriched = {
            **metadata,
            "sha256": digest,
            "byte_size": len(data),
            "stored_at": datetime.now(UTC).isoformat(),
        }
        Path(str(path) + SIDECAR_SUFFIX).write_text(
            json.dumps(enriched, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )

        log.debug("stored", key=key, bytes=len(data))
        return StoredObject(digest=digest, key=key, byte_size=len(data), already_present=False, metadata=enriched)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def get_metadata(self, key: str) -> dict[str, Any]:
        sidecar = Path(str(self._path(key)) + SIDECAR_SUFFIX)
        if not sidecar.exists():
            return {}
        loaded: dict[str, Any] = json.loads(sidecar.read_text(encoding="utf-8"))
        return loaded

    def describe(self) -> str:
        return f"local:{self.root}"


class S3RawStore(RawStore):
    """S3 compatible, which in practice means Cloudflare R2.

    Metadata goes into a sidecar object rather than S3 user metadata, because user metadata is
    capped at 2 KB and response headers routinely exceed that.
    """

    def __init__(self, settings: Settings) -> None:
        import boto3

        self.bucket = settings.raw_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.raw_endpoint_url or None,
            aws_access_key_id=settings.raw_access_key_id,
            aws_secret_access_key=settings.raw_secret_access_key,
            region_name="auto",
        )

    def put(self, data: bytes, *, metadata: dict[str, Any], suffix: str = "") -> StoredObject:
        digest = content_hash(data)
        key = storage_key(digest, suffix=suffix)

        if self.exists(key):
            return StoredObject(
                digest=digest,
                key=key,
                byte_size=len(data),
                already_present=True,
                metadata=self.get_metadata(key),
            )

        enriched = {
            **metadata,
            "sha256": digest,
            "byte_size": len(data),
            "stored_at": datetime.now(UTC).isoformat(),
        }
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data)
        self._client.put_object(
            Bucket=self.bucket,
            Key=key + SIDECAR_SUFFIX,
            Body=json.dumps(enriched, indent=2, sort_keys=True, default=str).encode("utf-8"),
            ContentType="application/json",
        )
        log.debug("stored", key=key, bytes=len(data), bucket=self.bucket)
        return StoredObject(digest=digest, key=key, byte_size=len(data), already_present=False, metadata=enriched)

    def get(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self.bucket, Key=key)
        body: bytes = response["Body"].read()
        return body

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        return True

    def get_metadata(self, key: str) -> dict[str, Any]:
        try:
            raw = self.get(key + SIDECAR_SUFFIX)
        except Exception:  # noqa: BLE001 - a missing sidecar is not fatal
            return {}
        loaded: dict[str, Any] = json.loads(raw)
        return loaded

    def describe(self) -> str:
        return f"s3:{self.bucket}"


def get_raw_store(settings: Settings | None = None) -> RawStore:
    resolved = settings or get_settings()
    if resolved.raw_backend is RawStoreBackend.s3:
        return S3RawStore(resolved)
    return LocalRawStore(resolved.raw_local_root)


MediaKind = Literal["document", "audio", "transcript"]
