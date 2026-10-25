"""What the projection decides, given particular evidence. One behaviour per test."""
from helpers import by_kind, full, repo, skills, with_github
from m6_projection import project


# ── ownership asymmetry ──────────────────────────────────────────────────────

def test_unverified_ownership_caps_repo_evidence():
    for e in by_kind(project(full()), "repo_artifact"):
        assert e.reliability_base == 0.70
        assert e.reliability == 0.42
        assert [f.factor for f in e.reliability_factors] == ["ownership_unverified"]


def test_verified_ownership_removes_the_cap_entirely():
    report = with_github(full(), ownership="verified_oauth")
    for e in by_kind(project(report), "repo_artifact"):
        assert e.reliability == 0.70
        assert e.reliability_factors == ()
    assert not any(s.reason == "non_scoring_rule" for s in project(report).not_emitted)


# ── repositories ─────────────────────────────────────────────────────────────

def test_forks_and_shells_are_suppressed_not_scored():
    report = with_github(full(), repos=[
        repo(name="real"), repo(name="a-fork", is_fork=True),
        repo(name="a-shell", is_readme_only=True), repo(name="not-mine", owner_matches=False)])
    batch = project(report)
    assert [e.payload["repo"] for e in by_kind(batch, "repo_artifact")] == ["real"]
    suppressed = [s.what for s in batch.not_emitted if s.reason == "not_a_capability_signal"]
    assert sum(name in " ".join(suppressed) for name in ("a-fork", "a-shell", "not-mine")) == 3


def test_frameworks_resolve_through_the_alias_table():
    """`mongoose` is a library name; the skill is mongodb. `next` is a CLI; the
    skill is nextjs. Emitting the raw strings would fragment the ontology."""
    got = skills(by_kind(project(full()), "repo_artifact")[1])
    assert "mongodb" in got and "mongoose" not in got
    assert "nextjs" in got and "next" not in got


def test_datastores_are_secondary_frameworks():
    got = skills(by_kind(project(full()), "repo_artifact")[1])
    assert got["nextjs"] == 0.80 and got["react"] == 0.80
    assert got["mongodb"] == 0.60, "a datastore is weaker evidence than the framework"


def test_a_repo_with_no_matching_project_claim_still_emits():
    """Two of the three repositories in the golden report have no project claim.
    A repository does not need a claim to demonstrate a language."""
    names = {e.payload["repo"] for e in by_kind(project(full()), "repo_artifact")}
    assert names == {"ATMA-Final", "cf-connect", "Terminal-Chat-Room"}


def test_substance_band_is_carried_in_the_payload():
    """The projection decides the band; m6-parameters.yaml decides what it is
    worth. The band has to travel for that split to work."""
    bands = {e.payload["repo"]: e.payload["substance_band"]
             for e in by_kind(project(full()), "repo_artifact")}
    assert bands == {"ATMA-Final": "large", "cf-connect": "substantial",
                     "Terminal-Chat-Room": "small"}


# ── claims ───────────────────────────────────────────────────────────────────

def test_backed_claim_is_corroborated_and_unbacked_is_merely_claimed():
    batch = project(full())
    corroborated = {s for e in by_kind(batch, "claim_corroborated") for s in skills(e)}
    claimed = {s for e in by_kind(batch, "cv_claim") for s in skills(e)}
    assert "typescript" in corroborated, "335 kB shipped across two repos"
    assert "cpp" in claimed, "no C++ repository exists"
    assert not corroborated & claimed


def test_a_bare_claim_is_emitted_not_dropped():
    """Weak evidence is not no evidence. Dropping it would make the graph unable
    to distinguish 'claimed but unbacked' from 'never mentioned'."""
    cv = by_kind(project(full()), "cv_claim")
    assert cv, "unbacked claims must still reach the graph"
    assert all(e.reliability <= 0.20 for e in cv), "low reliability is what limits them"

    # A plain self-report sits at the prior exactly: no GitHub evidence stands
    # behind it, so no evidence-quality factor applies either. Claims that M5
    # flagged as soft are discounted further — see test_aggregate_claims.py.
    plain = [e for e in cv if "metric" not in e.payload]
    assert plain, "the fixture should contain at least one unflagged skill claim"
    assert all(e.reliability == 0.20 and e.reliability_factors == () for e in plain)


