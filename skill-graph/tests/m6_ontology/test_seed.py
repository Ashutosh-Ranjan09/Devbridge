"""The shipped contract, ../schemas/skills/ontology.yaml.

Everything above tests the loader against fixtures. This tests the actual file
the system runs on — and where it has to agree with m6-parameters.yaml.
"""
import yaml
from ontology_fixtures import ROOT, SEED_PATH

from m6_ontology import SeedOntology, default_ontology

PARAMETERS = ROOT / "contracts" / "m6-parameters.yaml"


def parameters() -> dict:
    return yaml.safe_load(PARAMETERS.read_text())


# ── the file itself ─────────────────────────────────────────────────────────
def test_the_shipped_seed_is_valid():
    """If this ever fails, nothing downstream would have told you."""
    assert SeedOntology.load(SEED_PATH).validate() == []


def test_the_default_ontology_is_the_shipped_seed():
    onto = default_ontology()
    assert onto.ontology_version == "0.2.0"
    assert len(onto) == 35 and len(onto.relations()) == 15


def test_the_default_is_loaded_once():
    """Read on every ingest; the file cannot change under a running process."""
    assert default_ontology() is default_ontology()


def test_the_skills_the_worked_example_needs_are_all_present():
    onto = default_ontology()
    for skill in ("cpp", "c", "algorithms", "typescript", "python", "problem_solving"):
        assert onto.knows(skill), skill


def test_the_published_propagation_edge_is_the_one_the_trace_uses():
    """The published /explain trace propagates cpp -> c. If this edge changed
    type, the damping would change and the published number would move."""
    edge, = [e for e in default_ontology().neighbours("cpp") if e.target == "c"]
    assert edge.type == "RELATED_TO"


# ── agreement with m6-parameters.yaml ───────────────────────────────────────
def test_every_edge_type_in_the_seed_has_a_gamma():
    """An edge whose type has no gamma is skipped silently by the propagator:
    the edge is in the contract, reads as active, and does nothing."""
    gammas = set(parameters()["propagation"]["gamma_per_edge_type"])
    used = {e.type for e in default_ontology().relations()}
    assert used <= gammas, f"no gamma for {sorted(used - gammas)}"


def test_every_tier_used_by_a_skill_has_a_decay_rate():
    """A tier with no lambda decays at whatever the fallback is, so evidence
    would age at a rate nobody chose. Tier reconciliation between the two files
    is asserted in tests/m6_scoring/test_params.py, which can see both."""
    rates = {k for k, v in parameters()["decay"]["lambda_per_day"].items()
             if isinstance(v, dict)}
    assert set(default_ontology().by_tier()) <= rates


def test_the_tiers_the_seed_declares_are_the_tiers_it_uses():
    """A declared-but-unused tier is dead contract; an used-but-undeclared one
    is caught by validate(). Both are worth knowing about."""
    onto = default_ontology()
    assert set(onto.tiers) == {s.tier for s in onto.skills()}
