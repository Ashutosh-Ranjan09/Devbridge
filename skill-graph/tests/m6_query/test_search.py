"""Search across a population — tiers, never a ranking."""
from query_fixtures import AS_OF, SUBJECT, population, service


def flatten(found):
    return [m.subject_ref for tier in found for m in tier.members]


def test_search_finds_everyone_above_a_low_bar():
    found = population().search("typescript", AS_OF, minimum=0.0)
    assert set(flatten(found)) == {SUBJECT, "subj_strong", "subj_thin", "subj_weak"}


def test_a_higher_bar_admits_fewer():
    svc = population()
    low = flatten(svc.search("typescript", AS_OF, minimum=0.0))
    high = flatten(svc.search("typescript", AS_OF, minimum=0.35))
    assert set(high) < set(low)


def test_definite_matching_is_stricter_than_possible_matching():
    """The caller's risk decision: 'confident they are above the bar' versus
    'they might be'. Both are legitimate; picking one silently is not."""
    svc = population()
    definite = flatten(svc.search("typescript", AS_OF, minimum=0.45, definite=True))
    possible = flatten(svc.search("typescript", AS_OF, minimum=0.45, definite=False))
    assert set(definite) <= set(possible)
    assert len(possible) > len(definite), "the threshold should separate the two readings"


def test_identical_evidence_lands_in_one_indistinguishable_tier():
    """subj_7a3f9e21 and subj_strong hold the same events under different ids.
    Separating them would be inventing a difference that does not exist."""
    found = population().search("typescript", AS_OF, minimum=0.0)
    together = [t for t in found if {SUBJECT, "subj_strong"} <= {m.subject_ref for m in t.members}]
    assert together, [t.to_dict() for t in found]
    assert together[0].to_dict()["indistinguishable"] is True


def test_a_thin_candidate_is_not_ranked_against_a_full_one_without_a_gap():
    """Wide intervals overlap, so the honest answer is 'cannot separate'."""
    found = population().search("typescript", AS_OF, minimum=0.0)
    for tier in found:
        refs = {m.subject_ref for m in tier.members}
        if {"subj_thin", "subj_strong"} <= refs:
            return                      # correctly grouped
    # If they did separate, the gap must be real.
    positions = {m.subject_ref: t.rank for t in found for m in t.members}
    assert positions["subj_thin"] != positions["subj_strong"]
    upper = next(m for t in found for m in t.members if m.subject_ref == "subj_strong")
    lower = next(m for t in found for m in t.members if m.subject_ref == "subj_thin")
    assert upper.definitely_above(lower) or lower.definitely_above(upper)


def test_tiers_are_numbered_from_one_and_contiguous():
    found = population().search("typescript", AS_OF, minimum=0.0)
    assert [t.rank for t in found] == list(range(1, len(found) + 1))


def test_nobody_appears_in_two_tiers():
    found = population().search("typescript", AS_OF, minimum=0.0)
    refs = flatten(found)
    assert len(refs) == len(set(refs))


def test_an_impossible_bar_returns_nothing_rather_than_a_best_effort():
    """No 'closest match' fallback. A search with no results is information."""
    assert population().search("typescript", AS_OF, minimum=0.99) == []


def test_a_skill_nobody_has_returns_nothing():
    assert population().search("haskell", AS_OF, minimum=0.0) == []


def test_the_prior_is_never_a_search_result():
    """A developer with no evidence for a skill must not surface just because
    the prior happens to sit above the threshold."""
    found = population().search("haskell", AS_OF, minimum=0.0)
    assert found == []


def test_inferred_candidates_are_excluded_by_default():
    """Searching for someone who can do X should not return people we merely
    infer might be able to. Opt in explicitly."""
    svc = population()
    default = flatten(svc.search("c", AS_OF, minimum=0.0))
    opted_in = flatten(svc.search("c", AS_OF, minimum=0.0, include_inferred=True))
    assert default == []
    assert opted_in


def test_an_inferred_result_declares_its_source():
    found = population().search("c", AS_OF, minimum=0.0, include_inferred=True)
    for tier in found:
        for member in tier.members:
            assert member.is_inferred
            assert member.propagated_from == "cpp"


def test_search_can_be_scoped_to_named_subjects():
    found = population().search("typescript", AS_OF, subjects=["subj_thin"])
    assert flatten(found) == ["subj_thin"]


def test_search_ignores_a_subject_with_no_evidence_at_all():
    found = population().search("typescript", AS_OF, subjects=["subj_nobody", "subj_thin"])
    assert flatten(found) == ["subj_thin"]


def test_search_at_a_past_date_uses_only_evidence_from_then():
    from datetime import date
    svc = population()
    early = flatten(svc.search("typescript", date(2025, 5, 1), minimum=0.3))
    late = flatten(svc.search("typescript", AS_OF, minimum=0.3))
    assert len(early) <= len(late)


