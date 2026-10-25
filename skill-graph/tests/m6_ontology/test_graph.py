"""The accessors 6.2, 6.3 and 6.4 each depend on."""
from ontology_fixtures import GOOD, build, raises

from m6_ontology import Edge, Skill, UnknownSkill


# ── membership: what 6.2 asks ───────────────────────────────────────────────
def test_knows_answers_for_present_and_absent_skills():
    onto = build()
    assert onto.knows("cpp")
    assert not onto.knows("quantum_telepathy")


def test_an_absent_skill_is_false_never_an_error():
    """6.2's quarantine is built on asking about skills it expects to be missing.
    If this raised, the ingestor would have to catch an exception on its normal
    path and would eventually catch too much."""
    assert build().knows("") is False


def test_membership_reads_as_containment():
    onto = build()
    assert "react" in onto and "haskell" not in onto
    assert len(onto) == 4


# ── volatility: what 6.3 asks ───────────────────────────────────────────────
def test_tier_is_the_skills_own_property():
    onto = build()
    assert onto.tier("cpp") == "fundamental"
    assert onto.tier("react") == "framework"


def test_an_unknown_skill_has_no_tier_rather_than_a_default_one():
    """None lets 6.3 tell "this ontology has no opinion" from "this ontology
    says fundamental" — it has its own fallback and needs to know when to use it."""
    assert build().tier("haskell") is None


def test_every_skill_carries_a_label_for_display():
    assert build().label("cpp") == "C++"
    assert build().label("haskell") is None


def test_a_skill_object_carries_id_tier_and_label_together():
    skill = build().skill("typescript")
    assert isinstance(skill, Skill)
    assert (skill.skill_id, skill.tier, skill.label) == ("typescript", "ecosystem", "TypeScript")


def test_asking_strictly_for_an_absent_skill_names_the_version():
    exc = raises(UnknownSkill, build().skill, "haskell")
    assert "test-1.0" in str(exc), "the error should say WHICH graph lacks it"


# ── edges: what 6.3 traverses ───────────────────────────────────────────────
def test_relations_are_typed_directed_edges():
    edges = build().relations()
    assert all(isinstance(e, Edge) for e in edges)
    assert Edge("cpp", "algorithms", "REQUIRES") in edges


def test_neighbours_are_outgoing_only():
    """Direction decides which way evidence may move. If `neighbours` returned
    incident edges, propagation would run backwards along half of them."""
    onto = build()
    assert [e.target for e in onto.neighbours("cpp")] == ["algorithms"]
    assert onto.neighbours("algorithms") == (), "nothing propagates OUT of algorithms here"


def test_the_raw_edge_shape_is_what_the_scoring_reader_expects():
    """6.3's edges_from_ontology reads e["from"], e["to"], e["type"] off this."""
    edge = build().edges[0]
    assert set(edge) == {"from", "to", "type"}


def test_edges_are_copies_so_a_caller_cannot_mutate_the_graph():
    onto = build()
    onto.edges.clear()
    onto.edges[0]["to"] = "haskell"
    assert onto.edges[0]["to"] == "algorithms"


# ── the whole graph ─────────────────────────────────────────────────────────
def test_skill_ids_are_sorted_so_output_is_stable():
    assert build().skill_ids() == ["algorithms", "cpp", "react", "typescript"]


def test_by_tier_groups_every_skill_and_loses_none():
    grouped = build().by_tier()
    assert grouped["fundamental"] == ["algorithms", "cpp"]
    assert sum(len(v) for v in grouped.values()) == 4


def test_tiers_carry_the_prose_that_defines_them():
    """A tier name alone does not say what it means; the contract's definition
    travels with it so a reviewer can check a skill is filed correctly."""
    assert build().tiers["framework"] == "fast"


def test_to_dict_round_trips_through_the_constructor():
    onto = build()
    again = build(GOOD)
    assert onto.to_dict() == again.to_dict()
    assert onto.to_dict()["ontology_version"] == "test-1.0"


def test_iterating_yields_every_skill():
    assert {s.skill_id for s in build()} == set(build().skill_ids())
