"""Each check fires when it should and stays quiet when it should not.

A detector that fires on everything is as useless as one that never fires, so
every test below has a negative twin.
"""
from datetime import date, timedelta

from integrity_fixtures import AS_OF, analyse, codes, event, loaded, only, rules_without


# ── EVIDENCE_BURST ──────────────────────────────────────────────────────────
def test_burst_fires_when_most_evidence_is_recent():
    events = [event(event_id=f"ev_{i}", occurred_at="2026-08-10") for i in range(5)]
    f = only(analyse(events), "EVIDENCE_BURST")
    assert f.severity == "attention"
    assert f.metrics["events_in_window"] == 5 and f.metrics["share"] == 1.0


def test_burst_stays_quiet_for_evidence_spread_over_years():
    events = [event(event_id=f"ev_{i}", occurred_at=f"202{i}-03-01") for i in range(1, 6)]
    assert "EVIDENCE_BURST" not in codes(analyse(events))


def test_burst_needs_enough_events_to_be_a_pattern():
    """Two recent events is a coincidence, not a burst."""
    events = [event(event_id=f"ev_{i}", occurred_at="2026-08-10") for i in range(2)]
    assert "EVIDENCE_BURST" not in codes(analyse(events))


def test_burst_carries_the_events_it_is_about():
    events = [event(event_id=f"ev_{i}", occurred_at="2026-08-10") for i in range(5)]
    f = only(analyse(events), "EVIDENCE_BURST")
    assert set(f.event_ids) == {f"ev_{i}" for i in range(5)}


# ── OWNERSHIP_UNPROVEN ──────────────────────────────────────────────────────
def test_ownership_fires_when_most_evidence_is_capped():
    events = [event(event_id=f"ev_{i}", factors=("ownership_unverified",))
              for i in range(4)]
    f = only(analyse(events), "OWNERSHIP_UNPROVEN")
    assert f.severity == "attention" and f.metrics["capped_events"] == 4


def test_ownership_stays_quiet_when_the_account_is_proven():
    assert "OWNERSHIP_UNPROVEN" not in codes(
        analyse([event(event_id=f"ev_{i}") for i in range(4)]))


def test_ownership_fires_on_the_golden_report():
    """Its GitHub account is unverified, and most of its evidence is GitHub."""
    with loaded() as m6:
        assert "OWNERSHIP_UNPROVEN" in codes(m6.integrity("subj_7a3f9e21", AS_OF))


# ── SINGLE_SOURCE ───────────────────────────────────────────────────────────
def test_single_source_fires_when_nothing_corroborates():
    events = [event(event_id="ev_1", origin="github_api"),
              event(event_id="ev_2", origin="github_api")]
    f = only(analyse(events), "SINGLE_SOURCE")
    assert f.metrics["origin"] == "github_api" and f.skills == ("python",)


def test_single_source_stays_quiet_with_two_independent_origins():
    events = [event(event_id="ev_1", origin="github_api"),
              event(event_id="ev_2", origin="codeforces_api")]
    assert "SINGLE_SOURCE" not in codes(analyse(events))


def test_a_lone_event_is_not_a_single_source_finding():
    """One event is obviously from one place; saying so adds nothing."""
    assert "SINGLE_SOURCE" not in codes(analyse([event()]))


# ── CLAIM_ONLY ──────────────────────────────────────────────────────────────
def test_claim_only_fires_for_a_wholly_self_reported_skill():
    f = only(analyse([event(kind="cv_claim", event_id="ev_1")]), "CLAIM_ONLY")
    assert f.skills == ("python",)


def test_claim_only_stays_quiet_when_anything_is_verified():
    events = [event(kind="cv_claim", event_id="ev_1"),
              event(kind="repo_artifact", event_id="ev_2")]
    assert "CLAIM_ONLY" not in codes(analyse(events))


# ── CONTRADICTED ────────────────────────────────────────────────────────────
def test_contradicted_fires_on_evidence_pointing_both_ways():
    events = [event(event_id="ev_1"),
              event(event_id="ev_2", kind="claim_contradicted", direction="negative")]
    f = only(analyse(events), "CONTRADICTED")
    assert f.severity == "attention"
    assert f.metrics == {"supporting": 1, "contradicting": 1}