def test_search_results_are_deterministic():
    svc = population()
    a = [t.to_dict() for t in svc.search("typescript", AS_OF, minimum=0.0)]
    b = [t.to_dict() for t in svc.search("typescript", AS_OF, minimum=0.0)]
    assert a == b


def test_a_single_subject_log_still_tiers_correctly():
    found = service().search("typescript", AS_OF, minimum=0.0)
    assert len(found) == 1 and len(found[0].members) == 1
    assert found[0].to_dict()["indistinguishable"] is False


def test_the_current_intervals_are_too_wide_to_separate_this_population():
    """A real property of the system as configured, pinned deliberately.

    Four candidates — full evidence, thin evidence, and evidence at a THIRD of
    the reliability — all land in one indistinguishable tier for typescript. The
    constraint is working exactly as designed: on this much evidence the system
    genuinely cannot rank them, and it says so instead of inventing an order.

    The practical consequence is that search is currently a FILTER, not a
    ranker. If separating candidates is wanted, the lever is z (display.z, swept
    0.5-2.0), not the tiering rule. This test exists so that lowering z is a
    deliberate decision that breaks a test, rather than a quiet drift.
    """
    found = population().search("typescript", AS_OF, minimum=0.0)
    assert len(found) == 1, "the population separated; z or the evidence changed"
    assert len(found[0].members) == 4


def test_low_reliability_barely_moves_the_estimate():
    """Why the population above is indistinguishable, stated precisely.

    subj_weak carries the SAME evidence at a third of the reliability, and its
    estimate sits within 0.05 of subj_strong. That is correct: reliability
    governs how confident the filter is, not where it lands. Only a different
    observed VALUE moves the estimate. Anyone expecting reliability alone to
    separate candidates is expecting the wrong thing from the model.
    """
    svc = population()
    strong = {v.skill_id: v for v in svc.skills("subj_strong", AS_OF)}["typescript"]
    weak = {v.skill_id: v for v in svc.skills("subj_weak", AS_OF)}["typescript"]
    assert weak.mean < strong.mean
    assert abs(strong.mean - weak.mean) < 0.05
    assert (weak.upper - weak.lower) > (strong.upper - strong.lower), \
        "lower reliability must show up as a WIDER interval"


def _two_candidate_service(z=None):
    """The golden subject against one whose repositories are all trivial —
    a real difference in the evidence, worth about 0.10 of mean ability."""
    from query_fixtures import batch, log_with, relabelled, service as make_service
    log = log_with(batch(), relabelled("subj_novice", downgrade=True))
    if z is None:
        return make_service(log)
    from m6_ontology import default_ontology
    from m6_scoring import ScoringEngine
    from m6_scoring.params import default_parameters
    from m6_query import QueryService
    ontology = default_ontology()
    return QueryService(log, ScoringEngine(
        default_parameters().replacing(display__z=z), ontology=ontology),
        ontology=ontology)


def test_even_a_real_difference_in_ability_does_not_separate_at_z_equals_one():
    """The finding that matters most about search, pinned so it cannot drift.

    subj_novice's repositories are trivial rather than substantial — a genuine
    difference in the evidence, worth about 0.10 of estimated ability. At the
    contract's z=1 the intervals STILL overlap, so the two are reported as
    indistinguishable.

    This is not a bug in the tiering rule. It is what "only definite interval
    overlap" costs: at z=1 the bands are wide relative to the differences this
    evidence produces, so search is a FILTER, not a ranker. Anyone wanting it to
    rank has to argue for a lower z and accept the false precision that buys.
    """
    svc = _two_candidate_service()
    strong = {v.skill_id: v for v in svc.skills(SUBJECT, AS_OF)}["typescript"]
    novice = {v.skill_id: v for v in svc.skills("subj_novice", AS_OF)}["typescript"]
    assert strong.mean - novice.mean > 0.08, "the fixture no longer differs meaningfully"

    found = svc.search("typescript", AS_OF, minimum=0.0)
    assert len(found) == 1 and len(found[0].members) == 2


def test_the_same_pair_separates_once_the_bands_are_narrow_enough():
    """The tiering rule can separate people; width is what currently prevents
    it. Measured threshold: this pair separates at z <= 0.40 and not at 0.45.
    That number belongs in the sensitivity chapter, so it is asserted here."""
    assert len(_two_candidate_service(z=0.45).search("typescript", AS_OF)) == 1
    found = _two_candidate_service(z=0.40).search("typescript", AS_OF)
    assert len(found) == 2

    positions = {m.subject_ref: t.rank for t in found for m in t.members}
    assert positions[SUBJECT] < positions["subj_novice"]
    top = next(m for t in found for m in t.members if m.subject_ref == SUBJECT)
    bottom = next(m for t in found for m in t.members if m.subject_ref == "subj_novice")
    assert top.definitely_above(bottom), "the split was not justified by a real gap"
