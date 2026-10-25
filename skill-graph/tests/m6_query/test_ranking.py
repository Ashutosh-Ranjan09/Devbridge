"""Interval-overlap comparison, in isolation.

The rule: two candidates may only be ordered when their intervals do not
overlap. Everything else is "not distinguishable on this evidence". These are
pure functions, so they can be tested exhaustively rather than through the API.
"""
from m6_query import Candidate, meets_threshold, tiers


def c(ref, lower, upper, evidence=1, propagated_from=None):
    return Candidate(subject_ref=ref, skill_id="python", lower=lower, upper=upper,
                     evidence_count=evidence, propagated_from=propagated_from)


# ── the primitive comparisons ───────────────────────────────────────────────
def test_overlap_is_symmetric():
    a, b = c("a", 0.3, 0.6), c("b", 0.5, 0.8)
    assert a.overlaps(b) and b.overlaps(a)


def test_touching_intervals_overlap():
    """Adjacent bounds are not a separation. Asserting an order on a shared
    endpoint would be claiming a difference of exactly zero."""
    assert c("a", 0.3, 0.5).overlaps(c("b", 0.5, 0.7))


def test_definitely_above_requires_a_real_gap():
    assert c("a", 0.7, 0.9).definitely_above(c("b", 0.3, 0.6))
    assert not c("a", 0.5, 0.9).definitely_above(c("b", 0.3, 0.6))
    assert not c("a", 0.3, 0.6).definitely_above(c("b", 0.7, 0.9))


def test_a_wide_interval_is_above_nothing():
    """Uncertainty costs you the comparison, which is the point."""
    vague = c("vague", 0.05, 0.95)
    assert not vague.definitely_above(c("other", 0.4, 0.5))
    assert not c("other", 0.4, 0.5).definitely_above(vague)


# ── thresholds ──────────────────────────────────────────────────────────────
def test_definite_requires_the_whole_interval_to_clear():
    straddling = c("a", 0.4, 0.8)
    assert not meets_threshold(straddling, 0.6, definite=True)
    assert meets_threshold(straddling, 0.6, definite=False)


def test_definite_and_possible_agree_when_the_interval_is_unambiguous():
    clear = c("a", 0.7, 0.9)
    below = c("b", 0.1, 0.3)
    for definite in (True, False):
        assert meets_threshold(clear, 0.6, definite=definite)
        assert not meets_threshold(below, 0.6, definite=definite)


def test_a_zero_threshold_admits_everyone():
    assert meets_threshold(c("a", 0.01, 0.02), 0.0, definite=True)


# ── tiering ─────────────────────────────────────────────────────────────────
def test_no_candidates_gives_no_tiers():
    assert tiers([]) == []


def test_separated_candidates_land_in_their_own_tiers():
    got = tiers([c("low", 0.1, 0.2), c("high", 0.8, 0.9), c("mid", 0.4, 0.5)])
    assert [t.rank for t in got] == [1, 2, 3]
    assert [t.members[0].subject_ref for t in got] == ["high", "mid", "low"]
    assert all(len(t.members) == 1 for t in got)


def test_overlapping_candidates_share_one_tier():
    got = tiers([c("a", 0.30, 0.60), c("b", 0.45, 0.75), c("d", 0.50, 0.80)])
    assert len(got) == 1
    assert got[0].to_dict()["indistinguishable"] is True


def test_a_tier_is_sorted_alphabetically_not_by_score():
    """Ordering inside a tier by point score would recreate exactly the false
    precision the tiers exist to prevent."""
    got = tiers([c("zeta", 0.50, 0.80), c("alpha", 0.45, 0.75), c("mid", 0.48, 0.78)])
    assert len(got) == 1
    assert [m.subject_ref for m in got[0].members] == ["alpha", "mid", "zeta"]


def test_a_new_tier_starts_only_below_every_member_of_the_last():
    """b overlaps a, and d overlaps b but NOT a. d must stay with b, because it
    is not definitely below everything above it."""
    got = tiers([c("a", 0.60, 0.90), c("b", 0.50, 0.70), c("d", 0.35, 0.55)])
    assert len(got) == 1, [t.to_dict() for t in got]


def test_a_clear_gap_does_split_the_tiers():
    got = tiers([c("a", 0.60, 0.90), c("b", 0.55, 0.70), c("far", 0.05, 0.20)])
    assert len(got) == 2
    assert [m.subject_ref for m in got[0].members] == ["a", "b"]
    assert [m.subject_ref for m in got[1].members] == ["far"]


def test_tiers_are_strictly_ordered_between_themselves():
    """Everything in tier n must be definitely above something in tier n+1, or
    the split was not justified."""
    got = tiers([c("a", 0.80, 0.95), c("b", 0.40, 0.60), c("d", 0.05, 0.20)])
    for upper_tier, lower_tier in zip(got, got[1:]):
        assert any(x.definitely_above(y)
                   for x in upper_tier.members for y in lower_tier.members)


def test_tiering_is_deterministic_regardless_of_input_order():
    people = [c("a", 0.80, 0.95), c("b", 0.40, 0.60), c("d", 0.05, 0.20),
              c("e", 0.45, 0.65)]
    forward = [t.to_dict() for t in tiers(people)]
    backward = [t.to_dict() for t in tiers(list(reversed(people)))]
    assert forward == backward


def test_identical_candidates_never_separate():
    got = tiers([c("a", 0.5, 0.7), c("b", 0.5, 0.7), c("d", 0.5, 0.7)])
    assert len(got) == 1 and len(got[0].members) == 3


def test_a_single_candidate_is_not_marked_indistinguishable():
    assert tiers([c("only", 0.4, 0.6)])[0].to_dict()["indistinguishable"] is False


# ── what a tier publishes ───────────────────────────────────────────────────
def test_the_serialised_tier_carries_intervals_not_points():
    row = tiers([c("a", 0.4, 0.6)])[0].to_dict()["candidates"][0]
    assert row["interval"] == [0.4, 0.6]
    assert "score" not in row, "a bare point invites sorting by it"


def test_an_inferred_candidate_says_where_it_came_from():
    row = tiers([c("a", 0.4, 0.6, evidence=0, propagated_from="cpp")])[0]
    assert row.members[0].is_inferred
    assert row.to_dict()["candidates"][0]["inferred_from"] == "cpp"
