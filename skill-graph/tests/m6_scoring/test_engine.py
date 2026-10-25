"""Recompute-from-log, SkillState, ablation, and the explain response.

O4: state is a derived cache, never a source of truth. Deleting every SkillState
must lose nothing, and that property is what makes as_of queries, ablation and
the sweep cheap — each is just another fold.
"""
from datetime import date, timedelta

from scoring_fixtures import (AS_OF, engine, event, events, raises, validate_state)
from m6_scoring import ParameterMismatch


def test_folding_no_evidence_gives_the_prior_and_says_so():
    st = engine().fold([], "python", AS_OF)
    assert st.evidence_count == 0 and st.is_prior_only
    assert abs(st.state.mean - 0.25) < 1e-9
    assert st.newest_evidence_at is None


def test_a_skill_nobody_mentioned_is_prior_only():
    assert engine().fold(events(), "rust", AS_OF).is_prior_only


def test_the_fold_uses_only_events_naming_the_skill():
    st = engine().fold(events(), "mongodb", AS_OF)
    assert st.evidence_count == 1
    assert len(st.event_ids) == 1


def test_state_conforms_to_the_committed_schema():
    for skill in ("typescript", "python", "rust"):
        validate_state(engine().fold(events(), skill, AS_OF, subject_ref="subj_7a3f9e21"))


def test_provenance_lists_every_event_folded_in():
    """Makes the score decomposable and any single source ablatable."""
    st = engine().fold(events(), "typescript", AS_OF)
    assert len(st.event_ids) == st.evidence_count == 3
    assert len(set(st.event_ids)) == len(st.event_ids)


def test_the_fold_is_deterministic_regardless_of_input_order():
    evs = events()
    forward = engine().fold(evs, "typescript", AS_OF)
    backward = engine().fold(list(reversed(evs)), "typescript", AS_OF)
    assert abs(forward.state.mu - backward.state.mu) < 1e-12
    assert forward.event_ids == backward.event_ids


def test_events_after_as_of_are_excluded():
    """as_of queries are how the report shows the graph at a past date. An event
    from the future leaking in would make those meaningless."""
    early = engine().fold(events(), "typescript", date(2025, 1, 1))
    late = engine().fold(events(), "typescript", AS_OF)
    assert early.evidence_count < late.evidence_count


def test_as_of_before_all_evidence_is_the_prior():
    assert engine().fold(events(), "typescript", date(2020, 1, 1)).is_prior_only


def test_a_later_as_of_widens_the_band_without_new_evidence():
    eng = engine()
    now = eng.fold(events(), "python", AS_OF)
    later = eng.fold(events(), "python", AS_OF + timedelta(days=1000))
    assert later.state.var > now.state.var
    assert later.state.score(1.0) < now.state.score(1.0)
    assert later.evidence_count == now.evidence_count


def test_newest_evidence_is_recorded_for_the_staleness_display():
    st = engine().fold(events(), "python", AS_OF)
    assert str(st.newest_evidence_at) == "2024-06-28"


def test_fold_all_covers_every_skill_any_event_mentions():
    evs = events()
    mentioned = {r["skill_id"] for e in evs for r in e["skill_refs"]}
    assert set(engine().fold_all(evs, AS_OF)) == mentioned


def test_more_and_better_evidence_scores_higher():
    """The ordering is the product. A skill with three corroborating events must
    outrank one resting on a single weak claim."""
    eng = engine()
    strong = eng.fold(events(), "typescript", AS_OF).state.score(1.0)
    weak = eng.fold(events(), "mongodb", AS_OF).state.score(1.0)
    assert strong > weak


# ── ablation ────────────────────────────────────────────────────────────────
def test_ablating_a_source_lowers_the_score_it_supported():
    """The report's per-source ablation table is this function in a loop."""
    eng = engine()
    evs = events()
    full = eng.fold(evs, "typescript", AS_OF).state.score(1.0)
    without_github = eng.fold_without(evs, "typescript", AS_OF, origin="github_api")
    assert without_github.state.score(1.0) < full
    assert without_github.evidence_count < 3


def test_ablating_an_irrelevant_source_changes_nothing():
    eng = engine()
    evs = events()
    full = eng.fold(evs, "mongodb", AS_OF)
    same = eng.fold_without(evs, "mongodb", AS_OF, origin="codeforces_api")
    assert abs(full.state.mu - same.state.mu) < 1e-12


def test_ablating_every_source_returns_the_prior():
    eng = engine()
    ablated = eng.fold_without(events(), "python", AS_OF, origin="github_api")
    assert ablated.is_prior_only