def test_corroborated_claim_is_dated_by_the_evidence_not_the_document():
    e = by_kind(project(full()), "claim_corroborated")[0]
    assert str(e.occurred_at)[:10] == "2025-06-19", "latest corroborating commit"


def test_achievement_covered_by_a_platform_is_not_double_counted():
    """c22 and c23 are the source of the platform_rating event; re-emitting them
    as claims would count the same Codeforces rating twice."""
    batch = project(full())
    assert len(by_kind(batch, "platform_rating")) == 1
    refs = {r for e in by_kind(batch, "cv_claim") for r in e.source.claim_refs}
    assert "c22" not in refs and "c23" not in refs


def test_achievement_with_no_platform_maps_through_the_skill_table():
    """'500+ problems' spans three platforms and P3 abstained, so nothing
    corroborates it — but it still bears on problem_solving."""
    e = next(e for e in by_kind(project(full()), "cv_claim") if "c24" in e.source.claim_refs)
    assert skills(e) == {"problem_solving": 1.0}
    assert e.payload["value"] == 500


def test_unmappable_achievement_is_suppressed_with_a_reason():
    report = full()
    report["claim_graph"]["claims"].append(
        {"claim_id": "c99", "kind": "achievement", "metric": "hall_colours",
         "value": 1, "provenance": {"char_start": 0, "char_end": 1,
                                    "verbatim": "x", "recovery": "exact"}})
    reasons = [s for s in project(report).not_emitted if "c99" in s.what]
    assert len(reasons) == 1 and reasons[0].reason == "no_skill_mapping"


# ── deployments ──────────────────────────────────────────────────────────────

def test_dead_deployment_is_a_finding_not_evidence():
    """A 404 says nothing about skill. It stays in the verification report."""
    batch = project(full())
    urls = {e.payload["url"] for e in by_kind(batch, "artifact_live")}
    assert urls == {"https://atma-rs.vercel.app"}
    assert any("cf-connect-rs" in s.what and s.reason == "not_a_capability_signal"
               for s in batch.not_emitted)


def test_live_deployment_credits_the_linked_framework_and_deployment():
    got = skills(by_kind(project(full()), "artifact_live")[0])
    assert got == {"deployment": 0.70, "nextjs": 0.60}


def test_a_deployment_credits_the_framework_not_the_first_dependency():
    """M5 sends a manifest's whole dependency list, sorted. The first entry was the
    rule, so a Next.js site was credited to `@eslint/eslintrc`."""
    report = full()
    for r in report["evidence_bundle"]["github"]["repos"]:
        if r["frameworks"]:
            r["frameworks"] = ["@eslint/eslintrc", "axios", "next", "react", "zod"]
    got = skills(by_kind(project(report), "artifact_live")[0])
    assert got == {"deployment": 0.70, "nextjs": 0.60}


def test_a_deployment_with_no_known_framework_credits_deployment_alone():
    report = full()
    for r in report["evidence_bundle"]["github"]["repos"]:
        r["frameworks"] = ["axios", "zod"]
    got = skills(by_kind(project(report), "artifact_live")[0])
    assert got == {"deployment": 0.70}


# ── absent sources ───────────────────────────────────────────────────────────

def test_missing_github_block_produces_no_github_events_and_no_crash():
    report = full()
    report["evidence_bundle"]["github"] = None
    batch = project(report)
    assert by_kind(batch, "repo_artifact") == []
    assert by_kind(batch, "platform_rating"), "platform evidence is independent of GitHub"
    assert not any(s.reason == "non_scoring_rule" for s in batch.not_emitted)


