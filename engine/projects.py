"""Projects and their ingest API keys. Keys are shown once and stored as sha256 hashes."""

from __future__ import annotations

import hashlib
import secrets

from engine import db


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


async def create_project(project_id: str, name: str, key: str | None = None) -> str:
    key = key or f"wd_{project_id}_{secrets.token_urlsafe(18)}"
    await db.execute(
        "INSERT INTO projects (id, name, api_key_hash) VALUES (%s, %s, %s) "
        "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, api_key_hash = EXCLUDED.api_key_hash",
        (project_id, name, hash_key(key)),
    )
    return key


async def project_for_key(key: str) -> str | None:
    row = await db.fetchrow("SELECT id FROM projects WHERE api_key_hash = %s", (hash_key(key),))
    return row["id"] if row else None
