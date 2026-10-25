"""Report → projection → ingestor → scoring, over the real storage layer.

The other suites test each module against fixtures. This one runs the whole
chain the way production will, so a shape change anywhere fails here rather than
at integration.
"""
from datetime import date, timedelta

from scoring_fixtures import AS_OF, PUBLISHED, engine, report
from m6_ingestor import EventLog, Ingestor
from m6_ontology import default_ontology
from m6_projection import project
from m6_scoring import Propagator, ScoringEngine, edges_from_ontology


def pipeline(name="report-full.json"):
    """Everything, end to end, through a real (in-memory) database."""
    log = EventLog(":memory:")
    Ingestor(log, ontology=default_ontology()).ingest(
        project(report(name), module_version="0.4.1").to_dict())
    return log


def test_the_whole_chain_reproduces_the_published_graph():
    log = pipeline()
    eng = engine()
    events = [e.document for e in log.events()]
    for skill, published in PUBLISHED.items():
        got = eng.fold(events, skill, AS_OF).state.score(eng.p.z)
        assert abs(got - published) < 0.01, f"{skill}: chain {got:.3f}, published {published}"


def test_scoring_reads_per_skill_agree_with_reading_the_whole_log():
    """6.3 queries per skill rather than loading everything. The narrow read must
    give the same answer, or the optimisation silently changes the score."""
    log = pipeline()
    eng = engine()
    everything = [e.document for e in log.events()]
    for skill in PUBLISHED:
        narrow = [e.document for e in log.events_for_skill(skill)]
        assert abs(eng.fold(everything, skill, AS_OF).state.mu
                   - eng.fold(narrow, skill, AS_OF).state.mu) < 1e-12, skill


def test_quarantined_skills_do_not_reach_the_scorer():
    """The ingestor holds them out of scoring reads; nothing downstream has to
    remember to filter."""
    log = EventLog(":memory:")
    batch = project(report(), module_version="0.4.1").to_dict()
    batch["events"][0]["skill_refs"] = [{"skill_id": "quantum_telepathy", "relevance": 0.9}]
    Ingestor(log, ontology=default_ontology()).ingest(batch)
    assert log.events_for_skill("quantum_telepathy") == []
    assert engine().fold([e.document for e in log.events_for_skill("quantum_telepathy")],
                         "quantum_telepathy", AS_OF).is_prior_only


def test_replaying_the_batch_changes_no_score():
    """Idempotent ingestion, stated in the terms that matter: the graph is
    identical after a redelivery."""
    log = pipeline()
    eng = engine()
    before = {s: eng.fold([e.document for e in log.events()], s, AS_OF).state.mu
              for s in PUBLISHED}
    for _ in range(3):
        Ingestor(log, ontology=default_ontology()).ingest(
            project(report(), module_version="0.4.1").to_dict())
    after = {s: eng.fold([e.document for e in log.events()], s, AS_OF).state.mu
             for s in PUBLISHED}
    assert before == after


def test_an_unconsented_report_produces_an_empty_graph():
    """Both gates in sequence, then the scorer having nothing to score."""
    from m6_ingestor import ConsentRefused
    log = EventLog(":memory:")
    batch = project(report("report-degraded.json"), module_version="0.4.1").to_dict()
    try:
        Ingestor(log, ontology=default_ontology()).ingest(batch)
        raise AssertionError("an unconsented batch was ingested")
    except ConsentRefused:
        pass
    assert engine().fold_all([e.document for e in log.events()], AS_OF) == {}


def test_the_graph_decays_as_a_whole_without_new_evidence():
    """Every skill must lose confidence, and none may gain any."""
    log = pipeline()
    eng = engine()
    events = [e.document for e in log.events()]
    now = eng.fold_all(events, AS_OF)
    later = eng.fold_all(events, AS_OF + timedelta(days=730))
    for skill, state in now.items():
        assert later[skill].state.var > state.state.var, skill
        assert later[skill].state.score(eng.p.z) < state.state.score(eng.p.z), skill


def test_the_full_graph_with_propagation_is_schema_valid_throughout():
    from scoring_fixtures import validate_state
    log = pipeline()
    eng = engine()
    direct = eng.fold_all([e.document for e in log.events()], AS_OF,
                          subject_ref="subj_7a3f9e21")
    everything = Propagator(eng).propagate(
        direct, edges_from_ontology(default_ontology()), AS_OF)
    assert len(everything) > len(direct), "propagation added nothing"
    for state in everything.values():
        validate_state(state)


def test_a_parameter_sweep_moves_scores_without_breaking_the_ordering():
    """What the report's sensitivity chapter needs: the ranking should be robust
    to the constants even where the values are not."""
    from m6_scoring.params import default_parameters
    log = pipeline()
    events = [e.document for e in log.events()]
    base = engine()
    ranking = sorted(PUBLISHED, key=lambda s: -base.fold(events, s, AS_OF).state.score(1.0))

    for s0 in (0.05, 0.30):
        swept = ScoringEngine(default_parameters().replacing(observation__S0=s0),
                              ontology=default_ontology())
        got = sorted(PUBLISHED,
                     key=lambda s: -swept.fold(events, s, AS_OF).state.score(swept.p.z))
        assert got == ranking, f"S0={s0} reordered the graph: {got} vs {ranking}"
