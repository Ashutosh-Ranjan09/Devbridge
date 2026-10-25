"""M5 report → projection → ingestor → fold → the published skill graph.

The chain the whole module exists to serve. If any link changes shape, this
fails here rather than at integration.
"""
import pathlib
import sys
from datetime import date

from fixtures import ROOT, consented, ingestor, report
from m6_ingestor import EventLog, Ingestor
from m6_ontology import default_ontology
from m6_projection import project

sys.path.insert(0, str(ROOT / "contracts" / "reference"))
import m6_model as M  # noqa: E402

TIER = {"algorithms": "fundamental", "problem_solving": "fundamental", "cpp": "fundamental",
        "typescript": "ecosystem", "javascript": "ecosystem", "python": "ecosystem",
        "nextjs": "framework", "react": "framework", "mongodb": "framework",
        "deployment": "framework"}
OBSERVED = {"platform_rating": 0.74, "claim_corroborated": 0.68, "artifact_live": 0.58,
            "repo_artifact": {"small": 0.50, "substantial": 0.62, "large": 0.66},
            "cv_claim": {"proficient": 0.60, "expert": 0.75, None: 0.45}}
PUBLISHED = {"algorithms": 0.533, "cpp": 0.514, "typescript": 0.381,
             "nextjs": 0.316, "python": 0.189, "mongodb": 0.173}


def _observed(document):
    payload = document.get("payload") or {}
    if document["kind"] == "repo_artifact":
        return OBSERVED["repo_artifact"][payload["substance_band"]]
    if document["kind"] == "cv_claim":
        return OBSERVED["cv_claim"][payload.get("proficiency")]
    return OBSERVED[document["kind"]]


def _foldable(stored):
    return [{"event_id": e.document["event_id"],
             "occurred_at": date.fromisoformat(e.document["occurred_at"][:10]),
             "strength": e.document["strength"], "reliability": e.document["reliability"],
             "observed": _observed(e.document), "skill_refs": e.document["skill_refs"]}
            for e in stored]


def _loaded():
    ing = Ingestor(EventLog(":memory:"), ontology=default_ontology())
    ing.ingest(project(report(), module_version="0.4.1").to_dict())
    return ing


def test_the_full_chain_reproduces_the_published_graph():
    events = _foldable(_loaded().log.events())
    for skill, published in PUBLISHED.items():
        state = M.fold(events, skill, TIER[skill], date(2026, 8, 24))
        assert abs(state.score() - published) < 0.01, \
            f"{skill}: chain gives {state.score():.3f}, trace published {published}"


def test_reading_one_skill_from_the_log_folds_the_same_as_reading_all():
    """6.3 will query per skill rather than loading the log. The two paths must
    agree, or the optimisation silently changes the answer."""
    log = _loaded().log
    everything = _foldable(log.events())
    for skill in PUBLISHED:
        narrow = _foldable(log.events_for_skill(skill))
        assert abs(M.fold(everything, skill, TIER[skill], date(2026, 8, 24)).score()
                   - M.fold(narrow, skill, TIER[skill], date(2026, 8, 24)).score()) < 1e-9, skill


def test_replaying_the_batch_does_not_change_a_single_score():
    """The property that makes at-least-once delivery safe, stated in the terms
    that actually matter: the graph is identical after a redelivery."""
    ing = _loaded()
    before = {s: M.fold(_foldable(ing.log.events()), s, TIER[s], date(2026, 8, 24)).score()
              for s in PUBLISHED}
    for _ in range(3):
        ing.ingest(project(report(), module_version="0.4.1").to_dict())
    after = {s: M.fold(_foldable(ing.log.events()), s, TIER[s], date(2026, 8, 24)).score()
             for s in PUBLISHED}
    assert before == after
    assert ing.log.count() == 8


def test_an_unconsented_report_reaches_the_graph_as_nothing():
    """Both gates, in sequence, on the real degraded fixture."""
    from m6_ingestor import ConsentRefused
    doc = project(report("report-degraded.json"), module_version="0.4.1").to_dict()
    assert doc["events"] == []
    ing = ingestor()
    try:
        ing.ingest(doc)
        raise AssertionError("an unconsented batch was ingested")
    except ConsentRefused:
        pass
    assert ing.log.count() == 0


def test_the_log_preserves_everything_the_fold_needs():
    """A round trip through SQLite must not lose or coerce a field — floats
    especially, since they are what the filter arithmetic runs on."""
    original = {e["event_id"]: e for e in consented()["events"]}
    for stored in _loaded().log.events():
        assert stored.document == original[stored.event_id]
