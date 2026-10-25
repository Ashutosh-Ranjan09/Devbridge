"""Shared test helpers. Plain functions rather than pytest fixtures so the suite
runs under `pytest` and under `python3 tests/run.py` identically."""
from __future__ import annotations

import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages"))

EXAMPLES = ROOT.parent / "schemas" / "examples"
SCHEMA = ROOT.parent / "schemas" / "evidence-event.schema.json"


def load_report(name: str) -> dict:
    """A fresh deep copy each time — tests mutate these freely."""
    return copy.deepcopy(json.loads((EXAMPLES / name).read_text()))


def full() -> dict:
    return load_report("report-full.json")


def degraded() -> dict:
    return load_report("report-degraded.json")


def validate(batch) -> None:
    """Validate a batch against the committed JSON Schema. Raises on failure."""
    import jsonschema
    jsonschema.validate(instance=batch.to_dict(), schema=json.loads(SCHEMA.read_text()))


def repo(**over) -> dict:
    base = {"name": "r", "exists": True, "is_fork": False, "owner_matches": True,
            "is_readme_only": False, "commit_count": 60, "size_kb": 500,
            "last_commit": "2025-06-01", "languages": {"Python": 10000}, "frameworks": []}
    base.update(over)
    return base


def credential(**over) -> dict:
    """Neither committed fixture carries a credential, so this is the only way
    the credential_verified branch is exercised at all."""
    base = {"credential_id": "cred_aws_saa", "issuer": "Amazon Web Services",
            "verified": True, "issued_at": "2025-02-11",
            "skill_refs": ["AWS", "cloud_architecture"]}
    base.update(over)
    return base


def with_credentials(report: dict, *creds) -> dict:
    report["evidence_bundle"]["credentials"] = list(creds)
    return report


def with_github(report: dict, **over) -> dict:
    gh = report["evidence_bundle"]["github"] or {}
    gh.update(over)
    report["evidence_bundle"]["github"] = gh
    return report


def ids(batch) -> list[str]:
    return [e.event_id for e in batch.events]


def by_kind(batch, kind: str) -> list:
    return [e for e in batch.events if e.kind == kind]


def skills(event) -> dict[str, float]:
    return {r.skill_id: r.relevance for r in event.skill_refs}
