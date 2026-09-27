"""Disk cache for Gemini calls, keyed by a stable hash of (model, prompt, config).

A cache hit lets the pipeline re-run for free; cost.py records hits separately
from priced calls so the end-of-run summary reflects that.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from eventscout.config import CACHE_DIR


def cache_key(model: str, prompt: str, config: dict) -> str:
    payload = json.dumps({"model": model, "prompt": prompt, "config": config}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def get(key: str) -> dict | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def put(key: str, value: dict) -> None:
    _cache_path(key).write_text(json.dumps(value, indent=2))
