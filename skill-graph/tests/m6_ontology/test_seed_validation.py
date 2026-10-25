"""The checks that stop a broken contract file reaching production.

Every failure here is silent in production if unchecked: an edge to a skill that
does not exist propagates nothing, a missing tier decays at the default rate,
and a duplicated skill_id splits one skill's evidence in two. All three produce
plausible numbers that nothing downstream is in a position to doubt.
"""
from ontology_fixtures import build, problems, raises, raw, written

from m6_ontology import InvalidOntology, SeedOntology


def only(**over) -> str:
    """The single problem the mutation should produce, as one string."""
    found = problems(**over)
    assert len(found) == 1, f"expected exactly one problem, got {found}"
    return found[0]


# ── the happy case ──────────────────────────────────────────────────────────
def test_a_sound_graph_has_no_problems():
    assert build().validate() == []


# ── edges ───────────────────────────────────────────────────────────────────
def test_an_edge_to_a_skill_that_does_not_exist_is_caught():
    """The silent one: propagation simply never fires, and the target's score is
    the prior. Nothing looks wrong."""
    said = only(edges=[{"from": "cpp", "to": "haskell", "type": "REQUIRES"}])
    assert "haskell" in said and "not a skill" in said


def test_an_edge_from_a_skill_that_does_not_exist_is_caught():
    assert "not a skill" in only(
        edges=[{"from": "haskell", "to": "cpp", "type": "REQUIRES"}])


def test_a_self_edge_is_caught():
    """cpp -> cpp would feed a skill's own evidence back as an inference about
    itself, at damped confidence — an update from no new information."""
    assert "imply itself" in only(
        edges=[{"from": "cpp", "to": "cpp", "type": "RELATED_TO"}])


def test_a_duplicated_edge_is_caught():
    """Two identical edges means two hops, so the target is updated twice from
    one source and lands more confident than the evidence supports."""
    edge = {"from": "cpp", "to": "algorithms", "type": "REQUIRES"}
    assert "duplicated" in only(edges=[edge, dict(edge)])


def test_the_same_pair_under_two_types_is_not_a_duplicate():
    """Different types carry different gammas, so it is a modelling choice
    rather than an error — a checker should not overrule it."""
    assert problems(edges=[{"from": "cpp", "to": "algorithms", "type": "REQUIRES"},
                           {"from": "cpp", "to": "algorithms", "type": "RELATED_TO"}]) == []


def test_an_incomplete_edge_is_caught():
    assert "needs from, to and type" in only(edges=[{"from": "cpp", "to": "algorithms"}])


def test_a_cycle_is_not_an_error():
    """Propagation runs one hop from direct-evidence sources only, so a cycle
    cannot loop. Flagging one would imply a constraint 6.3 does not have."""
    assert problems(edges=[{"from": "cpp", "to": "algorithms", "type": "REQUIRES"},
                           {"from": "algorithms", "to": "cpp", "type": "REQUIRES"}]) == []


# ── skills ──────────────────────────────────────────────────────────────────
def test_a_skill_without_a_tier_is_caught():
    said = only(skills={"cpp": {"label": "C++"}}, edges=[])
    assert "no tier" in said and "default rate" in said


def test_a_tier_not_declared_in_the_contract_is_caught():
    said = only(skills={"cpp": {"tier": "medium-ish"}}, edges=[])
    assert "medium-ish" in said


def test_a_skill_id_that_is_not_lower_snake_case_is_caught():
    """ids are matched literally across the M5 boundary: `React` and `react`
    would be two skills sharing one meaning and splitting its evidence."""
    said = only(skills={"React": {"tier": "framework"}}, edges=[])
    assert "lower_snake_case" in said


def test_an_empty_graph_is_caught():
    said = problems(skills={}, edges=[])
    assert any("every incoming skill_ref would be quarantined" in p for p in said)


def test_a_missing_version_is_caught():
    """Receipts record which ontology judged a batch. A default version makes
    that record a lie."""
    assert any("ontology_version" in p for p in problems(ontology_version="0.0.0"))


# ── reporting ───────────────────────────────────────────────────────────────
def test_every_problem_is_reported_not_just_the_first():
    """Fixing a contract file one error per run is how a half-corrected
    ontology gets deployed."""
    found = problems(skills={"cpp": {}, "Bad": {"tier": "nope"}},
                     edges=[{"from": "cpp", "to": "ghost", "type": "REQUIRES"}])
    assert len(found) >= 4, found


# ── loading ─────────────────────────────────────────────────────────────────
def test_loading_a_broken_seed_refuses_by_default():
    path = written(raw(edges=[{"from": "cpp", "to": "haskell", "type": "REQUIRES"}]))
    exc = raises(InvalidOntology, SeedOntology.load, path)
    assert str(path) in str(exc), "the error should name the file to fix"
    assert exc.problems


def test_a_broken_seed_can_still_be_loaded_deliberately():
    """`check` has to be able to load the broken file in order to report on it."""
    path = written(raw(edges=[{"from": "cpp", "to": "haskell", "type": "REQUIRES"}]))
    onto = SeedOntology.load(path, strict=False)
    assert len(onto.validate()) == 1


def test_a_sound_seed_loads_from_file_with_everything_intact():
    onto = SeedOntology.load(written(raw()))
    assert onto.ontology_version == "test-1.0"
    assert len(onto) == 4 and len(onto.relations()) == 2
    assert onto.tiers["ecosystem"] == "medium"


def test_a_skill_entry_that_is_not_a_mapping_is_caught():
    """`python:` with nothing after it is valid YAML and parses to None. Without
    this branch validate() raises AttributeError on the contract file rather
    than reporting what is wrong with it."""
    said = only(skills={"cpp": None}, edges=[])
    assert "expected a mapping" in said and "NoneType" in said


def test_a_shorthand_skill_entry_is_caught_rather_than_crashing():
    """`cpp: fundamental` is the obvious hand-edit and the wrong shape."""
    said = only(skills={"cpp": "fundamental"}, edges=[])
    assert "expected a mapping" in said and "str" in said


def test_a_repr_says_which_graph_it_is():
    """Ontologies get compared in debugging sessions; `<SeedOntology object at
    0x7f...>` twice is not a comparison."""
    assert repr(build()) == "SeedOntology(version='test-1.0', skills=4, edges=2)"
