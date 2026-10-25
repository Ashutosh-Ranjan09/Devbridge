"""Timestamp normalisation, repository↔claim attribution, and the credential
branch — the three places the fixtures could not reach on their own.
"""
from datetime import date, datetime, timedelta, timezone

from helpers import by_kind, credential, full, skills, with_credentials
from m6_projection import MalformedReport, project
from m6_projection.projector import _as_date, _links_repo, _repo_segment


def _repo_event(report, name):
    return next(e for e in by_kind(project(report), "repo_artifact")
                if e.payload.get("repo") == name)


def _with_last_commit(stamp):
    report = full()
    repo = report["evidence_bundle"]["github"]["repos"][0]
    repo["last_commit"] = stamp
    return _repo_event(report, repo["name"]).occurred_at


# ── timestamps ──────────────────────────────────────────────────────────────
def test_offset_timestamp_resolves_to_the_utc_day():
    """20:30 on the 1st at -08:00 is 04:30 on the 2nd in UTC. Truncating the
    string to ten characters would record the 1st."""
    assert _with_last_commit("2025-03-01T20:30:00-08:00") == date(2025, 3, 2)


def test_eastern_offset_that_rolls_backwards():
    """01:30 on the 2nd at +05:30 is 20:00 on the 1st in UTC."""
    assert _with_last_commit("2025-03-02T01:30:00+05:30") == date(2025, 3, 1)


def test_offset_that_does_not_cross_midnight_is_unchanged():
    assert _with_last_commit("2025-03-01T02:30:00-08:00") == date(2025, 3, 1)


def test_zulu_and_bare_date_agree():
    assert _with_last_commit("2025-03-01T09:00:00Z") == _with_last_commit("2025-03-01")


def test_bare_date_is_taken_as_given():
    """A date with no offset carries no instant to convert; inventing a timezone
    for it would shift dates that were already correct."""
    assert _as_date("2025-03-01") == date(2025, 3, 1)


def test_naive_datetime_is_read_as_utc():
    assert _as_date(datetime(2025, 3, 1, 23, 30)) == date(2025, 3, 1)


def test_aware_datetime_is_converted_to_its_utc_day():
    pacific = timezone(timedelta(hours=-8))
    assert _as_date(datetime(2025, 3, 1, 20, 30, tzinfo=pacific)) == date(2025, 3, 2)
    assert _as_date(datetime(2025, 3, 2, 4, 30, tzinfo=timezone.utc)) == date(2025, 3, 2)


def test_fractional_seconds_are_accepted():
    assert _as_date("2025-03-01T09:00:00.123456Z") == date(2025, 3, 1)


def test_unreadable_timestamp_is_reported_not_guessed():
    for bad in ("last tuesday", "2025-13-45", "", "2025-03-01T99:00:00Z"):
        try:
            _as_date(bad)
        except MalformedReport:
            continue
        raise AssertionError(f"{bad!r} was accepted as a date")


# ── repository ↔ claim attribution ──────────────────────────────────────────
def test_repo_segment_extraction():
    assert _repo_segment("https://github.com/dev/ATMA-Final") == "atma-final"
    assert _repo_segment("https://github.com/dev/ATMA-Final/") == "atma-final"
    assert _repo_segment("https://github.com/dev/ATMA-Final.git") == "atma-final"
    assert _repo_segment("https://atma-rs.vercel.app") == ""
    assert _repo_segment(None) == ""


def test_a_prefix_named_repo_is_not_attributed_to_its_neighbours_claim():
    """A repository called `ATMA` must not inherit the claim about `ATMA-Final`.
    claim_refs is the audit trail shown to a recruiter; a wrong one is a wrong
    explanation, which in a system with no overall score is the whole product."""
    report = full()
    repos = report["evidence_bundle"]["github"]["repos"]
    decoy = dict(repos[0], name="ATMA", commit_count=5)
    repos.append(decoy)

    assert _repo_event(report, "ATMA").source.claim_refs == ()
    assert _repo_event(report, "ATMA-Final").source.claim_refs == ("c07",)


def test_attribution_is_case_insensitive():
    report = full()
    repo = report["evidence_bundle"]["github"]["repos"][0]
    repo["name"] = repo["name"].upper()
    assert _repo_event(report, repo["name"]).source.claim_refs == ("c07",)


