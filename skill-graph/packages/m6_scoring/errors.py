"""Failures the scoring engine can have."""
from __future__ import annotations


class ScoringError(Exception):
    """Base for everything this package raises."""


class UnscoreableEvent(ScoringError):
    """An event the observation model cannot turn into a number.

    Raised rather than defaulted. A silently-defaulted observation is a score
    nobody can explain, and every score in this system has to be explainable —
    there is no overall trust number to hide behind.
    """


class ParameterMismatch(ScoringError):
    """A stored SkillState was computed under a different parameter_version.

    States are a derived cache, so the fix is always to recompute rather than to
    reconcile. Mixing two parameter sets in one graph makes the ordering between
    skills meaningless, which is the one property the whole design rests on.
    """

    def __init__(self, skill_id: str, stored: str, current: str) -> None:
        super().__init__(
            f"{skill_id} was computed under parameter_version {stored}, "
            f"engine is running {current}; recompute rather than mixing")
        self.stored, self.current = stored, current
