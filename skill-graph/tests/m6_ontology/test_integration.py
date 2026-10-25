"""What each submodule asks 6.1 for, and what changes when the answer changes.

Mutation testing found the gap this file fills. Making `tier()` return None
broke only two tests, one of them 6.1's own and the other a contract-consistency
check — nothing asserted that the ontology's tier is what actually decides how
fast a score decays. An ontology can be wired in and still not be *load-bearing*,
and the tests looked the same either way.

Each test here substitutes an ontology and asserts a downstream number moves.
"""
from datetime import date, timedelta

from ontology_fixtures import ROOT, build, raw

from m6_ontology import SeedOntology, default_ontology
from m6_scoring import Propagator, ScoringEngine, edges_from_ontology

AS_OF = date(2026, 8, 24)
SUBJECT = "subj_integration"


def events(skill: str = "cpp", *, when: str = "2024-01-15") -> list[dict]:
    """One repo_artifact event in the shape 6.3 actually folds, old enough that
    the difference between two half-lives is visible by AS_OF."""
    return [{
        "event_id": "ev_int_1", "kind": "repo_artifact",
        "occurred_at": f"{when}T00:00:00Z", "direction": "positive",
        "skill_refs": [{"skill_id": skill, "relevance": 0.9}],
        "strength": 0.7, "reliability": 0.85,
        "source": {"module": "m5-cv-verification", "module_version": "0.4.1",
                   "origin": "github_api"},
        "payload": {"substance_band": "substantial"},
    }]


def tiered(skill: str, tier: str) -> SeedOntology:
    return SeedOntology({skill: {"tier": tier, "label": skill}}, "tier-probe-1.0")


# ── 6.3 asks: how fast does this decay? ─────────────────────────────────────
def test_the_ontologys_tier_is_what_sets_the_half_life():
    fast = ScoringEngine(ontology=tiered("cpp", "framework"))
    slow = ScoringEngine(ontology=tiered("cpp", "fundamental"))
    assert fast.p.half_life("framework") < slow.p.half_life("fundamental")
    assert fast.tier_of("cpp") == "framework" and slow.tier_of("cpp") == "fundamental"


def test_retiering_a_skill_changes_the_score_it_reaches():
    """The behavioural claim. Same events, same parameters, same date — only the
    ontology's opinion about volatility differs, and the number moves."""
    fast = ScoringEngine(ontology=tiered("cpp", "framework")).fold(
        events(), "cpp", AS_OF, subject_ref=SUBJECT)
    slow = ScoringEngine(ontology=tiered("cpp", "fundamental")).fold(
        events(), "cpp", AS_OF, subject_ref=SUBJECT)

    z = 1.0
    assert fast.tier == "framework" and slow.tier == "fundamental"
    assert fast.state.var > slow.state.var, "a framework signal ages into more doubt"
    assert fast.state.score(z) < slow.state.score(z)
    assert (fast.state.upper(z) - fast.state.score(z)) > \
           (slow.state.upper(z) - slow.state.score(z)), "and a wider interval"


def test_an_ontology_with_no_opinion_falls_back_rather_than_guessing():
    """`tier()` returns None for an unknown skill so 6.3 can tell "no opinion"
    from "fundamental" and reach for m6-parameters' fallback list."""
    engine = ScoringEngine(ontology=SeedOntology({}, "empty-1.0"))
    assert engine.ontology.tier("cpp") is None
    assert engine.tier_of("cpp") == "fundamental", "the parameters fallback, not a default"
    assert engine.tier_of("nothing_anywhere") == engine.p.default_tier


# ── 6.3 asks: what does this imply? ─────────────────────────────────────────
def test_the_typed_edges_are_what_the_propagator_actually_reads():
    """Not `edges` — `relations()`. This was the other mutation finding: the
    typed accessor existed, the README said 6.3 used it, and nothing did."""
    triples = edges_from_ontology(default_ontology())
    assert ("cpp", "c", "RELATED_TO") in triples
    assert len(triples) == len(default_ontology().relations())


def test_a_bare_stub_with_an_edges_list_still_works():
    """The fallback path. A test ought to be able to say "these two edges"
    without constructing an ontology."""
    class Stub:
        edges = [{"from": "a", "to": "b", "type": "REQUIRES"}]
    assert edges_from_ontology(Stub()) == [("a", "b", "REQUIRES")]
    assert edges_from_ontology(object()) == []


