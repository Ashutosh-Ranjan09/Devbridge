"""Comparison by DEFINITE interval overlap — the constraint, implemented.

The rule the design fixed early: two candidates may only be ordered when their
credible intervals do not overlap. Where they do overlap, the honest answer is
"these are not distinguishable on this evidence", and a recruiter who is shown a
strict ordering there is being told something the data does not support.

So this module produces a PARTIAL order: tiers of candidates nobody can separate,
with tiers themselves strictly ordered. Inside a tier the sort is alphabetical,
deliberately — anything else would read as a ranking and get used as one.

This is also where the "no overall trust score" constraint bites. There is no
function here that combines skills into one number, because the moment such a
function exists someone will sort by it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True, slots=True)
class Candidate:
    """One (subject, skill) result: an interval, not a point."""
    subject_ref: str
    skill_id: str
    lower: float
    upper: float
    evidence_count: int
    propagated_from: str | None = None

    @property
    def is_inferred(self) -> bool:
        """No direct evidence — the score came from a neighbour in the ontology.
        A caller filtering for demonstrated ability wants these out."""
        return self.evidence_count == 0

    def overlaps(self, other: "Candidate") -> bool:
        return self.lower <= other.upper and other.lower <= self.upper

    def definitely_above(self, other: "Candidate") -> bool:
        """The only comparison this system is willing to assert."""
        return self.lower > other.upper


@dataclass(frozen=True, slots=True)
class Tier:
    """Candidates that cannot be separated on the available evidence."""
    rank: int
    members: tuple[Candidate, ...]

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "indistinguishable": len(self.members) > 1,
            "candidates": [
                {"subject_ref": c.subject_ref, "skill_id": c.skill_id,
                 "interval": [round(c.lower, 3), round(c.upper, 3)],
                 "evidence_count": c.evidence_count,
                 "inferred_from": c.propagated_from}
                for c in self.members],
        }


def meets_threshold(candidate: Candidate, minimum: float, *, definite: bool) -> bool:
    """Does this candidate clear `minimum`?

    Two readings, and the caller must choose:

      definite=True   the whole interval clears it — we are confident they are
                      above the bar. Fewer, safer results.
      definite=False  the interval reaches it — they might be above the bar.
                      More results, some of which are merely un-refuted.

    Defaulting silently to either would be making a recruiter's risk decision for
    them, so the endpoint takes it as an explicit parameter.
    """
    return candidate.lower >= minimum if definite else candidate.upper >= minimum


def tiers(candidates: Iterable[Candidate]) -> list[Tier]:
    """Group into strictly-ordered tiers of mutually indistinguishable results.

    A new tier begins only where a candidate is definitely below every member of
    the current one. That is a real ordering claim; anything finer is not.
    """
    ordered: Sequence[Candidate] = sorted(
        candidates, key=lambda c: (-c.lower, -c.upper, c.subject_ref, c.skill_id))
    if not ordered:
        return []

    out: list[Tier] = []
    current: list[Candidate] = [ordered[0]]
    floor = ordered[0].lower          # the lowest lower-bound in the current tier

    for candidate in ordered[1:]:
        if candidate.upper < floor:
            out.append(_seal(len(out) + 1, current))
            current, floor = [candidate], candidate.lower
        else:
            current.append(candidate)
            floor = min(floor, candidate.lower)
    out.append(_seal(len(out) + 1, current))
    return out


def _seal(rank: int, members: list[Candidate]) -> Tier:
    # Alphabetical inside a tier. Ordering by point score here would recreate
    # exactly the false precision the tiers exist to prevent.
    return Tier(rank=rank,
                members=tuple(sorted(members, key=lambda c: (c.subject_ref, c.skill_id))))
