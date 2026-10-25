"""The skills endpoint and the explain endpoint.

The plan calls explain the demo and says to build it as a first-class
deliverable, so it is tested as one: not merely "does it return", but does it
say enough for a reader to disagree with the number.
"""
from datetime import date, timedelta

from query_fixtures import AS_OF, SUBJECT, population, raises, service
from m6_query import UnknownSkill, UnknownSubject


# ── the graph ───────────────────────────────────────────────────────────────
def test_skills_returns_every_skill_with_an_interval():
    views = service().skills(SUBJECT, AS_OF)
    assert views
    for v in views:
        assert v.lower < v.upper, v.skill_id
        assert v.lower <= v.mean <= v.upper


def test_skills_are_ordered_by_lower_bound():
    views = service().skills(SUBJECT, AS_OF)
    assert [v.lower for v in views] == sorted((v.lower for v in views), reverse=True)


def test_the_published_skills_are_present_with_the_published_numbers():
    views = {v.skill_id: v for v in service().skills(SUBJECT, AS_OF)}
    for skill, published in (("algorithms", 0.533), ("typescript", 0.381),
                             ("python", 0.189)):
        assert abs(views[skill].lower - published) < 0.01, skill


def test_an_unknown_subject_is_a_distinct_failure():
    """Not the same as a developer with a low score. Conflating the two would
    let an empty graph read as a negative assessment."""
    raises(UnknownSubject, service().skills, "subj_nobody", AS_OF)


def test_inferred_skills_can_be_excluded():
    with_inferred = service().skills(SUBJECT, AS_OF, include_inferred=True)
    without = service().skills(SUBJECT, AS_OF, include_inferred=False)
    assert len(without) < len(with_inferred)
    assert all(v.evidence_count > 0 for v in without)


def test_propagation_can_be_turned_off():
    on = service().skills(SUBJECT, AS_OF, propagate=True)
    off = service().skills(SUBJECT, AS_OF, propagate=False)
    assert {v.skill_id for v in off} < {v.skill_id for v in on}
    assert all(v.propagated is None for v in off)


def test_a_minimum_evidence_filter_narrows_the_graph():
    strict = service().skills(SUBJECT, AS_OF, min_evidence=2)
    assert strict and all(v.evidence_count >= 2 for v in strict)


def test_an_inferred_skill_is_labelled_as_such():
    views = {v.skill_id: v for v in service().skills(SUBJECT, AS_OF)}
    assert views["c"].inferred
    assert views["c"].propagated["from_skill_id"] == "cpp"
    assert not views["typescript"].inferred


# ── as_of ───────────────────────────────────────────────────────────────────
def test_as_of_in_the_past_sees_less_evidence():
    early = service().skills(SUBJECT, date(2025, 1, 1), propagate=False)
    late = service().skills(SUBJECT, AS_OF, propagate=False)
    assert sum(v.evidence_count for v in early) < sum(v.evidence_count for v in late)


def test_as_of_in_the_future_widens_every_interval():
    """No new evidence means less confidence, never more."""
    now = {v.skill_id: v for v in service().skills(SUBJECT, AS_OF, propagate=False)}
    later = {v.skill_id: v for v in
             service().skills(SUBJECT, AS_OF + timedelta(days=1000), propagate=False)}
    for skill, view in now.items():
        assert (later[skill].upper - later[skill].lower) > (view.upper - view.lower), skill


def test_staleness_is_reported_per_skill():
    views = {v.skill_id: v for v in service().skills(SUBJECT, AS_OF)}
    assert views["python"].days_since_newest_evidence == (AS_OF - date(2024, 6, 28)).days


# ── explain, the demo ───────────────────────────────────────────────────────
def test_explain_names_every_contributing_event():
    got = service().explain(SUBJECT, "typescript", AS_OF)
    assert got["evidence_count"] == 3
    assert len(got["contributions"]) == 3
    for c in got["contributions"]:
        for field in ("event_id", "kind", "occurred_at", "observed", "relevance", "weight"):
            assert field in c, field


def test_explain_shows_the_interval_and_the_basis():
    got = service().explain(SUBJECT, "typescript", AS_OF)
    assert got["basis"] == "direct_evidence"
    assert got["interval"][0] < got["interval"][1]
    assert got["interval"][0] == got["score"], "the published score IS the lower bound"


def test_explain_shows_the_decay_story():
    """A reader must be able to see that a score fell because the evidence aged,
    not because anyone judged the person harshly."""
    got = service().explain(SUBJECT, "python", AS_OF)
    assert got["days_since_newest_evidence"] > 700
    assert got["half_life_days"] == 1167
    assert got["volatility_tier"] if "volatility_tier" in got else got["tier"]


