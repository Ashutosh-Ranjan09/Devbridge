"""Fixtures for the integrity suite."""
from __future__ import annotations

import copy, json, pathlib, sys
from datetime import date, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages"))
EXAMPLES = ROOT / "docs" / "docs" / "examples"

from m6 import M6  # noqa: E402
from m6_integrity import IntegrityAnalyser, IntegrityRules  # noqa: E402

AS_OF = date(2026, 8, 24)
SUBJECT = "subj_7a3f9e21"


def report(name="report-full.json") -> dict:
    return json.loads((EXAMPLES / name).read_text())


def loaded(name="report-full.json") -> M6:
    m6 = M6(":memory:")
    m6.ingest_report(report(name))
    return m6


def event(kind="repo_artifact", *, event_id="ev_x", occurred_at="2025-01-01",
          skills=("python",), relevance=0.9, origin="github_api",
          direction="positive", factors=(), strength=0.6, reliability=0.7) -> dict:
    return {"event_id": event_id, "kind": kind,
            "occurred_at": f"{occurred_at}T00:00:00Z",
            "skill_refs": [{"skill_id": s, "relevance": relevance} for s in skills],
            "strength": strength, "reliability": reliability, "direction": direction,
            "reliability_factors": [{"factor": f, "value": 0.6, "reason": "x"}
                                    for f in factors],
            "source": {"module": "m5-cv-verification", "module_version": "1.0.0",
                       "origin": origin},
            "payload": {}}


def analyse(events, *, as_of=AS_OF, states=None, quarantined=None, engine=None,
            rules=None):
    return IntegrityAnalyser(rules=rules, engine=engine).analyse(
        events, as_of, subject_ref=SUBJECT, states=states or {},
        quarantined=quarantined or {})


def codes(report_obj) -> set[str]:
    return {f.check_id for f in report_obj.findings}


def only(report_obj, check_id):
    hits = [f for f in report_obj.findings if f.check_id == check_id]
    assert hits, f"{check_id} did not fire; got {sorted(codes(report_obj))}"
    return hits[0]


def rules_without(*check_ids) -> IntegrityRules:
    raw = copy.deepcopy(IntegrityRules.load()._raw)
    raw["checks"] = [c for c in raw["checks"] if c["id"] not in check_ids]
    return IntegrityRules(raw)


def raises(exc_type, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc_type as exc:
        return exc
    raise AssertionError(f"expected {exc_type.__name__}")
