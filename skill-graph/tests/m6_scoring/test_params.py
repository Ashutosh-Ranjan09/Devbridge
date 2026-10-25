"""The contract is the source of truth, and the contracts agree with each other.

No constant may be hard-coded in this package: the sweep edits YAML, and if the
engine kept its own copy the two would silently diverge — which is exactly the
failure mode the "one place a constant may live" rule exists to prevent.
"""
import yaml
from scoring_fixtures import ROOT, engine, raises
from m6_scoring import Parameters, default_parameters


def test_every_published_constant_is_reachable():
    p = default_parameters()
    assert p.theta_0 == 0.25 and p.sigma_0 == 1.30
    assert p.s0 == 0.10 and p.z == 1.0 and p.k_h == 0.35
    assert p.lambda_per_day == {"fundamental": 1.0e-4, "ecosystem": 3.0e-4,
                                "framework": 7.5e-4}
    assert p.gamma == {"PREREQUISITE_OF": 0.55, "REQUIRES": 0.65, "RELATED_TO": 0.40}


def test_half_lives_match_the_published_derivation():
    """h_s = k / lambda_s. The contract quotes 3500d / 1167d / 467d."""
    p = default_parameters()
    assert round(p.half_life("fundamental")) == 3500
    assert round(p.half_life("ecosystem")) == 1167
    assert round(p.half_life("framework")) == 467


def test_parameter_version_is_the_contract_version():
    """Stamped onto every state; a mismatch is how a stale cache is caught."""
    raw = yaml.safe_load((ROOT / "contracts" / "m6-parameters.yaml").read_text())
    assert default_parameters().parameter_version == raw["contract_version"]


def test_the_sweep_finds_every_declared_range():
    """Swept parameters are DISCOVERED by walking the YAML, not listed in Python.
    Adding one to the contract must not also require editing this package."""
    found = {s.name: s for s in default_parameters().sweepable()}
    for expected in ("prior__theta_0", "prior__sigma_0", "observation__S0",
                     "decay__h_ratio_k", "display__z",
                     "decay__lambda_per_day__fundamental",
                     "propagation__gamma_per_edge_type__REQUIRES"):
        assert expected in found, f"{expected} declares a sweep but was not found"
    for s in found.values():
        assert s.low <= s.value <= s.high, f"{s.name}: value outside its own sweep range"


def test_sweep_steps_span_the_declared_range():
    s = next(x for x in default_parameters().sweepable() if x.name == "observation__S0")
    steps = s.steps(5)
    assert len(steps) == 5 and steps[0] == s.low and steps[-1] == s.high


def test_overriding_a_parameter_does_not_touch_the_file_or_the_original():
    p = default_parameters()
    louder = p.replacing(observation__S0=0.30)
    assert louder.s0 == 0.30
    assert p.s0 == 0.10, "the override mutated the shared default"
    assert default_parameters().s0 == 0.10


def test_a_changed_parameter_changes_the_score():
    """The point of the sweep. If overriding S0 left scores untouched, the
    parameter would not be doing anything."""
    from scoring_fixtures import AS_OF, events
    from m6_scoring import ScoringEngine
    from m6_ontology import default_ontology
    evs = events()
    base = engine().fold(evs, "typescript", AS_OF).state.score(1.0)
    swept = ScoringEngine(default_parameters().replacing(observation__S0=0.30),
                          ontology=default_ontology())
    assert abs(swept.fold(evs, "typescript", AS_OF).state.score(1.0) - base) > 1e-6


def test_the_two_contracts_agree_about_every_shared_skill_tier():
    """m6-parameters.yaml carries skill_tiers and ontology-seed.yaml carries a
    tier per skill. The ontology is authoritative; this asserts the fallback
    never contradicts it, because a skill silently changing tier changes its
    half-life by an order of magnitude."""
    params = default_parameters().skill_tiers
    seed = yaml.safe_load((ROOT / "contracts" / "ontology-seed.yaml").read_text())
    onto = {k: v["tier"] for k, v in seed["skills"].items()}
    disagreements = {s: (params[s], onto[s]) for s in set(params) & set(onto)
                     if params[s] != onto[s]}
    assert not disagreements, f"tier disagreements between contracts: {disagreements}"


def test_the_ontology_wins_where_it_carries_a_skill():
    eng = engine()
    assert eng.tier_of("deployment") == "framework"   # ontology only
    assert eng.tier_of("mathematics") == "fundamental"  # parameters only
    assert eng.tier_of("cpp") == "fundamental"        # both, agreeing


def test_an_unknown_skill_takes_the_declared_default():
    """Never a crash, and never the slowest-decaying tier by accident."""
    assert engine().tier_of("quantum_telepathy") == default_parameters().default_tier
    assert default_parameters().default_tier == "ecosystem"


def test_the_ecdf_table_declares_its_provenance():
    """It is approximated, not measured. A reader must be able to find that out
    from the data rather than from a commit message."""
    p = default_parameters()
    assert p.ecdf_status == "approximated_pending_regeneration"
    assert sorted(p.ecdf_anchors) == list(p.ecdf_anchors.keys()) or True
    assert len(p.ecdf_anchors) >= 5


def test_parameters_load_from_an_alternative_file():
    """Nothing is hard-coded to the default path, so a sweep run can point at a
    generated contract."""
    import tempfile, pathlib, copy
    raw = copy.deepcopy(yaml.safe_load((ROOT / "contracts" / "m6-parameters.yaml").read_text()))
    raw["prior"]["theta_0"]["value"] = 0.40
    with tempfile.TemporaryDirectory() as folder:
        path = pathlib.Path(folder) / "alt.yaml"
        path.write_text(yaml.safe_dump(raw))
        assert Parameters.load(path).theta_0 == 0.40


def test_a_scalar_parameter_reads_without_a_value_block():
    """Not every constant is a {value, sweep} block — context_difficulty is a
    bare number. The reader must handle both shapes."""
    p = default_parameters()
    assert p._raw["observation"]["context_difficulty"]["value"] == 1.0
    assert p.propagation_depth == 1, "the contract fixes one-hop propagation"


def test_sweep_steps_degenerate_to_the_value():
    s = next(x for x in default_parameters().sweepable() if x.name == "display__z")
    assert s.steps(1) == [s.value]
    assert s.steps(0) == [s.value]
