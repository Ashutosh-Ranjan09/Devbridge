"""On-disk response cache, with a freshness budget per source.

Two reasons this is not optional. Rate limits: GitHub gives 60 requests an hour
unauthenticated, and one CV with four named repositories spends about twenty — so a
handful of development runs exhausts it. And reproducibility: a verification re-run
against a cached response gives the same evidence, which is what makes a stored report
explainable months later.

The freshness budgets come from how fast each source actually moves. A Codeforces
rating changes after a contest; a repository's creation date never does.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

CACHE_DIR = Path(".cache/http")

# Days. codeforces 7 · github 30 · credentials 90, per the design.
TTL_DAYS: dict[str, int] = {
    "codeforces": 7,
    "github": 30,
    "leetcode": 7,
    "codechef": 7,
    "issuers": 90,
    "http_probe": 1,
}
DEFAULT_TTL_DAYS = 7


def _path(source: str, key: str) -> Path:
    digest = hashlib.sha256(key.encode()).hexdigest()[:20]
    return CACHE_DIR / source / f"{digest}.json"


def get(source: str, key: str) -> Any | None:
    """The cached response, or None if absent or stale."""
    path = _path(source, key)
    if not path.is_file():
        return None
    try:
        entry = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None

    ttl = TTL_DAYS.get(source, DEFAULT_TTL_DAYS) * 86400
    if time.time() - entry.get("fetched_at", 0) > ttl:
        return None
    return entry.get("body")


def put(source: str, key: str, body: Any) -> None:
    path = _path(source, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"fetched_at": time.time(), "key": key, "body": body}, indent=2)
    )


def response_hash(body: Any) -> str:
    """Recorded in provenance, so a finding can be traced to the exact response that
    produced it even after the source has moved on."""
    return "sha256:" + hashlib.sha256(
        json.dumps(body, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
