"""Fixtures for the scoring suite. Unique module name so it cannot shadow the
other suites' helpers — tests/run.py fails loudly if two ever collide."""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages"))
sys.path.insert(0, str(ROOT / "contracts" / "reference"))

EXAMPLES = ROOT.parent / "schemas" / "examples"
STATE_SCHEMA = ROOT / "contracts" / "schemas" / "skill-state.schema.json"

from m6_ontology import default_ontology  # noqa: E402
from m6_projection import project  # noqa: E402
from m6_scoring import ScoringEngine  # noqa: E402

AS_OF = date(2026, 8, 24)

# The graph published in docs/m6-worked-trace.html §06.
PUBLISHED = {"algorithms": 0.533, "cpp": 0.514, "typescript": 0.381,
             "nextjs": 0.316, "python": 0.189, "mongodb": 0.173}


def report(name: str = "report-full.json") -> dict:
    return json.loads((EXAMPLES / name).read_text())


def events(name: str = "report-full.json") -> list[dict]:
    """The real projected batch — what the engine will actually be handed."""
    return [e.to_dict() for e in project(report(name), module_version="0.4.1").events]


def engine(**kw) -> ScoringEngine:
    return ScoringEngine(ontology=default_ontology(), **kw)


def event(kind="repo_artifact", *, event_id="ev_test", occurred_at="2025-01-01",
          skill="python", relevance=1.0, strength=0.6, reliability=0.7,
          direction="positive", **payload) -> dict:
    """One synthetic event, so a test can isolate a single variable."""
    return {"event_id": event_id, "kind": kind, "occurred_at": f"{occurred_at}T00:00:00Z",
            "skill_refs": [{"skill_id": skill, "relevance": relevance}],
            "strength": strength, "reliability": reliability, "direction": direction,
            "source": {"module": "m5-cv-verification", "module_version": "0.4.1",
                       "origin": "test"},
            "payload": payload}


def validate_state(skill_state) -> None:
    """Against contracts/schemas/skill-state.schema.json."""
    import jsonschema
    jsonschema.validate(instance=skill_state.to_dict(),
                        schema=json.loads(STATE_SCHEMA.read_text()))


def scores(states, z=1.0) -> dict[str, float]:
    return {k: v.state.score(z) for k, v in states.items()}


def raises(exc_type, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_type as exc:
        return exc
    raise AssertionError(f"expected {exc_type.__name__}, nothing was raised")
