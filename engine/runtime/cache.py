"""Content-addressed disk cache for LLM responses (PLAN A7.7: cache every call in dev and evals)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from engine.settings import ROOT, env, load_config


def cache_key(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


class DiskCache:
    def __init__(self, directory: Path | None = None, enabled: bool | None = None):
        cfg = load_config("budgets").get("cache", {})
        self.dir = directory or ROOT / cfg.get("dir", ".cache/llm")
        if enabled is None:
            enabled = cfg.get("enabled", True) and env("WHYDUNIT_LLM_CACHE", "1") != "0"
        self.enabled = enabled

    def _path(self, key: str) -> Path:
        return self.dir / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        path = self._path(key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def put(self, key: str, value: dict[str, Any]) -> None:
        if not self.enabled:
            return
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, default=str))
        tmp.replace(path)
