"""A claim that pools several platforms when only some were verified.

"Solved 500+ problems across LeetCode, Codeforces, GeeksforGeeks" is two things
at once: a verified fact (Codeforces reports 412) and an unverifiable assertion
(the rest). Counting it once at full weight overstates it; suppressing it
discards a real number. Both halves are kept, and neither twice.
"""
from helpers import by_kind, full
from m6_projection import project
from m6_projection.params import Rules, default_rules


def _aggregate(report=None):
    batch = project(report or full())
    return next(e for e in by_kind(batch, "cv_claim")
                if e.payload.get("metric") == "problems_solved")


def _factors(event):
    return {f.factor: f.value for f in event.reliability_factors}


def test_aggregate_claim_is_discounted_not_suppressed():
    """It is weak evidence, not absent evidence — the graph must still be able
    to tell "claimed and partly backed" from "never mentioned"."""
    event = _aggregate()
    assert event.reliability_base == 0.20
    assert abs(event.reliability - 0.20 * 0.7 * 0.85) < 1e-9


def test_both_discounts_are_named_on_the_event():
    """A candidate shown a reduced score is owed the reason. An unexplained
    multiplier is exactly what reliability_factors exists to prevent."""
    assert _factors(_aggregate()) == {"aggregate_across_sources": 0.7, "open_bound": 0.85}


def test_the_verified_count_is_carried_in_the_payload():
    """The scoring engine gets Codeforces' own 412, not the asserted 500+."""
    payload = _aggregate().payload
    assert payload["independently_confirmed"] == [{"platform": "codeforces", "value": 412}]
    assert payload["value"] == 500
    assert payload["platforms_claimed"] == ["leetcode", "codeforces", "geeksforgeeks"]


def test_the_verified_count_also_stays_on_its_own_platform_event():
    """The strong signal keeps its own event; the claim only adds the remainder.
    The 412 is not being moved, and it is not being counted twice at weight."""
    rating = by_kind(project(full()), "platform_rating")[0]
    assert rating.payload["problems_solved"] == 412
    assert rating.reliability == 0.90
    assert _aggregate().reliability < 0.15


def test_a_precise_single_source_claim_is_not_discounted():
    report = full()
    for claim in report["claim_graph"]["claims"]:
        if claim["claim_id"] == "c24":
            claim["flags"] = []
            claim["context"] = {"platforms": ["codeforces"]}
    assert _factors(_aggregate(report)) == {}
    assert _aggregate(report).reliability == 0.20


def test_open_bound_alone_discounts_on_its_own():
    report = full()
    for claim in report["claim_graph"]["claims"]:
        if claim["claim_id"] == "c24":
            claim["flags"] = []
    assert _factors(_aggregate(report)) == {"open_bound": 0.85}


def test_unconfirmed_aggregate_carries_no_confirmation_block():
    """Nothing was verified, so nothing is asserted to have been."""
    report = full()
    for plat in report["evidence_bundle"]["platforms"]:
        plat["found"] = False
    payload = _aggregate(report).payload
    assert "independently_confirmed" not in payload
    assert _factors(_aggregate(report)) == {"aggregate_across_sources": 0.7, "open_bound": 0.85}


def test_a_platform_outside_the_claim_does_not_count_as_confirmation():
    """Confirmation must come from a platform the claim actually named."""
    report = full()
    for claim in report["claim_graph"]["claims"]:
        if claim["claim_id"] == "c24":
            claim["context"]["platforms"] = ["leetcode", "geeksforgeeks"]
    assert "independently_confirmed" not in _aggregate(report).payload


def test_discounts_are_reachable_from_the_contract(tmp=None):
    """Turning the discount off in YAML must turn it off in behaviour — nothing
    about this policy is compiled into the module."""
    raw = default_rules()._raw  # noqa: SLF001 - reading the loaded contract
    import copy
    edited = copy.deepcopy(raw)
    edited["thresholds"]["claim_discounts"] = {"flags": {}, "bounds": {}}
    assert Rules(edited).claim_discount_factors(["aggregate_across_sources"], "open") == ()
    assert default_rules().claim_discount_factors(["aggregate_across_sources"], "open") == \
        ("aggregate_across_sources", "open_bound")


def test_unknown_flags_are_ignored_rather_than_crashing():
    """M5 may add flags at any time; an unrecognised one must not break ingest."""
    assert default_rules().claim_discount_factors(["something_new"], "closed") == ()
    assert default_rules().claim_discount_factors(None, None) == ()
