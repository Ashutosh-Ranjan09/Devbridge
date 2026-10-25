"""Fixtures for the query suite.

The other suites work from one subject, because that is all report-full.json
describes. Search only means anything across several, so this builds a small
synthetic population by re-labelling the real batch — real event shapes, real
projection output, different people and different amounts of evidence.
"""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages"))

EXAMPLES = ROOT / "docs" / "docs" / "examples"

from m6_ingestor import EventLog, Ingestor  # noqa: E402
from m6_ontology import default_ontology  # noqa: E402
from m6_projection import project  # noqa: E402
from m6_query import QueryService  # noqa: E402
from m6_scoring import ScoringEngine  # noqa: E402

AS_OF = date(2026, 8, 24)
SUBJECT = "subj_7a3f9e21"


def report(name: str = "report-full.json") -> dict:
    return json.loads((EXAMPLES / name).read_text())


def batch(name: str = "report-full.json") -> dict:
    return project(report(name), module_version="0.4.1").to_dict()


def relabelled(subject_ref: str, *, keep: int | None = None,
               scale_reliability: float = 1.0, downgrade: bool = False) -> dict:
    """The golden batch as a different person.

    event_id must stay unique per subject or the ingestor will correctly treat
    the second arrival as a duplicate of the first, so ids are rehashed with the
    subject mixed in — the same rule the projection follows.
    """
    doc = copy.deepcopy(batch())
    doc["subject_ref"] = subject_ref
    doc["batch_id"] = f"evb_{hashlib.sha256(subject_ref.encode()).hexdigest()[:12]}"
    doc["verification_id"] = f"ver_{subject_ref}"
    events = doc["events"][:keep] if keep is not None else doc["events"]
    for event in events:
        seed = f"{subject_ref}|{event['event_id']}"
        event["event_id"] = f"ev_{hashlib.sha256(seed.encode()).hexdigest()[:12]}"
        event["source"]["verification_id"] = doc["verification_id"]
        if downgrade and event["kind"] == "repo_artifact":
            # A genuinely weaker developer, not merely a less-trusted one.
            # Scaling reliability changes how CONFIDENT the estimate is; only a
            # different observed value changes WHERE it lands, which is what it
            # takes to separate two candidates.
            event.setdefault("payload", {})["substance_band"] = "trivial"
        if scale_reliability != 1.0:
            event["reliability"] = round(
                min(event["reliability"] * scale_reliability, 1.0), 6)
            event["reliability_base"] = round(
                min(event.get("reliability_base", event["reliability"]) * scale_reliability,
                    1.0), 6)
            event.pop("reliability_factors", None)
    doc["events"] = events
    return doc


def log_with(*batches) -> EventLog:
    log = EventLog(":memory:")
    ingestor = Ingestor(log, ontology=default_ontology())
    for doc in batches or (batch(),):
        ingestor.ingest(doc)
    return log


def service(log=None) -> QueryService:
    ontology = default_ontology()
    return QueryService(log or log_with(), ScoringEngine(ontology=ontology),
                        ontology=ontology)


def population() -> QueryService:
    """Four developers with genuinely different evidence:

      subj_strong    the full batch
      subj_7a3f9e21  the same, under its own id — the golden subject
      subj_thin      the first three events: one typescript repo instead of
                     three corroborating events, so a materially wider interval
      subj_weak      the full batch at a third of the reliability

    `keep=3` rather than a rounder number because event 2 is the first that
    mentions typescript, and a fixture with no evidence for the skill under test
    would make the search tests pass for the wrong reason.
    """
    return service(log_with(
        batch(),
        relabelled("subj_strong"),
        relabelled("subj_thin", keep=3),
        relabelled("subj_weak", scale_reliability=0.33)))


def raises(exc_type, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_type as exc:
        return exc
    raise AssertionError(f"expected {exc_type.__name__}, nothing was raised")


def walk(node):
    """Every (key, value) pair anywhere in a nested response."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)