def test_ablation_by_kind_works_too():
    eng = engine()
    evs = events()
    without_claims = eng.fold_without(evs, "cpp", AS_OF, kind="cv_claim")
    assert without_claims.evidence_count < eng.fold(evs, "cpp", AS_OF).evidence_count


# ── persistence round trip ──────────────────────────────────────────────────
def test_a_state_survives_a_round_trip_through_its_document():
    eng = engine()
    original = eng.fold(events(), "typescript", AS_OF, subject_ref="subj_x")
    back = eng.rehydrate(original.to_dict())
    assert abs(back.state.mu - original.state.mu) < 1e-6
    assert abs(back.state.var - original.state.var) < 1e-6
    assert back.tier == original.tier and back.event_ids == original.event_ids


def test_rehydrating_can_decay_to_a_later_date():
    """This is the cheap read path: decay a cached state instead of re-folding."""
    eng = engine()
    stored = eng.fold(events(), "python", AS_OF, subject_ref="s").to_dict()
    later = AS_OF + timedelta(days=500)
    assert eng.rehydrate(stored, as_of=later).state.var > eng.rehydrate(stored).state.var


def test_the_cheap_read_path_agrees_with_a_full_refold():
    """If decaying a cached state disagreed with re-folding the log, the cache
    would not be a cache — it would be a second, quietly different answer."""
    eng = engine()
    later = AS_OF + timedelta(days=400)
    cached = eng.rehydrate(eng.fold(events(), "python", AS_OF, subject_ref="s").to_dict(),
                           as_of=later)
    refolded = eng.fold(events(), "python", later)
    assert abs(cached.state.mu - refolded.state.mu) < 1e-5
    assert abs(cached.state.var - refolded.state.var) < 1e-5


def test_a_state_from_another_parameter_version_is_refused():
    """States are a derived cache, so the fix is always to recompute. Mixing two
    parameter sets makes the ordering between skills meaningless."""
    eng = engine()
    stored = eng.fold(events(), "python", AS_OF, subject_ref="s").to_dict()
    stored["provenance"]["parameter_version"] = "0.9.0"
    exc = raises(ParameterMismatch, eng.rehydrate, stored)
    assert "recompute" in str(exc)


# ── explain ─────────────────────────────────────────────────────────────────
def test_explain_matches_the_published_response_shape():
    got = engine().explain(engine().fold(events(), "typescript", AS_OF), AS_OF)
    for field in ("skill", "score", "mean", "sigma", "sigma_logit", "tier",
                  "evidence_count", "days_since_newest_evidence", "contributions"):
        assert field in got, field


def test_sigma_in_explain_is_the_display_band_not_the_logit_state():
    """This is what reconciles the published numbers — mean - score, not the
    state's own standard deviation."""
    got = engine().explain(engine().fold(events(), "typescript", AS_OF), AS_OF)
    assert abs(got["mean"] - got["score"] - got["sigma"]) < 0.002
    assert got["sigma"] != got["sigma_logit"]


def test_explain_names_every_contributing_event_with_its_weight():
    got = engine().explain(engine().fold(events(), "typescript", AS_OF), AS_OF)
    assert len(got["contributions"]) == 3
    for c in got["contributions"]:
        assert 0.0 <= c["weight"] <= 1.0
        assert c["event_id"] and c["kind"]


def test_contributions_are_in_fold_order():
    got = engine().explain(engine().fold(events(), "typescript", AS_OF), AS_OF)
    stamps = [c["occurred_at"] for c in got["contributions"]]
    assert stamps == sorted(stamps)


def test_explain_says_when_a_score_is_only_the_prior():
    """The query API must not report a prior as though it were measured."""
    got = engine().explain(engine().fold(events(), "rust", AS_OF), AS_OF)
    assert got["prior_only"] is True and got["evidence_count"] == 0
    assert got["days_since_newest_evidence"] is None


def test_explain_reports_staleness_and_half_life():
    got = engine().explain(engine().fold(events(), "python", AS_OF), AS_OF)
    assert got["days_since_newest_evidence"] == (AS_OF - date(2024, 6, 28)).days
    assert got["half_life_days"] == 1167          # ecosystem


def test_an_unscoreable_event_stops_the_fold_rather_than_being_skipped():
    """A silently skipped event is a score nobody can explain."""
    from m6_scoring import UnscoreableEvent
    bad = event("telepathy", skill="python", occurred_at="2025-02-02")
    raises(UnscoreableEvent, engine().fold, events() + [bad], "python", AS_OF)