def test_contradicted_stays_quiet_when_everything_agrees():
    assert "CONTRADICTED" not in codes(
        analyse([event(event_id="ev_1"), event(event_id="ev_2")]))


# ── WHOLLY_STALE ────────────────────────────────────────────────────────────
def test_wholly_stale_fires_past_the_half_life():
    with loaded() as m6:
        events = [event(event_id="ev_1", skills=("mongodb",), occurred_at="2024-01-01")]
        f = only(analyse(events, engine=m6.engine), "WHOLLY_STALE")
        assert f.metrics["half_life_days"] == 467 and f.metrics["tier"] == "framework"


def test_wholly_stale_stays_quiet_for_fresh_evidence():
    with loaded() as m6:
        events = [event(event_id="ev_1", skills=("mongodb",), occurred_at="2026-08-01")]
        assert "WHOLLY_STALE" not in codes(analyse(events, engine=m6.engine))


def test_a_fundamental_tolerates_far_more_age_than_a_framework():
    """Same date, different tier, different verdict — the check reads the skill's
    own half-life rather than one global threshold."""
    with loaded() as m6:
        old = "2024-01-01"
        framework = analyse([event(event_id="e1", skills=("mongodb",), occurred_at=old)],
                            engine=m6.engine)
        fundamental = analyse([event(event_id="e2", skills=("algorithms",), occurred_at=old)],
                              engine=m6.engine)
        assert "WHOLLY_STALE" in codes(framework)
        assert "WHOLLY_STALE" not in codes(fundamental)


def test_staleness_is_skipped_without_an_engine():
    """The check needs half-lives; without them it abstains rather than guessing."""
    assert "WHOLLY_STALE" not in codes(
        analyse([event(occurred_at="2020-01-01")], engine=None))


# ── BREADTH_FROM_ONE_ARTEFACT ───────────────────────────────────────────────
def test_breadth_fires_when_one_artefact_carries_many_skills():
    wide = event(event_id="ev_wide",
                 skills=("python", "django", "postgresql", "docker", "redis", "nginx"))
    f = only(analyse([wide]), "BREADTH_FROM_ONE_ARTEFACT")
    assert f.metrics["skill_count"] == 6 and f.event_ids == ("ev_wide",)


def test_breadth_stays_quiet_for_a_focused_artefact():
    assert "BREADTH_FROM_ONE_ARTEFACT" not in codes(
        analyse([event(skills=("python", "numpy"))]))


# ── QUARANTINED_EVIDENCE ────────────────────────────────────────────────────
def test_quarantine_finding_names_the_unknown_skills():
    f = only(analyse([event()], quarantined={"ev_9": ["haskell", "prolog"]}),
             "QUARANTINED_EVIDENCE")
    assert f.skills == ("haskell", "prolog") and f.event_ids == ("ev_9",)


def test_quarantine_stays_quiet_when_everything_resolved():
    assert "QUARANTINED_EVIDENCE" not in codes(analyse([event()], quarantined={}))


# ── INFERRED_ONLY ───────────────────────────────────────────────────────────
def test_inferred_only_fires_for_a_propagated_skill():
    with loaded() as m6:
        report = m6.integrity("subj_7a3f9e21", AS_OF)
        inferred = [f for f in report.findings if f.check_id == "INFERRED_ONLY"]
        assert {f.skills[0] for f in inferred} >= {"c"}
        assert inferred[0].metrics["from_skill"] == "cpp"


# ── the contract governs the checks ─────────────────────────────────────────
def test_removing_a_check_from_the_contract_switches_it_off():
    """No threshold and no check lives in Python. Deleting it from the YAML must
    stop it running, not leave orphaned code firing."""
    events = [event(event_id=f"ev_{i}", occurred_at="2026-08-10") for i in range(5)]
    assert "EVIDENCE_BURST" in codes(analyse(events))
    assert "EVIDENCE_BURST" not in codes(
        analyse(events, rules=rules_without("EVIDENCE_BURST")))


def test_a_clean_graph_says_so_rather_than_returning_silence():
    report = analyse([event(event_id="ev_1", origin="github_api"),
                      event(event_id="ev_2", origin="codeforces_api",
                            skills=("algorithms",))])
    assert report.clean
    assert "Nothing to flag" in report.to_dict()["note"]
