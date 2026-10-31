"""Read-time propagation — O5, O7.

Three constraints, each of which stops a specific failure: read time (a stored
propagated state would become a source and evidence would drift arbitrarily
far), one hop, and direct-evidence sources only (which is what makes the pass
loop-free without cycle detection).
"""
from published_trace import published_trace
from scoring_fixtures import AS_OF, engine, events, validate_state
from m6_ontology import default_ontology
from m6_scoring import Propagator, edges_from_ontology


def propagated():
    eng = engine()
    direct = eng.fold_all(events(), AS_OF, subject_ref="subj_7a3f9e21")
    out = Propagator(eng).propagate(direct, edges_from_ontology(default_ontology()), AS_OF)
    return eng, direct, out


def test_edges_are_read_from_the_ontology_contract():
    edges = edges_from_ontology(default_ontology())
    assert ("cpp", "c", "RELATED_TO") in edges
    assert all(len(e) == 3 for e in edges)


def test_propagation_reaches_a_skill_with_no_direct_evidence():
    _, direct, out = propagated()
    assert "c" not in direct
    assert "c" in out


def test_a_propagated_state_reproduces_the_published_trace():
    """The trace publishes c at 0.378 propagated from cpp. cpp itself moved to
    0.507 after the CV-dating fix, so c follows it down slightly."""
    # The published trace was computed with the approximated Codeforces table; see
    # contracts/reference/published_trace.py.
    with published_trace():
        eng, _, out = propagated()
        assert abs(out["c"].state.score(eng.p.z) - 0.378) < 0.02


def test_a_propagated_state_carries_its_provenance():
    """A score with no evidence behind it has to say where it came from."""
    _, _, out = propagated()
    block = out["c"].propagated
    assert block == {"from_skill_id": "cpp", "edge_type": "RELATED_TO", "gamma": 0.40}


def test_a_propagated_state_still_reports_zero_evidence():
    """Propagation is inference, not evidence. This is the field the query API
    uses to say 'inferred' rather than clamping the number."""
    _, _, out = propagated()
    assert out["c"].evidence_count == 0 and out["c"].is_prior_only


def test_a_propagated_state_conforms_to_the_schema():
    _, _, out = propagated()
    validate_state(out["c"])


def test_direct_evidence_is_never_overwritten_by_an_inference():
    """Real evidence about a skill always beats an inference about it."""
    eng, direct, out = propagated()
    for skill, state in direct.items():
        if state.evidence_count > 0:
            assert out[skill] is state, f"{skill} was overwritten by propagation"
            assert out[skill].propagated is None


def test_a_propagated_state_is_weaker_than_its_source():
    """Damping is variance inflation, so the inference must be less certain than
    the evidence it came from — otherwise propagation manufactures confidence."""
    eng, direct, out = propagated()
    assert out["c"].state.var > direct["cpp"].state.var
    assert out["c"].state.score(eng.p.z) < direct["cpp"].state.score(eng.p.z)


def test_a_lower_gamma_damps_harder():
    eng = engine()
    direct = eng.fold_all(events(), AS_OF)
    strong = Propagator(eng).propagate(direct, [("cpp", "c", "REQUIRES")], AS_OF)
    weak = Propagator(eng).propagate(direct, [("cpp", "c", "RELATED_TO")], AS_OF)
    assert eng.p.gamma["RELATED_TO"] < eng.p.gamma["REQUIRES"]
    assert weak["c"].state.var > strong["c"].state.var


def test_propagation_sources_only_from_direct_evidence():
    """The property that makes one pass loop-free. cpp -> c -> d must not carry
    evidence two hops, because c is not a direct-evidence state."""
    eng = engine()
    direct = eng.fold_all(events(), AS_OF)
    out = Propagator(eng).propagate(
        direct, [("cpp", "c", "REQUIRES"), ("c", "d", "REQUIRES")], AS_OF)
    assert "c" in out
    assert "d" not in out, "evidence travelled two hops in one pass"


def test_a_cycle_terminates():
    eng = engine()
    direct = eng.fold_all(events(), AS_OF)
    out = Propagator(eng).propagate(
        direct, [("cpp", "c", "REQUIRES"), ("c", "cpp", "REQUIRES")], AS_OF)
    assert out["cpp"].evidence_count == 2, "the cycle wrote back over real evidence"


def test_an_edge_from_a_skill_with_no_evidence_propagates_nothing():
    eng = engine()
    out = Propagator(eng).propagate({}, [("cpp", "c", "REQUIRES")], AS_OF)
    assert out == {}


def test_an_unknown_edge_type_is_ignored_rather_than_guessed():
    """One gamma per TYPE, never per edge. An unrecognised type has no gamma, and
    inventing one would be an unbounded parameter nobody could sweep."""
    eng = engine()
    direct = eng.fold_all(events(), AS_OF)
    out = Propagator(eng).propagate(direct, [("cpp", "c", "VIBES_WITH")], AS_OF)
    assert "c" not in out


def test_propagation_is_not_persisted():
    """Nothing here writes. A stored propagated state would become a source for
    further propagation on the next pass."""
    eng, direct, out = propagated()
    again = Propagator(eng).propagate(direct, edges_from_ontology(default_ontology()), AS_OF)
    assert abs(again["c"].state.mu - out["c"].state.mu) < 1e-12


def test_a_propagated_skill_can_outrank_an_evidenced_one():
    """Documented, not fixed. c reaches ~0.37 on no evidence of its own, above
    python's 0.19 which rests on a real repository. The honest fix is to SHOW
    evidence_count 0 and the propagated block — clamping the number would be
    lying about the model rather than improving it."""
    eng, direct, out = propagated()
    z = eng.p.z
    assert out["c"].state.score(z) > direct["python"].state.score(z)
    assert out["c"].evidence_count == 0 and direct["python"].evidence_count == 1