def test_explain_reports_what_was_not_counted():
    """The projection records suppressions; surfacing them here is what lets a
    candidate see a claim was read and rejected rather than never noticed."""
    reasons = {r["reason"] for r in service().explain(SUBJECT, "typescript", AS_OF)["not_counted"]}
    assert "not_a_capability_signal" in reasons
    assert "institution_disclaimed" in reasons


def test_explain_works_for_a_propagated_skill_and_says_so():
    got = service().explain(SUBJECT, "c", AS_OF)
    assert got["basis"] == "propagated"
    assert got["evidence_count"] == 0
    assert got["propagated"]["from_skill_id"] == "cpp"
    assert got["contributions"] == [], "an inference has no contributing events of its own"


def test_explain_refuses_a_skill_with_no_evidence_and_no_path():
    exc = raises(UnknownSkill, service().explain, SUBJECT, "haskell", AS_OF)
    assert "known here" in str(exc), "the error should say what IS available"


def test_explain_refuses_an_unknown_subject():
    raises(UnknownSubject, service().explain, "subj_nobody", "python", AS_OF)


def test_explain_at_a_past_date_reflects_that_date():
    early = service().explain(SUBJECT, "typescript", date(2025, 5, 1))
    late = service().explain(SUBJECT, "typescript", AS_OF)
    assert early["evidence_count"] < late["evidence_count"]
    assert early["as_of"] == "2025-05-01"


def test_contribution_weights_are_gains_between_zero_and_one():
    for c in service().explain(SUBJECT, "typescript", AS_OF)["contributions"]:
        assert 0.0 <= c["weight"] <= 1.0


def test_the_first_event_carries_the_most_weight():
    """Against a wide prior the first observation moves the estimate furthest.
    A reader seeing later events weighted higher would be right to distrust it."""
    weights = [c["weight"] for c in service().explain(SUBJECT, "typescript", AS_OF)["contributions"]]
    assert weights[0] == max(weights)


# ── the population ──────────────────────────────────────────────────────────
def test_subjects_lists_everyone_with_evidence():
    assert set(population().subjects()) == {
        SUBJECT, "subj_strong", "subj_thin", "subj_weak"}


def test_thin_evidence_gives_a_wider_interval_than_full_evidence():
    svc = population()
    full = {v.skill_id: v for v in svc.skills("subj_strong", AS_OF)}
    thin = {v.skill_id: v for v in svc.skills("subj_thin", AS_OF)}
    shared = set(full) & set(thin)
    assert shared
    widths = [(thin[s].upper - thin[s].lower) - (full[s].upper - full[s].lower)
              for s in shared if thin[s].evidence_count < full[s].evidence_count]
    assert widths and all(w > 0 for w in widths)


def test_low_reliability_evidence_moves_the_score_less():
    svc = population()
    strong = {v.skill_id: v for v in svc.skills("subj_strong", AS_OF)}
    weak = {v.skill_id: v for v in svc.skills("subj_weak", AS_OF)}
    assert weak["typescript"].mean < strong["typescript"].mean


def test_a_wholly_quarantined_skill_never_reaches_a_score():
    """The ingestor holds unknown skills out of scoring; the read path has to
    honour that. Folding every event instead of the log's filtered read let a
    quarantined skill appear with a score and an evidence count — the quarantine
    was decorative."""
    from query_fixtures import batch, log_with, service as make_service
    doc = batch()
    doc["events"][0]["skill_refs"] = [{"skill_id": "quantum_telepathy", "relevance": 0.9}]
    svc = make_service(log_with(doc))
    assert "quantum_telepathy" not in {v.skill_id for v in svc.skills(SUBJECT, AS_OF)}


def test_a_partly_quarantined_event_still_counts_for_its_known_skills():
    """Quarantine is per (event, skill). One unknown skill must not discard the
    event's evidence for the skills that resolved."""
    from query_fixtures import batch, log_with, service as make_service
    doc = batch()
    doc["events"][0]["skill_refs"] = [{"skill_id": "python", "relevance": 0.9},
                                      {"skill_id": "quantum_telepathy", "relevance": 0.5}]
    views = {v.skill_id: v for v in make_service(log_with(doc)).skills(SUBJECT, AS_OF)}
    assert "quantum_telepathy" not in views
    assert views["python"].evidence_count == 1


def test_one_subjects_evidence_never_folds_into_anothers():
    """A per-skill read that forgets to filter by subject silently merges every
    developer's evidence into every developer's score."""
    svc = population()
    thin = {v.skill_id: v for v in svc.skills("subj_thin", AS_OF)}
    strong = {v.skill_id: v for v in svc.skills("subj_strong", AS_OF)}
    assert thin["typescript"].evidence_count < strong["typescript"].evidence_count