def test_empty_bundle_still_yields_a_valid_batch():
    report = full()
    report["evidence_bundle"].update(github=None, platforms=[], deployments=[], credentials=[])
    batch = project(report)
    assert all(e.kind == "cv_claim" for e in batch.events)
    assert batch.not_emitted, "silence must still be explained"


def test_non_capability_claims_are_suppressed_by_name():
    """Roll number, institution and supervisor all verified — none of it maps to
    a competency, and the reader must be told so."""
    suppression = next(s for s in project(full()).not_emitted if s.reason == "no_skill_mapping")
    assert "c01" in suppression.what and "c14" in suppression.what


def test_document_disclaimer_is_inherited_not_re_derived():
    s = next(s for s in project(full()).not_emitted if s.reason == "institution_disclaimed")
    assert "coursework" in s.what


def test_a_scraped_platform_reading_is_discounted():
    """The contract declares a scraped_source factor; it must actually apply.
    A scraped profile page can be stale or misparsed in ways an API cannot."""
    report = full()
    for plat in report["evidence_bundle"]["platforms"]:
        plat["source_quality"] = "scraped"
    event = by_kind(project(report), "platform_rating")[0]
    assert {f.factor: f.value for f in event.reliability_factors} == {"scraped_source": 0.7}
    assert abs(event.reliability - 0.90 * 0.7) < 1e-9


def _with_codechef(report: dict, *, rating: int, claimed: int | None) -> dict:
    report["evidence_bundle"]["platforms"].append({
        "platform": "codechef", "handle": "chef", "found": True, "max_rating": rating,
        "rank_title": "3 star", "problems_solved": 26, "contests": [],
        "source_quality": "scrape"})
    if claimed is not None:
        claim = dict(next(c for c in report["claim_graph"]["claims"]
                          if c.get("platform") == "codeforces" and c.get("metric") == "max_rating"))
        claim.update(claim_id="ccc1", platform="codechef", value=claimed)
        report["claim_graph"]["claims"].append(claim)
    return report


def test_a_codechef_rating_confirms_the_claim_instead_of_being_priced():
    """No reference distribution places CodeChef's scale, so it must never reach
    6.3 as a platform_rating. What it does establish — the claim is true — needs
    no scale."""
    batch = project(_with_codechef(full(), rating=1746, claimed=1733))
    assert all(e.payload.get("platform") != "codechef"
               for e in by_kind(batch, "platform_rating"))
    event = next(e for e in by_kind(batch, "claim_corroborated")
                 if e.payload.get("platform") == "codechef")
    assert event.source.claim_refs == ("ccc1",)
    assert (event.payload["claimed"], event.payload["platform_value"]) == (1733, 1746)
    assert {f.factor for f in event.reliability_factors} == {"scraped_source"}
    assert abs(event.reliability - 0.80 * 0.7) < 1e-9
    assert not any(e.kind == "cv_claim" and "ccc1" in e.source.claim_refs
                   for e in batch.events), "the claim is carried once, not twice"


def test_a_claim_the_platform_falls_short_of_stays_a_cv_claim():
    batch = project(_with_codechef(full(), rating=1600, claimed=1733))
    assert not any(e.payload.get("platform") == "codechef"
                   for e in by_kind(batch, "claim_corroborated"))
    assert any(e.kind == "cv_claim" and "ccc1" in e.source.claim_refs for e in batch.events)


def test_an_unplaced_rating_no_claim_cites_is_suppressed_by_name():
    batch = project(_with_codechef(full(), rating=1746, claimed=None))
    assert any("codechef rating 1746" in s.what and s.reason == "not_a_capability_signal"
               for s in batch.not_emitted)


def test_an_api_platform_reading_is_not_discounted():
    """The golden fixture reads Codeforces over the API — full reliability."""
    event = by_kind(project(full()), "platform_rating")[0]
    assert event.reliability_factors == ()
    assert event.reliability == 0.90
