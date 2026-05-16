"""diskcache wrapper for LLM responses.

Cache key = sha256 of (provider, model, prompt, schema_version). Hits are
free + deterministic; misses make a network call. The cache lives at
`Settings.llm_cache_dir` (default `.cache/llm/`, gitignored).

Reasoning for diskcache vs alternatives:
- sqlite-based, persists across runs (idempotency req from ADR-004)
- thread-safe — important when we batch+concurrent
- no server, fits the local-only constraint (ADR-004)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import diskcache


class LLMCache:
    """Thin wrapper around diskcache. Public API: `get`, `set`."""

    def __init__(self, cache_dir: Path) -> None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache = diskcache.Cache(str(cache_dir))

    @staticmethod
    def make_key(provider: str, model: str, prompt: str, schema_version: str) -> str:
        """Deterministic key for a (provider, model, prompt, schema) tuple."""
        h = hashlib.sha256()
        h.update(provider.encode("utf-8"))
        h.update(b"\x00")
        h.update(model.encode("utf-8"))
        h.update(b"\x00")
        h.update(schema_version.encode("utf-8"))
        h.update(b"\x00")
        h.update(prompt.encode("utf-8"))
        return h.hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        raw = self._cache.get(key)
        if raw is None:
            return None
        result: dict[str, Any] = json.loads(raw)
        return result

    def set(self, key: str, value: dict[str, Any]) -> None:
        self._cache.set(key, json.dumps(value, sort_keys=True))

    def close(self) -> None:
        self._cache.close()

    def __enter__(self) -> LLMCache:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