def test_links_repo_is_exact_not_substring():
    claim = {"artefacts": [{"url": "https://github.com/dev/ATMA-Final"}]}
    assert _links_repo(claim, "ATMA-Final")
    assert not _links_repo(claim, "ATMA")
    assert not _links_repo(claim, "Final")
    assert not _links_repo({"artefacts": []}, "ATMA-Final")


# ── credentials ─────────────────────────────────────────────────────────────
def test_verified_credential_becomes_an_event():
    batch = project(with_credentials(full(), credential()))
    events = by_kind(batch, "credential_verified")
    assert len(events) == 1
    assert skills(events[0]) == {"aws": 1.0, "cloud_architecture": 1.0}
    assert events[0].occurred_at == date(2025, 2, 11)
    assert events[0].payload["issuer"] == "Amazon Web Services"


def test_unverified_credential_is_not_an_event():
    """M5 could not confirm it with the issuer, so it carries no weight here."""
    batch = project(with_credentials(full(), credential(verified=False)))
    assert by_kind(batch, "credential_verified") == []


def test_credential_without_skills_is_quarantined_not_dropped():
    batch = project(with_credentials(full(), credential(skill_refs=[])))
    assert by_kind(batch, "credential_verified") == []
    assert any("credential_verified" in q for q in batch.quarantined), batch.quarantined


def test_credential_without_an_issue_date_falls_back_to_gathered_at():
    batch = project(with_credentials(full(), credential(issued_at=None)))
    event = by_kind(batch, "credential_verified")[0]
    assert event.occurred_at == date(2026, 8, 24)


def test_credential_skill_names_go_through_the_alias_table():
    batch = project(with_credentials(full(), credential(skill_refs=["Mongoose"])))
    assert skills(by_kind(batch, "credential_verified")[0]) == {"mongodb": 1.0}


# ── platforms M5 could not resolve ──────────────────────────────────────────
def test_platform_not_found_emits_nothing():
    report = full()
    for plat in report["evidence_bundle"]["platforms"]:
        plat["found"] = False
    assert by_kind(project(report), "platform_rating") == []


def test_platform_found_but_unrated_emits_nothing():
    """A resolved handle with no rating is not evidence of rating — an absent
    number must not be read as a low one."""
    report = full()
    for plat in report["evidence_bundle"]["platforms"]:
        plat["max_rating"] = None
    assert by_kind(project(report), "platform_rating") == []


def test_unrated_platform_releases_its_achievement_claims():
    """The achievement is only skipped when a platform_rating already carries
    it. With no rating event, the CV claim must still reach the graph."""
    report = full()
    for plat in report["evidence_bundle"]["platforms"]:
        plat["max_rating"] = None
    payloads = [e.payload for e in by_kind(project(report), "cv_claim")]
    assert any("metric" in p for p in payloads), "achievement claims vanished entirely"


# ── when a CV claim is dated ────────────────────────────────────────────────
def test_cv_claims_are_dated_at_the_document_not_the_verification():
    """The weakest evidence in the system must not get the freshest date. A CV
    written in July 2025 and verified in August 2026 carries 13 months of decay,
    not none."""
    batch = project(full())
    for event in by_kind(batch, "cv_claim"):
        assert event.occurred_at == date(2025, 7, 4), event.event_id
    assert batch.emitted_at == date(2026, 8, 24)


def test_document_date_is_normalised_to_utc():
    """The fixture's created_at is +05:30; the UTC day is what gets recorded."""
    report = full()
    report["document"]["created_at"] = "2025-07-05T02:30:00+05:30"  # 2025-07-04T21:00Z
    assert by_kind(project(report), "cv_claim")[0].occurred_at == date(2025, 7, 4)


def test_missing_document_date_falls_back_to_valid_as_of():
    report = full()
    report["document"].pop("created_at")
    assert by_kind(project(report), "cv_claim")[0].occurred_at == date(2026, 8, 24)


def test_corroborated_claims_keep_the_repository_date():
    """Corroboration is dated by the evidence, not by the document — the commit
    is what happened, and it happened when GitHub says it did."""
    for event in by_kind(project(full()), "claim_corroborated"):
        assert event.occurred_at == date(2025, 6, 19)