def test_adding_an_edge_makes_a_skill_appear_that_was_not_there():
    """The whole point of an edge: evidence for one skill becomes an inference
    about another. Substituting the ontology is what turns that on."""
    without = SeedOntology({"cpp": {"tier": "fundamental"},
                            "c": {"tier": "fundamental"}}, "no-edge-1.0")
    with_edge = SeedOntology({"cpp": {"tier": "fundamental"},
                              "c": {"tier": "fundamental"}}, "one-edge-1.0",
                             [{"from": "cpp", "to": "c", "type": "RELATED_TO"}])

    def reached(onto):
        engine = ScoringEngine(ontology=onto)
        direct = engine.fold_all(events(), AS_OF, subject_ref=SUBJECT)
        return Propagator(engine).propagate(direct, edges_from_ontology(onto), AS_OF)

    assert "c" not in reached(without)
    inferred = reached(with_edge)["c"]
    assert inferred.evidence_count == 0, "an inference is never evidence"
    assert inferred.propagated["from_skill_id"] == "cpp"


def test_the_edge_type_chosen_in_the_contract_changes_the_damping():
    """gamma is per TYPE. Editing the seed's `type:` field is a modelling change,
    not a label change, and it has to be visible as one."""
    def strength(edge_type):
        onto = SeedOntology({"cpp": {"tier": "fundamental"}, "c": {"tier": "fundamental"}},
                            "t-1.0", [{"from": "cpp", "to": "c", "type": edge_type}])
        engine = ScoringEngine(ontology=onto)
        direct = engine.fold_all(events(), AS_OF, subject_ref=SUBJECT)
        return Propagator(engine).propagate(
            direct, edges_from_ontology(onto), AS_OF)["c"].state.var

    # REQUIRES (0.65) damps less than RELATED_TO (0.40), so it leaves less doubt.
    assert strength("REQUIRES") < strength("RELATED_TO")


# ── 6.2 asks: does this skill exist? ────────────────────────────────────────
def test_the_ontology_version_that_judged_a_batch_reaches_the_receipt():
    """A quarantine decision is only interpretable against a version: the same
    event is held under 0.1.0 and admitted under 0.2.0."""
    import sys
    sys.path.insert(0, str(ROOT / "tests" / "m6_ingestor"))
    from fixtures import batch, ingestor
    from m6_ingestor import EventLog

    receipt = ingestor(log=EventLog(":memory:"),
                       ontology=SeedOntology({"python": {"tier": "ecosystem"}},
                                             "probe-9.9")).ingest(batch())
    assert receipt.ontology_version == "probe-9.9"


# ── 6.4 asks: what can be filtered on? ──────────────────────────────────────
def test_the_query_api_publishes_the_ontologys_skills_with_their_half_lives():
    import sys
    sys.path.insert(0, str(ROOT / "tests" / "m6_query"))
    from query_fixtures import service

    published = {row["skill_id"]: row for row in service().known_skills()}
    assert set(published) == set(default_ontology().skill_ids())
    assert published["react"]["volatility_tier"] == "framework"
    assert published["react"]["half_life_days"] == 467
    assert published["algorithms"]["half_life_days"] == 3500


# ── the composed module ─────────────────────────────────────────────────────
def test_all_four_consumers_hold_the_same_ontology_object():
    """Two ontologies in one process would mean a skill could be known to the
    scorer and unknown to the ingestor, and the graph would disagree with itself."""
    import sys
    sys.path.insert(0, str(ROOT / "packages"))
    from m6 import M6

    onto = SeedOntology({"python": {"tier": "ecosystem"}}, "shared-1.0")
    with M6(":memory:", ontology=onto) as m6:
        assert m6.ontology is onto
        assert m6.ingestor.ontology is onto
        assert m6.engine.ontology is onto
        assert m6.query.ontology is onto
        assert m6.integrity_analyser.engine.ontology is onto


def test_the_ontology_version_travels_into_every_answer():
    import sys
    sys.path.insert(0, str(ROOT / "packages"))
    from m6 import M6

    with M6(":memory:") as m6:
        versions = m6.versions()
    assert versions["ontology"] == default_ontology().ontology_version
    assert versions["m6_ontology"], "the package version too, not only the graph's"
