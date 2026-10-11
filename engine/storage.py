"""Blob storage for rrweb recordings, screenshots, keyframes and diffs.

S3-compatible (Nebius Object Storage, R2, …) when S3_BUCKET is set; a local directory otherwise.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

from engine.settings import ROOT, env


class BlobStore(Protocol):
    name: str

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str: ...
    async def get(self, key: str) -> bytes: ...
    async def exists(self, key: str) -> bool: ...
    def public_url(self, key: str) -> str | None: ...


class LocalBlobStore:
    name = "local"

    def __init__(self, root: Path | None = None):
        self.root = root or ROOT / ".cache" / "blobs"

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not str(path).startswith(str(self.root.resolve())):
            raise ValueError(f"invalid blob key {key!r}")
        return path

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)
        return key

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def public_url(self, key: str) -> str | None:
        return None


class S3BlobStore:
    name = "s3"

    def __init__(self) -> None:
        import boto3

        self.bucket = env("S3_BUCKET")
        self.client = boto3.client(
            "s3",
            endpoint_url=env("S3_ENDPOINT_URL"),
            region_name=env("S3_REGION"),
            aws_access_key_id=env("S3_ACCESS_KEY_ID"),
            aws_secret_access_key=env("S3_SECRET_ACCESS_KEY"),
        )

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        await asyncio.to_thread(
            self.client.put_object, Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
        )
        return key

    async def get(self, key: str) -> bytes:
        obj = await asyncio.to_thread(self.client.get_object, Bucket=self.bucket, Key=key)
        return await asyncio.to_thread(obj["Body"].read)

    async def exists(self, key: str) -> bool:
        try:
            await asyncio.to_thread(self.client.head_object, Bucket=self.bucket, Key=key)
            return True
        except Exception:  # noqa: BLE001
            return False

    def public_url(self, key: str) -> str | None:
        base = env("S3_PUBLIC_BASE_URL")
        return f"{base.rstrip('/')}/{key}" if base else None


_store: BlobStore | None = None


def get_blob_store() -> BlobStore:
    global _store
    if _store is None:
        _store = S3BlobStore() if env("S3_BUCKET") else LocalBlobStore()
    return _store


def set_blob_store(store: BlobStore | None) -> None:
    global _store
    _store = store
