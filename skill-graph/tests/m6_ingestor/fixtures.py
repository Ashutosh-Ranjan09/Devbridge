"""Fixtures for the ingestor suite.

Named `fixtures` rather than `helpers` so it cannot collide with the projection
suite's module of that name — test files import siblings by bare name, so two
`helpers` modules in one run would silently shadow each other.
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages"))

EXAMPLES = ROOT.parent / "schemas" / "examples"

from m6_ingestor import EventLog, Ingestor  # noqa: E402
from m6_ontology import AcceptAll  # noqa: E402
from m6_projection import project  # noqa: E402


def report(name: str = "report-full.json") -> dict:
    return copy.deepcopy(json.loads((EXAMPLES / name).read_text()))


def batch(name: str = "report-full.json", **over) -> dict:
    """A real projected batch — the actual thing the ingestor will receive,
    rather than a hand-written approximation of it."""
    doc = project(report(name), module_version="0.4.1").to_dict()
    doc.update(over)
    return doc


def ingestor(*, ontology=None, log=None) -> Ingestor:
    """In-memory by default: every test gets a clean, isolated log."""
    return Ingestor(log or EventLog(":memory:"),
                    ontology=AcceptAll() if ontology is None else ontology)


def seeded_ingestor(**kw) -> Ingestor:
    """An ingestor whose log already holds the full batch."""
    ing = ingestor(**kw)
    ing.ingest(batch())
    return ing


def mutate_event(doc: dict, index: int = 0, **changes) -> dict:
    out = copy.deepcopy(doc)
    out["events"][index].update(changes)
    return out


def ids(doc: dict) -> list[str]:
    return [e["event_id"] for e in doc["events"]]


def raises(exc_type, fn, *args, **kwargs):
    """Assert fn raises exc_type, and hand the exception back for inspection."""
    try:
        fn(*args, **kwargs)
    except exc_type as exc:
        return exc
    raise AssertionError(f"expected {exc_type.__name__}, nothing was raised")
