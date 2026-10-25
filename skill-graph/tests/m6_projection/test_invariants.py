"""Every invariant provoked, not merely believed.

The happy-path tests in test_contract.py assert the invariants HOLD for the
fixtures. That is worth much less than it looks: an invariant checker with a
typo'd comparison passes those tests forever. These tests corrupt a batch on
purpose and require the checker to reject it — the same "guard the guard"
reasoning that test_schema_rejects_an_undeclared_field applies to the schema.
"""
import dataclasses

from helpers import full
from m6_projection import ContractViolation, project
from m6_projection.models import ReliabilityFactor, SkillRef, Suppressed
from m6_projection.projector import _check_invariants
from m6_projection.params import default_rules


def _batch():
    return project(full())


def _corrupt(batch, index=0, **changes):
    """Replace one event with a mutated copy, leaving the rest intact."""
    events = list(batch.events)
    events[index] = dataclasses.replace(events[index], **changes)
    return dataclasses.replace(batch, events=tuple(events))


def _rejects(batch, expected: str):
    try:
        _check_invariants(batch, default_rules())
    except ContractViolation as exc:
        assert expected in str(exc), f"rejected, but for the wrong reason: {exc}"
        return
    raise AssertionError(f"invariant did not fire; expected a complaint about {expected!r}")


def test_clean_batch_passes():
    """A control: if this failed, every test below would pass vacuously."""
    _check_invariants(_batch(), default_rules())


def test_empty_skill_refs_are_rejected():
    _rejects(_corrupt(_batch(), skill_refs=()), "no skill_refs")


def test_duplicate_event_ids_are_rejected():
    batch = _batch()
    duplicated = _corrupt(batch, index=1, event_id=batch.events[0].event_id)
    _rejects(duplicated, "duplicate event_id")


def test_reliability_inconsistent_with_its_factors_is_rejected():
    """reliability must equal base × factors. A hand-edited reliability that no
    longer follows from its stated factors is unexplainable to a candidate."""
    _rejects(_corrupt(_batch(), reliability=0.99), "!= base")


def test_undeclared_factor_is_rejected():
    """The mirror case: the arithmetic is wrong because a factor was applied
    without being recorded."""
    batch = _batch()
    ghost = ReliabilityFactor("secret_penalty", 0.5, "applied but not reflected in reliability")
    _rejects(_corrupt(batch, reliability_factors=(ghost,)), "!= base")


def test_out_of_range_reliability_is_rejected():
    """Factors cleared as well as the base, so the arithmetic check stays
    satisfied and the range check is what actually fires."""
    _rejects(_corrupt(_batch(), reliability=1.4, reliability_base=1.4, reliability_factors=()),
             "out of [0,1]")


def test_out_of_range_strength_is_rejected():
    _rejects(_corrupt(_batch(), strength=-0.1), "out of [0,1]")


def test_out_of_range_relevance_is_rejected():
    _rejects(_corrupt(_batch(), skill_refs=(SkillRef("python", 1.7),)), "relevance out of [0,1]")


def test_future_event_is_rejected():
    _rejects(_corrupt(_batch(), occurred_at="2099-01-01"), "future")


def test_suppression_reason_outside_the_enum_is_rejected():
    batch = _batch()
    bogus = dataclasses.replace(
        batch, not_emitted=(Suppressed("something", "looked_wrong_to_me"),))
    _rejects(bogus, "not in the schema enum")
