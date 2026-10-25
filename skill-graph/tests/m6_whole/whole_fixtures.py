"""Fixtures for the composed-module suite."""
from __future__ import annotations

import json, pathlib, sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages"))
EXAMPLES = ROOT / "docs" / "docs" / "examples"
DEMO = ROOT / "demo" / "input" / "verification-report-extensive.json"

from m6 import M6  # noqa: E402

__all__ = ["M6", "ROOT", "report", "demo_report", "loaded", "raises"]

GOLDEN_AS_OF = date(2026, 8, 24)
DEMO_AS_OF = date(2026, 8, 30)
GOLDEN_SUBJECT = "subj_7a3f9e21"
DEMO_SUBJECT = "subj_c4f80a12"


def report(name="report-full.json") -> dict:
    return json.loads((EXAMPLES / name).read_text())


def demo_report() -> dict:
    return json.loads(DEMO.read_text())


def loaded(*reports) -> M6:
    m6 = M6(":memory:")
    for r in (reports or (report(),)):
        m6.ingest_report(r)
    return m6


def raises(exc_type, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc_type as exc:
        return exc
    raise AssertionError(f"expected {exc_type.__name__}, nothing was raised")
