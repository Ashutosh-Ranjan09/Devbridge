"""The checks, against recorded evidence. No network.

conventions: connectors are tested from recorded responses, so a test run needs no
token, hits no rate limit, and does not fail when Codeforces has an outage — which it
did, mid-spike.
"""

from __future__ import annotations

import datetime

import pytest

from cvv.dates import parse_interval
from cvv.models import (
    ActivityWindow,
    Artefact,
    ArtefactType,
    ClaimKind,
    ContestResult,
    DeploymentEvidence,
    DocumentInfo,
    EmploymentType,
    EvidenceBundle,
    Gap,
    GapReason,
    GitHubEvidence,
    IngestMethod,
    Ownership,
    Platform,
    PlatformEvidence,
    RepoEvidence,
    RuleStatus,
    Severity,
    Tier,
)
from cvv.report import assemble
from cvv.rules import REGISTRY, _same_org
from tests.cvdata import (
    AGGREGATE,
    CF_RANK,
    CF_RATING,
    DISCLAIMER,
    DOCUMENT,
    ROLL,
    SKILLS_LINE,
    make_claim,
    make_graph,
)

NOW = datetime.datetime(2026, 9, 4, tzinfo=datetime.UTC)


def codeforces(*, max_rating: int = 1495, ranks: tuple[int, ...] = (1106,), solved: int = 412):
    return PlatformEvidence(
        platform=Platform.CODEFORCES,
        handle="AR009",
        found=True,
        max_rating=max_rating,
        problems_solved=solved,
        contests=[
            ContestResult(name=f"Codeforces Round {998 + i}", rank=r, rating_after=max_rating)
            for i, r in enumerate(ranks)
        ],
    )


def bundle(
    graph, *, platforms=(), deployments=(), gaps=(), github=None
) -> EvidenceBundle:
    return EvidenceBundle(
        bundle_id="eb_test",
        graph_id=graph.graph_id,
        github=github,
        platforms=list(platforms),
        deployments=list(deployments),
        gathered_at=NOW,
        gaps=list(gaps),
    )


def outcome(report, rule_id: str):
    return next(o for o in report.rule_outcomes if o.rule_id == rule_id)


class TestP1CodeforcesRating:
    def test_clean_when_the_api_agrees(self) -> None:
        claim = make_claim(
            CF_RATING, DOCUMENT, platform="codeforces", metric="max_rating", value=1495
        )
        graph = make_graph([claim], DOCUMENT)
        report = assemble(graph, bundle(graph, platforms=[codeforces(max_rating=1495)]))
        assert outcome(report, "P1").status is RuleStatus.CLEAN
        assert report.discrepancies == []

    def test_fires_when_the_api_disagrees(self) -> None:
        claim = make_claim(
            CF_RATING, DOCUMENT, platform="codeforces", metric="max_rating", value=1495
        )
        graph = make_graph([claim], DOCUMENT)
        report = assemble(graph, bundle(graph, platforms=[codeforces(max_rating=1180)]))
        finding = next(f for f in report.discrepancies if f.rule_id == "P1")
        assert finding.tier is Tier.DECISIVE
        assert finding.params == {
            "claimed": 1495,
            "actual": 1180,
            "overstated_by": 315,
            "handle": "AR009",
        }
        assert finding.finding_id in report.buckets.contradicted
        assert claim.claim_id in finding.claim_refs, "a finding must cite its claim"

    def test_abstains_with_the_gaps_reason_when_the_api_is_unreachable(self) -> None:
        """The outage case, exactly as it happened: Codeforces returned 504 and the
        reason has to reach the reader. Silence would read as a pass."""
        claim = make_claim(
            CF_RATING, DOCUMENT, platform="codeforces", metric="max_rating", value=1495
        )
        graph = make_graph([claim], DOCUMENT)
        gap = Gap(
            source="codeforces", reason=GapReason.UNREACHABLE, detail="504 Gateway Timeout"
        )
        report = assemble(graph, bundle(graph, gaps=[gap]))
        result = outcome(report, "P1")
        assert result.status is RuleStatus.ABSTAINED
        assert "504" in (result.reason or "")
        assert any("504" in n for n in report.buckets.not_evaluated)

    def test_abstains_when_nothing_is_claimed(self) -> None:
        graph = make_graph([], DOCUMENT)
        report = assemble(graph, bundle(graph, platforms=[codeforces()]))
        assert outcome(report, "P1").status is RuleStatus.ABSTAINED

    def test_understating_is_never_a_finding(self) -> None:
        """max_rating is a peak and only rises, so a CV written six months ago
        disagrees with a better API value — and the candidate understated. Nothing in
        this design penalises that."""
        claim = make_claim(
            CF_RATING, DOCUMENT, platform="codeforces", metric="max_rating", value=1495
        )
        graph = make_graph([claim], DOCUMENT)
        report = assemble(graph, bundle(graph, platforms=[codeforces(max_rating=1700)]))
        assert outcome(report, "P1").status is RuleStatus.CLEAN
        assert report.discrepancies == []

    def test_a_small_overstatement_is_attention_not_contradicted(self) -> None:
        """Codeforces rerates contests after cheat removals, so a rating copied
        shortly after a contest can sit a few points above the settled value. The fact
        is still reported — only the tier changes."""
        claim = make_claim(
            CF_RATING, DOCUMENT, platform="codeforces", metric="max_rating", value=1495
        )
        graph = make_graph([claim], DOCUMENT)
        report = assemble(graph, bundle(graph, platforms=[codeforces(max_rating=1480)]))
        finding = next(f for f in report.discrepancies if f.rule_id == "P1")
        assert finding.tier is Tier.ATTENTION
        assert finding.innocent_explanation, "an attention finding must carry one"
        assert finding.finding_id in report.buckets.needs_context
        assert finding.finding_id not in report.buckets.contradicted


class TestP2ContestRank:
    def test_clean_when_the_rank_is_in_the_history(self) -> None:
        claim = make_claim(
            CF_RANK, DOCUMENT, platform="codeforces", metric="contest_rank", value=1106
        )
        graph = make_graph([claim], DOCUMENT)
        report = assemble(graph, bundle(graph, platforms=[codeforces(ranks=(1106, 2431))]))
        assert outcome(report, "P2").status is RuleStatus.CLEAN

    def test_fires_when_the_rank_is_absent(self) -> None:
        claim = make_claim(
            CF_RANK, DOCUMENT, platform="codeforces", metric="contest_rank", value=1106
        )
        graph = make_graph([claim], DOCUMENT)
        report = assemble(graph, bundle(graph, platforms=[codeforces(ranks=(2431, 3980))]))
        assert outcome(report, "P2").status is RuleStatus.FIRED

    def test_a_better_recorded_rank_is_never_a_finding(self) -> None:
        """Lower is better. A record at least as good as the claim means the candidate
        understated, or the standings improved after rejudging."""
        claim = make_claim(
            CF_RANK, DOCUMENT, platform="codeforces", metric="contest_rank", value=1106
        )
        graph = make_graph([claim], DOCUMENT)
        report = assemble(graph, bundle(graph, platforms=[codeforces(ranks=(1050,))]))
        assert outcome(report, "P2").status is RuleStatus.CLEAN

    def test_a_few_places_out_is_attention_not_contradicted(self) -> None:
        """The real case: a CV claiming 1106 in Round 998 where the API records 1109.
        Three places on 1100 is a standings-timing artefact, not a fabrication."""
        claim = make_claim(
            CF_RANK, DOCUMENT, platform="codeforces", metric="contest_rank", value=1106
        )
        graph = make_graph([claim], DOCUMENT)
        report = assemble(graph, bundle(graph, platforms=[codeforces(ranks=(1109,))]))
        finding = next(f for f in report.discrepancies if f.rule_id == "P2")
        assert finding.tier is Tier.ATTENTION
        assert finding.innocent_explanation
        assert finding.finding_id in report.buckets.needs_context

    def test_a_large_overstatement_stays_decisive(self) -> None:
        claim = make_claim(
            CF_RANK, DOCUMENT, platform="codeforces", metric="contest_rank", value=100
        )
        graph = make_graph([claim], DOCUMENT)
        report = assemble(graph, bundle(graph, platforms=[codeforces(ranks=(5000,))]))
        finding = next(f for f in report.discrepancies if f.rule_id == "P2")
        assert finding.tier is Tier.DECISIVE
        assert finding.finding_id in report.buckets.contradicted


class TestP3ProblemsSolved:
    """The aggregate claim must never fire and must never go silent."""

    @pytest.mark.parametrize("api_count", [412, 180, 900])
    def test_always_abstains_on_an_aggregate_claim(self, api_count: int) -> None:
        """"500+ across LeetCode, Codeforces and GeeksforGeeks" names three sources.
        Comparing it to Codeforces alone compares the wrong things — and at 180 it
        would have reported a contradiction that does not exist."""
        claim = make_claim(
            AGGREGATE,
            DOCUMENT,
            platform="leetcode",
            metric="problems_solved",
            value=500,
            flags=["aggregate_across_sources"],
            context={"platforms": ["codeforces", "geeksforgeeks", "leetcode"]},
        )
        graph = make_graph([claim], DOCUMENT)
        report = assemble(graph, bundle(graph, platforms=[codeforces(solved=api_count)]))
        result = outcome(report, "P3")
        assert result.status is RuleStatus.ABSTAINED
        assert "aggregates 3 platforms" in (result.reason or "")

    def test_solving_more_than_claimed_is_not_a_contradiction(self) -> None:
        """"500+" is a floor. Understating is never penalised."""
        claim = make_claim(
            CF_RATING, DOCUMENT, platform="codeforces", metric="problems_solved", value=1495
        )
        graph = make_graph([claim], DOCUMENT)
        report = assemble(graph, bundle(graph, platforms=[codeforces(solved=9000)]))
        assert outcome(report, "P3").status is RuleStatus.CLEAN


class TestW1DeploymentLiveness:
    def test_fires_on_a_dead_url_and_names_the_project(self) -> None:
        claim = make_claim(
            CF_RATING,
            DOCUMENT,
            kind=ClaimKind.PROJECT,
            title="CF-Connect",
            artefacts=[
                Artefact(type=ArtefactType.DEPLOYMENT, url="https://cf-connect.vercel.app")
            ],
        )
        graph = make_graph([claim], DOCUMENT)
        dead = DeploymentEvidence(
            url="https://cf-connect.vercel.app", reachable=False, status_code=404, checked_at=NOW
        )
        report = assemble(graph, bundle(graph, deployments=[dead]))
        finding = next(f for f in report.discrepancies if f.rule_id == "W1")
        assert "CF-Connect" in finding.explanation
        assert "404" in finding.explanation

    def test_clean_when_the_url_responds(self) -> None:
        graph = make_graph([], DOCUMENT)
        live = DeploymentEvidence(
            url="https://atma-ar.vercel.app", reachable=True, status_code=200, checked_at=NOW
        )
        report = assemble(graph, bundle(graph, deployments=[live]))
        assert outcome(report, "W1").status is RuleStatus.CLEAN


class TestTheRunner:
    def test_every_registered_rule_appears_in_the_outcomes(self) -> None:
        """Including the ones that did nothing. A rule missing from the outcomes is a
        check the reader believes ran."""
        graph = make_graph([], DOCUMENT)
        report = assemble(graph, bundle(graph))
        assert {o.rule_id for o in report.rule_outcomes} == {r.rule_id for r in REGISTRY}

    def test_a_raising_rule_is_isolated_and_the_report_still_renders(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One malformed claim must never take down a report — without this you find
        out during a demo rather than in testing."""

        def explode(self, ctx):
            raise ValueError("simulated rule failure")

        monkeypatch.setattr(type(REGISTRY[0]), "evaluate", explode)
        graph = make_graph([], DOCUMENT)
        report = assemble(graph, bundle(graph))

        broken = outcome(report, REGISTRY[0].rule_id)
        assert broken.status is RuleStatus.ERROR
        assert "simulated rule failure" in (broken.reason or "")
        assert len(report.rule_outcomes) == len(REGISTRY), "the other rules still ran"

    def test_an_abstention_always_carries_a_reason(self) -> None:
        """Enforced by the model validator too — but the rules must supply one."""
        graph = make_graph([], DOCUMENT)
        report = assemble(graph, bundle(graph))
        for o in report.rule_outcomes:
            if o.status in (RuleStatus.ABSTAINED, RuleStatus.ERROR):
                assert o.reason, f"{o.rule_id} abstained silently"


class TestTheReport:
    def test_there_is_no_overall_score(self) -> None:
        """The one field that must never exist."""
        graph = make_graph([], DOCUMENT)
        report = assemble(graph, bundle(graph))
        assert not hasattr(report, "overall_score")
        assert "overall_score" not in report.model_dump()

    def test_out_of_scope_is_always_present(self) -> None:
        """The reader must not infer that an unmentioned thing was checked."""
        graph = make_graph([], DOCUMENT)
        report = assemble(graph, bundle(graph))
        assert report.buckets.out_of_scope
        assert any("JEE" in o for o in report.buckets.out_of_scope)


# --------------------------------------------------------------------------- #
# G · GitHub
# --------------------------------------------------------------------------- #


def repo(
    name: str,
    *,
    exists: bool = True,
    is_fork: bool = False,
    owner_matches: bool = True,
    readme_only: bool = False,
    created: str = "2025-06-24",
    languages: tuple[str, ...] = (),
    frameworks: tuple[str, ...] = (),
) -> RepoEvidence:
    return RepoEvidence(
        name=name,
        exists=exists,
        is_fork=is_fork,
        owner_matches=owner_matches,
        is_readme_only=readme_only,
        languages=dict.fromkeys(languages, 1),
        frameworks=list(frameworks),
        created_at=datetime.date.fromisoformat(created),
        first_commit=None,  # no trustworthy server-side value exists
    )


def github(
    *,
    repos: tuple[RepoEvidence, ...] = (),
    public: tuple[RepoEvidence, ...] = (),
    windows: tuple[tuple[str, int], ...] = (),
    orgs: tuple[str, ...] = (),
    created: str = "2024-06-29",
    first_seen: dict[str, str] | None = None,
) -> GitHubEvidence:
    return GitHubEvidence(
        handle="Ashutosh-Ranjan09",
        ownership=Ownership.CLAIMED_UNVERIFIED,
        account_created=datetime.date.fromisoformat(created),
        first_commit_by_language={
            k: datetime.date.fromisoformat(v) for k, v in (first_seen or {}).items()
        },
        repos=list(repos),
        public_repos=list(public or repos),
        public_repo_count=len(public or repos),
        org_memberships=list(orgs),
        contribution_windows=[
            ActivityWindow(
                start=datetime.date.fromisoformat(f"{month}-01"),
                end=datetime.date.fromisoformat(f"{month}-28"),
                commit_count=count,
                active_days=min(count, 28),
            )
            for month, count in windows
        ],
    )


def project(title: str, dates: str, repo_url: str = "", tech: tuple[str, ...] = ()) -> object:
    interval = parse_interval(dates)
    assert interval is not None, dates
    return make_claim(
        CF_RATING,
        DOCUMENT,
        claim_id="c" + title[:6].lower().replace(" ", ""),
        kind=ClaimKind.PROJECT,
        title=title,
        interval=interval,
        skill_refs=list(tech),
        artefacts=[Artefact(type=ArtefactType.REPO, url=repo_url)] if repo_url else [],
    )


class TestG2AccountExists:
    def test_fires_when_the_account_does_not_exist(self) -> None:
        graph = make_graph([], DOCUMENT)
        gap = Gap(
            source="github",
            reason=GapReason.NOT_FOUND,
            detail="No GitHub account exists at github.com/ghost.",
        )
        report = assemble(graph, bundle(graph, gaps=[gap]))
        finding = next(f for f in report.discrepancies if f.rule_id == "G2")
        assert finding.tier is Tier.DECISIVE
        assert finding.finding_id in report.buckets.contradicted

    def test_clean_when_the_account_resolves(self) -> None:
        graph = make_graph([], DOCUMENT)
        report = assemble(graph, bundle(graph, github=github()))
        assert outcome(report, "G2").status is RuleStatus.CLEAN

    def test_abstains_when_no_handle_was_found(self) -> None:
        graph = make_graph([], DOCUMENT)
        gap = Gap(
            source="github",
            reason=GapReason.NO_HANDLE_IN_CV,
            detail="No GitHub repository URL found in the document.",
        )
        report = assemble(graph, bundle(graph, gaps=[gap]))
        result = outcome(report, "G2")
        assert result.status is RuleStatus.ABSTAINED
        assert "No GitHub repository URL" in (result.reason or "")


class TestG4RepoExistsOwnedNotFork:
    def test_clean_when_every_named_repo_is_owned_and_original(self) -> None:
        gh = github(repos=(repo("ATMA-Final"), repo("cf-connect")))
        graph = make_graph([], DOCUMENT)
        report = assemble(graph, bundle(graph, github=gh))
        assert outcome(report, "G4").status is RuleStatus.CLEAN

    def test_fires_when_a_named_repo_does_not_exist(self) -> None:
        gh = github(repos=(repo("ghost-project", exists=False),))
        graph = make_graph([], DOCUMENT)
        report = assemble(graph, bundle(graph, github=gh))
        finding = next(f for f in report.discrepancies if f.rule_id == "G4")
        assert finding.tier is Tier.DECISIVE
        assert "does not exist" in finding.explanation

    def test_fires_on_a_fork(self) -> None:
        """Presenting someone else's work as a project is a different claim from
        writing it, and GitHub records the distinction."""
        gh = github(repos=(repo("borrowed", is_fork=True),))
        graph = make_graph([], DOCUMENT)
        report = assemble(graph, bundle(graph, github=gh))
        finding = next(f for f in report.discrepancies if f.rule_id == "G4")
        assert "fork" in finding.explanation

    def test_abstains_when_no_repositories_are_named(self) -> None:
        graph = make_graph([], DOCUMENT)
        report = assemble(graph, bundle(graph, github=github()))
        assert outcome(report, "G4").status is RuleStatus.ABSTAINED


class TestG5ActivityDuringClaimedWindow:
    def test_the_real_cv_regression(self) -> None:
        """THE case that shaped this rule.

        ATMA claims Mar-Apr 2025 and its repository was created 2025-06-24 — two
        months later. A created_at comparison fires a decisive contradiction against
        an honest CV. The contributions calendar records activity in March and April:
        the work happened when claimed, the repository was pushed afterwards, which is
        what a course project looks like.
        """
        gh = github(
            repos=(repo("ATMA-Final", created="2025-06-24"),),
            windows=(("2025-01", 0), ("2025-03", 4), ("2025-04", 16), ("2025-05", 9)),
        )
        graph = make_graph([project("ATMA", "[Mar '25 - Apr '25]")], DOCUMENT)
        report = assemble(graph, bundle(graph, github=gh))
        assert outcome(report, "G5").status is RuleStatus.CLEAN
        assert not [f for f in report.discrepancies if f.rule_id == "G5"]

    def test_fires_when_the_window_is_completely_quiet(self) -> None:
        gh = github(windows=(("2025-01", 0), ("2025-03", 0), ("2025-04", 0), ("2025-05", 7)))
        graph = make_graph([project("Ghost", "[Mar '25 - Apr '25]")], DOCUMENT)
        report = assemble(graph, bundle(graph, github=gh))
        finding = next(f for f in report.discrepancies if f.rule_id == "G5")
        assert finding.tier is Tier.ATTENTION, "the calendar excludes private work"
        assert finding.innocent_explanation
        assert "private" in finding.innocent_explanation
        assert finding.finding_id in report.buckets.needs_context

    def test_abstains_without_a_calendar(self) -> None:
        """The calendar needs an authenticated GraphQL request. Without it the rule
        says so rather than approximating from repo.created_at."""
        gh = github(repos=(repo("ATMA-Final"),))
        graph = make_graph([project("ATMA", "[Mar '25 - Apr '25]")], DOCUMENT)
        report = assemble(graph, bundle(graph, github=gh))
        result = outcome(report, "G5")
        assert result.status is RuleStatus.ABSTAINED
        assert "CVV_GITHUB_TOKEN" in (result.reason or "")

    def test_ignores_a_window_the_calendar_does_not_cover(self) -> None:
        """A project predating the account cannot be judged from it either way."""
        gh = github(windows=(("2025-03", 4),))
        graph = make_graph([project("Old", "[Jun '20]")], DOCUMENT)
        report = assemble(graph, bundle(graph, github=gh))
        assert outcome(report, "G5").status is RuleStatus.CLEAN


class TestG7RepoSubstance:
    def test_fires_on_a_repository_holding_only_a_readme(self) -> None:
        gh = github(repos=(repo("empty-shell", readme_only=True),))
        graph = make_graph([], DOCUMENT)
        report = assemble(graph, bundle(graph, github=gh))
        finding = next(f for f in report.discrepancies if f.rule_id == "G7")
        assert finding.tier is Tier.DECISIVE

    def test_a_small_program_is_still_a_program(self) -> None:
        """A two-file Python chat application is not an empty repository. An earlier
        heuristic counted files and marked it as one."""
        gh = github(repos=(repo("Terminal-Chat-Room", readme_only=False),))
        graph = make_graph([], DOCUMENT)
        report = assemble(graph, bundle(graph, github=gh))
        assert outcome(report, "G7").status is RuleStatus.CLEAN


class TestG8PortfolioComposition:
    def test_fires_when_almost_everything_is_forked(self) -> None:
        forks = tuple(repo(f"fork-{i}", is_fork=True) for i in range(9))
        gh = github(repos=(repo("mine"),), public=(*forks, repo("mine")))
        graph = make_graph([], DOCUMENT)
        report = assemble(graph, bundle(graph, github=gh))
        finding = next(f for f in report.discrepancies if f.rule_id == "G8")
        assert finding.tier is Tier.ATTENTION
        assert finding.innocent_explanation, "forking is how contributing begins"
        assert finding.params["forks"] == 9

    def test_clean_for_an_account_of_original_work(self) -> None:
        gh = github(public=tuple(repo(f"r{i}") for i in range(7)))
        graph = make_graph([], DOCUMENT)
        report = assemble(graph, bundle(graph, github=gh))
        assert outcome(report, "G8").status is RuleStatus.CLEAN


# --------------------------------------------------------------------------- #
# D · document-intrinsic
# --------------------------------------------------------------------------- #


def roll(number: str = ROLL, *, year: int = 2023, dept: str = "CS") -> object:
    return make_claim(
        number,
        DOCUMENT,
        claim_id="cid001",
        kind=ClaimKind.IDENTIFIER,
        parsed={"admission_year": year, "dept_code": dept, "serial": 10004},
    )


def degree(name: str, org: str, year: str, claim_id: str = "cdeg01") -> object:
    interval = parse_interval(year)
    return make_claim(
        CF_RANK,
        DOCUMENT,
        claim_id=claim_id,
        kind=ClaimKind.EDUCATION,
        degree=name,
        org=org,
        interval=interval,
    )


class TestD9RollNumberStructure:
    """The invariant working: a decisive check needing no network at all, because the
    evidence is the document's own internal consistency."""

    def test_the_real_cv_abstains_but_reports_what_it_did_check(self) -> None:
        """23CS10004 with a B.TECH completing 2027. The years line up (2023 + 4), and
        the CV never states a department — the programme name lives in the header, not
        in the degree field. Absence is not a contradiction, so the rule abstains, and
        the reason has to carry the half that DID run."""
        graph = make_graph(
            [roll(), degree("B.TECH", "IIT Kharagpur", "2027")], DOCUMENT
        )
        report = assemble(graph, bundle(graph))
        result = outcome(report, "D9")
        assert result.status is RuleStatus.ABSTAINED
        assert "states no department" in (result.reason or "")
        assert "which the CV agrees with" in (result.reason or ""), (
            "the timeline check ran and passed; dropping that is the silence the "
            "design forbids"
        )

    def test_fires_when_the_timeline_does_not_add_up(self) -> None:
        """Admitted 2023, a four-year B.Tech, but the CV claims completion in 2025."""
        graph = make_graph(
            [roll(), degree("B.TECH", "IIT Kharagpur", "2025")], DOCUMENT
        )
        report = assemble(graph, bundle(graph))
        finding = next(f for f in report.discrepancies if f.rule_id == "D9")
        assert finding.tier is Tier.DECISIVE
        assert finding.params["expected_completion"] == 2027
        assert finding.params["claimed_completion"] == 2025
        assert finding.finding_id in report.buckets.contradicted

    def test_fires_when_the_department_contradicts_the_degree(self) -> None:
        graph = make_graph(
            [
                roll(dept="ME"),
                degree("B.Tech in Computer Science and Engineering", "IIT Kharagpur", "2027"),
            ],
            DOCUMENT,
        )
        report = assemble(graph, bundle(graph))
        finding = next(f for f in report.discrepancies if f.rule_id == "D9")
        assert finding.tier is Tier.DECISIVE
        assert "mechanical" in finding.explanation.lower()

    def test_a_matching_department_and_timeline_is_clean(self) -> None:
        graph = make_graph(
            [
                roll(),
                degree("B.Tech in Computer Science and Engineering", "IIT Kharagpur", "2027"),
            ],
            DOCUMENT,
        )
        report = assemble(graph, bundle(graph))
        assert outcome(report, "D9").status is RuleStatus.CLEAN

    def test_an_unrecognised_scheme_abstains(self) -> None:
        """Roll-number schemes are institution-specific. An unknown shape is decoded
        by nothing, and guessing at it is how a rule invents a finding."""
        graph = make_graph(
            [
                make_claim(
                    "AR009", DOCUMENT, claim_id="cid002", kind=ClaimKind.IDENTIFIER,
                    parsed={"admission_year": 2021, "dept_code": "ZZ", "serial": 1},
                ),
                degree("B.Tech", "Some Other University", "2025"),
            ],
            DOCUMENT,
        )
        report = assemble(graph, bundle(graph))
        assert outcome(report, "D9").status is RuleStatus.ABSTAINED

    def test_abstains_without_an_identifier(self) -> None:
        graph = make_graph([degree("B.TECH", "IIT Kharagpur", "2027")], DOCUMENT)
        result = outcome(assemble(graph, bundle(make_graph([], DOCUMENT))), "D9")
        assert result.status is RuleStatus.ABSTAINED
        assert "identifier" in (result.reason or "")


def role(
    org: str,
    dates: str,
    kind: EmploymentType = EmploymentType.UNSTATED,
    claim_id: str = "",
    title: str = "Engineer",
) -> object:
    interval = parse_interval(dates)
    assert interval is not None, dates
    return make_claim(
        CF_RANK,
        DOCUMENT,
        claim_id=claim_id or "c" + org[:6].lower().replace(" ", ""),
        kind=ClaimKind.EMPLOYMENT,
        org=org,
        title=title,
        employment_type=kind,
        interval=interval,
    )


class TestD5IntervalOverlap:
    """Document-intrinsic: no network, no account, no cooperation."""

    def test_two_full_time_roles_at_once_is_decisive(self) -> None:
        graph = make_graph(
            [
                role("Acme", "Mar 2021 - Aug 2023", EmploymentType.FULL_TIME, "c001"),
                role("Globex", "Jan 2022 - Dec 2022", EmploymentType.FULL_TIME, "c002"),
            ],
            DOCUMENT,
        )
        report = assemble(graph, bundle(graph))
        finding = next(f for f in report.discrepancies if f.rule_id == "D5")
        assert finding.tier is Tier.DECISIVE
        assert finding.finding_id in report.buckets.contradicted

    def test_year_precision_alone_never_scores(self) -> None:
        """THE HARD-CONSTRAINT REGRESSION, at the report level.

        "2023" against "2023" is POSSIBLE, not DEFINITE — the two roles could have run
        Jan-Jun and Jul-Dec. Most Indian CVs give year precision only, so scoring this
        turns every clean CV into a contradiction.
        """
        graph = make_graph(
            [
                role("Acme", "2023", EmploymentType.FULL_TIME, "c001"),
                role("Globex", "2023", EmploymentType.FULL_TIME, "c002"),
            ],
            DOCUMENT,
        )
        report = assemble(graph, bundle(graph))
        assert outcome(report, "D5").status is RuleStatus.CLEAN
        assert not [f for f in report.discrepancies if f.rule_id == "D5"]

    def test_an_internship_concurrent_with_anything_is_not_a_finding(self) -> None:
        """Students work while studying, and a summer internship overlapping a
        part-time role is ordinary life. A rule that flags it penalises the people
        most likely to need both."""
        graph = make_graph(
            [
                role("Acme", "May 2024 - Aug 2024", EmploymentType.INTERNSHIP, "c001"),
                role("Globex", "Jan 2024 - Dec 2024", EmploymentType.FULL_TIME, "c002"),
            ],
            DOCUMENT,
        )
        report = assemble(graph, bundle(graph))
        assert outcome(report, "D5").status is RuleStatus.CLEAN

    def test_an_unstated_type_is_a_question_not_a_fact(self) -> None:
        """Most CVs never say "full-time". The overlap is real; its significance is
        not, so it is posed rather than asserted."""
        graph = make_graph(
            [
                role("Acme", "Mar 2021 - Aug 2023", claim_id="c001"),
                role("Globex", "Jan 2022 - Dec 2022", claim_id="c002"),
            ],
            DOCUMENT,
        )
        report = assemble(graph, bundle(graph))
        finding = next(f for f in report.discrepancies if f.rule_id == "D5")
        assert finding.tier is Tier.ATTENTION
        assert finding.innocent_explanation
        assert finding.finding_id in report.buckets.needs_context

    def test_abstains_with_fewer_than_two_dated_roles(self) -> None:
        graph = make_graph([role("Acme", "2023")], DOCUMENT)
        result = outcome(assemble(graph, bundle(graph)), "D5")
        assert result.status is RuleStatus.ABSTAINED
        assert "nothing to overlap" in (result.reason or "")


class TestG3OwnershipProof:
    """It verifies nothing, and cannot. Public GitHub data says an account exists and
    what it did; nothing links an account to a specific human."""

    def test_reports_the_unproven_state_and_never_scores(self) -> None:
        graph = make_graph([], DOCUMENT)
        report = assemble(graph, bundle(graph, github=github()))
        finding = next(f for f in report.discrepancies if f.rule_id == "G3")
        assert finding.tier is Tier.ATTENTION
        assert finding.scoring is False, (
            "G3 describes how to READ the other GitHub findings; letting it move a "
            "number would double-count them"
        )
        assert finding.params["ownership"] == "claimed_unverified"
        assert "CORROBORATES" in (finding.innocent_explanation or "")

    def test_says_nothing_once_control_is_proven(self) -> None:
        gh = github()
        proven = gh.model_copy(update={"ownership": Ownership.VERIFIED_CHALLENGE})
        graph = make_graph([], DOCUMENT)
        report = assemble(graph, bundle(graph, github=proven))
        assert outcome(report, "G3").status is RuleStatus.CLEAN

    def test_abstains_without_a_github_account(self) -> None:
        graph = make_graph([], DOCUMENT)
        gap = Gap(
            source="github",
            reason=GapReason.NO_HANDLE_IN_CV,
            detail="No GitHub repository URL found in the document.",
        )
        assert outcome(assemble(graph, bundle(graph, gaps=[gap])), "G3").status is (
            RuleStatus.ABSTAINED
        )


# ---------------------------------------------------------------------------
# The document-intrinsic group: no network, no account, no cooperation. These are
# the checks the invariant rests on — a CV naming nothing still gets a real report.
# ---------------------------------------------------------------------------


def document_info(
    *, created: str | None = "D:20250704194743+05'30'", modified: str | None = None,
    producer: str | None = "iText 2.1.7 by 1T3XT",
) -> DocumentInfo:
    return DocumentInfo(
        document_id="doc_test",
        pages=1,
        ingest_method=IngestMethod.PDF_TEXT,
        producer=producer,
        created_at=created,
        modified_at=modified if modified is not None else created,
    )


class TestD2SpanGrounding:
    """A finding about the EXTRACTOR, not about the candidate.

    Dropping a claim whose text is not in the document is the guardrail working. The
    cost is coverage, and stating that openly is the whole point of the rule: a report
    that silently checks less than it appears to is worse than one that says so.
    """

    def test_reports_what_was_dropped_and_never_scores(self) -> None:
        graph = make_graph([roll()], DOCUMENT, span_failures=2)
        report = assemble(graph, bundle(graph))
        finding = next(f for f in report.discrepancies if f.rule_id == "D2")
        assert finding.params == {"dropped": 2, "kept": 1, "proposed": 3}
        assert finding.scoring is False
        assert finding.claim_refs == [], "no claim survived to be cited"
        assert finding.finding_id in report.buckets.needs_context

    def test_losing_more_than_was_kept_is_a_louder_finding(self) -> None:
        graph = make_graph([roll()], DOCUMENT, span_failures=9)
        report = assemble(graph, bundle(graph))
        finding = next(f for f in report.discrepancies if f.rule_id == "D2")
        assert finding.severity is Severity.HIGH

    def test_silent_when_every_proposal_grounded(self) -> None:
        graph = make_graph([roll()], DOCUMENT)
        report = assemble(graph, bundle(graph))
        assert outcome(report, "D2").status is RuleStatus.CLEAN
        assert not [f for f in report.discrepancies if f.rule_id == "D2"]


class TestD3SelfDeclarationMarkers:
    """The document telling you its own trust boundary.

    A reader who does not see "CDC could not verify the relevant documents" may take
    the whole page as institutionally attested. Inheriting the disclaimer is more
    honest than ignoring it and more honest than re-deriving it.
    """

    def marker(self) -> object:
        return make_claim(
            DISCLAIMER, DOCUMENT, claim_id="cdecl1", kind=ClaimKind.DECLARATION_MARKER
        )

    def test_quotes_the_disclaimer_and_never_scores(self) -> None:
        graph = make_graph([self.marker()], DOCUMENT)
        report = assemble(graph, bundle(graph))
        finding = next(f for f in report.discrepancies if f.rule_id == "D3")
        assert finding.params["marker"] == DISCLAIMER
        assert finding.scoring is False
        assert finding.tier is Tier.ATTENTION
        assert "the candidate" in finding.innocent_explanation

    def test_is_never_a_mark_against_the_candidate(self) -> None:
        """It lands in needs_context, never in contradicted — the institution wrote
        it, and a candidate cannot be faulted for their own CDC's template."""
        graph = make_graph([self.marker()], DOCUMENT)
        report = assemble(graph, bundle(graph))
        finding = next(f for f in report.discrepancies if f.rule_id == "D3")
        assert finding.finding_id in report.buckets.needs_context
        assert finding.finding_id not in report.buckets.contradicted

    def test_abstains_on_a_document_that_disclaims_nothing(self) -> None:
        graph = make_graph([], DOCUMENT)
        report = assemble(graph, bundle(graph))
        assert outcome(report, "D3").status is RuleStatus.ABSTAINED


class TestD4DocumentProvenance:
    def test_fires_on_an_edit_long_after_generation(self) -> None:
        graph = make_graph([], DOCUMENT)
        report = assemble(
            graph,
            bundle(graph),
            document=document_info(modified="D:20250810120000+05'30'"),
        )
        finding = next(f for f in report.discrepancies if f.rule_id == "D4")
        assert finding.params == {
            "created": "2025-07-04",
            "modified": "2025-08-10",
            "gap_days": 37,
        }
        assert finding.scoring is False

    def test_an_institutional_producer_is_never_itself_a_finding(self) -> None:
        """The trap this rule was written around. A CV produced by a placement cell's
        template went THROUGH that cell, which is trust-increasing; firing on the
        producer string would invert the meaning of the evidence."""
        graph = make_graph([], DOCUMENT)
        report = assemble(graph, bundle(graph), document=document_info())
        assert outcome(report, "D4").status is RuleStatus.CLEAN
        assert not [f for f in report.discrepancies if f.rule_id == "D4"]

    def test_abstains_when_the_file_records_no_times(self) -> None:
        graph = make_graph([], DOCUMENT)
        report = assemble(graph, bundle(graph), document=document_info(created=None))
        result = outcome(report, "D4")
        assert result.status is RuleStatus.ABSTAINED
        assert "normal for many exporters" in (result.reason or "")

    def test_abstains_when_no_metadata_reaches_the_rule(self) -> None:
        graph = make_graph([], DOCUMENT)
        report = assemble(graph, bundle(graph))
        assert outcome(report, "D4").status is RuleStatus.ABSTAINED


class TestD8DegreeDuration:
    def test_a_four_year_btech_over_four_years_is_clean(self) -> None:
        graph = make_graph([degree("B.Tech.(Hons.)", "IIT Kharagpur", "2022-26")], DOCUMENT)
        report = assemble(graph, bundle(graph))
        assert outcome(report, "D8").status is RuleStatus.CLEAN

    def test_fires_when_the_span_is_not_the_standard_length(self) -> None:
        graph = make_graph([degree("B.Tech.(Hons.)", "IIT Kharagpur", "2022-2028")], DOCUMENT)
        report = assemble(graph, bundle(graph))
        finding = next(f for f in report.discrepancies if f.rule_id == "D8")
        assert finding.tier is Tier.ATTENTION, "a long degree is a question, not a lie"
        assert finding.params["claimed_years"] == 6
        assert finding.params["standard_years"] == 4
        assert "medical leave" in finding.innocent_explanation

    def test_abstains_when_the_degree_carries_no_end_year(self) -> None:
        graph = make_graph([degree("B.Tech.(Hons.)", "IIT Kharagpur", "2022")], DOCUMENT)
        result = outcome(assemble(graph, bundle(graph)), "D8")
        assert result.status is RuleStatus.ABSTAINED
        assert "start and an end" in (result.reason or "")

    def test_abstains_on_a_programme_with_no_standard_length_on_record(self) -> None:
        """Absence of a duration is not evidence of a wrong duration. An unrecognised
        programme abstains rather than being measured against a guess."""
        graph = make_graph([degree("Diplôme d'Ingénieur", "École X", "2022-26")], DOCUMENT)
        result = outcome(assemble(graph, bundle(graph)), "D8")
        assert result.status is RuleStatus.ABSTAINED
        assert "standard duration" in (result.reason or "")


class TestD10InternalContradiction:
    """Decisive without a network call, because the document contradicts ITSELF."""

    def test_the_same_role_dated_two_incompatible_ways(self) -> None:
        graph = make_graph(
            [
                role("Acme", "Jan 2022 - Jun 2022", claim_id="ca1"),
                role("Acme", "Jan 2024 - Jun 2024", claim_id="ca2"),
            ],
            DOCUMENT,
        )
        report = assemble(graph, bundle(graph))
        finding = next(f for f in report.discrepancies if f.rule_id == "D10")
        assert finding.tier is Tier.DECISIVE
        assert finding.finding_id in report.buckets.contradicted
        assert {"ca1", "ca2"} == set(finding.claim_refs)

    def test_two_mentions_that_can_both_be_true_are_not_a_contradiction(self) -> None:
        graph = make_graph(
            [
                role("Acme", "Jan 2022 - Dec 2022", claim_id="ca1"),
                role("Acme", "2022", claim_id="ca2"),
            ],
            DOCUMENT,
        )
        report = assemble(graph, bundle(graph))
        assert not [f for f in report.discrepancies if f.rule_id == "D10"]

    def test_different_roles_are_never_compared(self) -> None:
        """Two different jobs at different times is a career, not a contradiction."""
        graph = make_graph(
            [
                role("Acme", "Jan 2022 - Jun 2022", claim_id="ca1"),
                role("Globex", "Jan 2024 - Jun 2024", claim_id="cb1"),
            ],
            DOCUMENT,
        )
        report = assemble(graph, bundle(graph))
        assert not [f for f in report.discrepancies if f.rule_id == "D10"]

    def test_abstains_with_fewer_than_two_dated_roles(self) -> None:
        graph = make_graph([role("Acme", "2022")], DOCUMENT)
        assert outcome(assemble(graph, bundle(graph)), "D10").status is RuleStatus.ABSTAINED


class TestD11TimelineGap:
    """Displayed, never scored — and the test asserts the never.

    A gap can be illness, caregiving, a visa, a failed venture or a bad market. All of
    them look identical here, so this measures career shape rather than evidence.
    """

    def test_a_long_gap_is_shown_and_barred_from_scoring(self) -> None:
        graph = make_graph(
            [role("Acme", "2020", claim_id="ca1"), role("Globex", "2023", claim_id="cb1")],
            DOCUMENT,
        )
        report = assemble(graph, bundle(graph))
        finding = next(f for f in report.discrepancies if f.rule_id == "D11")
        assert finding.scoring is False
        assert finding.tier is Tier.ATTENTION
        assert finding.params["gap_days"] > 365
        assert finding.finding_id in report.buckets.needs_context
        assert finding.finding_id not in report.buckets.contradicted

    def test_a_normal_handover_between_roles_says_nothing(self) -> None:
        graph = make_graph(
            [
                role("Acme", "Jan 2022 - Jun 2022", claim_id="ca1"),
                role("Globex", "Sep 2022 - Dec 2022", claim_id="cb1"),
            ],
            DOCUMENT,
        )
        report = assemble(graph, bundle(graph))
        assert not [f for f in report.discrepancies if f.rule_id == "D11"]

    def test_abstains_with_one_role(self) -> None:
        graph = make_graph([role("Acme", "2022")], DOCUMENT)
        assert outcome(assemble(graph, bundle(graph)), "D11").status is RuleStatus.ABSTAINED


class TestD12TitleProgression:
    def test_a_jump_of_several_levels_in_months_is_shown_never_scored(self) -> None:
        graph = make_graph(
            [
                role("Acme", "Jan 2022", title="Intern", claim_id="ca1"),
                role("Acme", "Jun 2022", title="VP of Engineering", claim_id="cb1"),
            ],
            DOCUMENT,
        )
        report = assemble(graph, bundle(graph))
        finding = next(f for f in report.discrepancies if f.rule_id == "D12")
        assert finding.scoring is False
        assert finding.params["from"] == "Intern"
        assert finding.finding_id in report.buckets.needs_context

    def test_one_step_up_is_a_career_not_a_question(self) -> None:
        graph = make_graph(
            [
                role("Acme", "Jan 2022", title="Engineer", claim_id="ca1"),
                role("Acme", "Jun 2022", title="Senior Engineer", claim_id="cb1"),
            ],
            DOCUMENT,
        )
        report = assemble(graph, bundle(graph))
        assert not [f for f in report.discrepancies if f.rule_id == "D12"]

    def test_the_same_jump_over_years_is_not_a_question_either(self) -> None:
        graph = make_graph(
            [
                role("Acme", "Jan 2018", title="Intern", claim_id="ca1"),
                role("Acme", "Jun 2024", title="VP of Engineering", claim_id="cb1"),
            ],
            DOCUMENT,
        )
        report = assemble(graph, bundle(graph))
        assert not [f for f in report.discrepancies if f.rule_id == "D12"]

    def test_an_unrecognised_title_is_never_ranked(self) -> None:
        """"Wizard" is not on the ladder, and inventing a level for it would be the
        rule making up the very thing it claims to measure."""
        graph = make_graph(
            [
                role("Acme", "Jan 2022", title="Wizard", claim_id="ca1"),
                role("Acme", "Jun 2022", title="Chief Wizard", claim_id="cb1"),
            ],
            DOCUMENT,
        )
        report = assemble(graph, bundle(graph))
        assert not [f for f in report.discrepancies if f.rule_id == "D12"]


# ---------------------------------------------------------------------------
# Corroboration-only checks. Both can confirm and neither can contradict, and in
# both cases that asymmetry is a fact about GitHub rather than a gap here.
# ---------------------------------------------------------------------------

WORKING_YEAR = (("2024-05", 5), ("2024-06", 40), ("2024-07", 30), ("2024-08", 20),
                ("2024-09", 5))


class TestG10ActivityDuringEmployment:
    def test_activity_spanning_the_role_reaches_the_verified_bucket(self) -> None:
        graph = make_graph([role("Acme", "Jun 2024 - Aug 2024")], DOCUMENT)
        report = assemble(graph, bundle(graph, github=github(windows=WORKING_YEAR)))
        result = outcome(report, "G10")
        assert result.status is RuleStatus.CLEAN
        assert result.note is not None
        assert "90 public contributions across 3 of 3 months" in result.note
        assert result.note in report.buckets.verified

    def test_a_silent_window_is_never_a_finding(self) -> None:
        """The rule this one was written not to be. A salaried job leaves no public
        trace — work code is private — so firing on silence would flag most employed
        developers, exactly the mistake G5's first version made about projects."""
        quiet = (("2024-05", 5), ("2024-06", 0), ("2024-07", 0), ("2024-08", 0),
                 ("2024-09", 5))
        graph = make_graph([role("Acme", "Jun 2024 - Aug 2024")], DOCUMENT)
        report = assemble(graph, bundle(graph, github=github(windows=quiet)))
        result = outcome(report, "G10")
        assert result.status is RuleStatus.ABSTAINED
        assert "work code is normally private" in (result.reason or "")
        assert not [f for f in report.discrepancies if f.rule_id == "G10"]

    def test_says_nothing_about_a_role_the_calendar_does_not_cover(self) -> None:
        graph = make_graph([role("Acme", "Jun 2019 - Aug 2019")], DOCUMENT)
        report = assemble(graph, bundle(graph, github=github(windows=WORKING_YEAR)))
        assert outcome(report, "G10").status is RuleStatus.ABSTAINED

    def test_abstains_without_a_calendar(self) -> None:
        graph = make_graph([role("Acme", "Jun 2024 - Aug 2024")], DOCUMENT)
        report = assemble(graph, bundle(graph, github=github()))
        result = outcome(report, "G10")
        assert result.status is RuleStatus.ABSTAINED
        assert "CVV_GITHUB_TOKEN" in (result.reason or "")


class TestG11OrgMembership:
    def test_a_public_membership_is_evidence_from_outside_the_cv(self) -> None:
        graph = make_graph([role("Vercel", "2024")], DOCUMENT)
        report = assemble(graph, bundle(graph, github=github(orgs=("vercel",))))
        result = outcome(report, "G11")
        assert result.status is RuleStatus.CLEAN
        assert result.note is not None
        assert "'Vercel'" in result.note and "'vercel'" in result.note
        assert result.note in report.buckets.verified

    def test_no_matching_org_is_an_abstention_not_a_finding(self) -> None:
        """Membership is private by default; a real employee is normally invisible
        here. A rule that fired on absence would flag nearly everyone with a job."""
        graph = make_graph([role("Vercel", "2024")], DOCUMENT)
        report = assemble(graph, bundle(graph, github=github(orgs=("kgp-chess-club",))))
        result = outcome(report, "G11")
        assert result.status is RuleStatus.ABSTAINED
        assert "not evidence against the claim" in (result.reason or "")
        assert not [f for f in report.discrepancies if f.rule_id == "G11"]

    def test_an_account_in_no_public_org_abstains_with_the_reason(self) -> None:
        graph = make_graph([role("Vercel", "2024")], DOCUMENT)
        report = assemble(graph, bundle(graph, github=github()))
        result = outcome(report, "G11")
        assert result.status is RuleStatus.ABSTAINED
        assert "hides membership by default" in (result.reason or "")

    def test_abstains_when_the_cv_names_no_employer(self) -> None:
        graph = make_graph([], DOCUMENT)
        report = assemble(graph, bundle(graph, github=github(orgs=("vercel",))))
        assert outcome(report, "G11").status is RuleStatus.ABSTAINED

    def test_a_short_token_never_matches_by_accident(self) -> None:
        """'IT' inside 'kgp-it-society' is not a match. A miss abstains, so strictness
        costs nothing and a false corroboration would cost a great deal."""
        assert not _same_org("IT", "kgp-it-society")
        assert _same_org("Vercel", "vercel")
        assert _same_org("Acme Corporation", "acme-corporation")


URL = "https://github.com/Ashutosh-Ranjan09/{}"


class TestG6StackVsRepository:
    def test_clean_when_one_named_technology_is_in_the_repository(self) -> None:
        """A Next.js application reports to GitHub as TypeScript, so the language
        census alone contradicts every React project ever written. Manifests are read
        alongside it, and one match anywhere settles the claim."""
        graph = make_graph(
            [project("CF-Connect", "May '25 - Jun '25", URL.format("cf-connect"),
                     tech=("Next.js", "MongoDB", "Tailwind CSS"))],
            DOCUMENT,
        )
        gh = github(repos=(repo("cf-connect", languages=("TypeScript", "CSS"),
                                frameworks=("next", "react", "tailwindcss")),))
        report = assemble(graph, bundle(graph, github=gh))
        assert outcome(report, "G6").status is RuleStatus.CLEAN

    def test_fires_only_when_the_repository_contains_none_of_it(self) -> None:
        graph = make_graph(
            [project("Cache", "May '25 - Jun '25", URL.format("cache"),
                     tech=("Go", "Redis"))],
            DOCUMENT,
        )
        gh = github(repos=(repo("cache", languages=("TypeScript",), frameworks=("next",)),))
        report = assemble(graph, bundle(graph, github=gh))
        finding = next(f for f in report.discrepancies if f.rule_id == "G6")
        assert finding.tier is Tier.DECISIVE
        assert finding.params["claimed"] == ["Go", "Redis"]
        assert finding.params["observed"] == ["TypeScript"]
        assert finding.finding_id in report.buckets.contradicted

    def test_a_database_the_manifest_cannot_show_is_never_the_finding(self) -> None:
        """The unfair version of this rule. MongoDB is not a language and is not an
        npm package, so "one technology is missing" would fire on an honest CV."""
        graph = make_graph(
            [project("ATMA", "Mar '25 - Apr '25", URL.format("ATMA-Final"),
                     tech=("React", "MongoDB", "JWT"))],
            DOCUMENT,
        )
        gh = github(repos=(repo("ATMA-Final", languages=("JavaScript", "CSS"),
                                frameworks=("react", "jsonwebtoken")),))
        report = assemble(graph, bundle(graph, github=gh))
        assert not [f for f in report.discrepancies if f.rule_id == "G6"]

    def test_abstains_when_no_language_census_was_gathered(self) -> None:
        """An empty language map means the census was not fetched, never that the
        repository is empty. Conflating them would contradict every project."""
        graph = make_graph(
            [project("Cache", "May '25 - Jun '25", URL.format("cache"), tech=("Go",))],
            DOCUMENT,
        )
        report = assemble(graph, bundle(graph, github=github(repos=(repo("cache"),))))
        assert outcome(report, "G6").status is RuleStatus.ABSTAINED

    def test_abstains_when_no_project_names_a_stack(self) -> None:
        graph = make_graph([project("Cache", "May '25", URL.format("cache"))], DOCUMENT)
        gh = github(repos=(repo("cache", languages=("Go",)),))
        assert outcome(assemble(graph, bundle(graph, github=gh)), "G6").status is (
            RuleStatus.ABSTAINED
        )


def skill_years(years: float, *techs: str) -> object:
    return make_claim(
        SKILLS_LINE, DOCUMENT, claim_id="cskl01", kind=ClaimKind.SKILL,
        skill_refs=list(techs), stated_years=years,
    )


class TestG9LanguageTenure:
    def test_fires_when_an_older_account_shows_the_language_only_late(self) -> None:
        graph = make_graph([skill_years(8, "Python")], DOCUMENT)
        gh = github(created="2015-01-01", first_seen={"Python": "2024-03-01"})
        report = assemble(graph, bundle(graph, github=gh))
        finding = next(f for f in report.discrepancies if f.rule_id == "G9")
        assert finding.tier is Tier.ATTENTION
        assert finding.params["first_evidence"] == 2024
        assert "lower bound on EVIDENCE" in finding.innocent_explanation

    def test_an_account_younger_than_the_claim_is_not_a_witness(self) -> None:
        """The fairness guard, and the whole reason this rule is safe to ship. Eight
        years of Python against a three-year-old account says when they joined
        GitHub, not when they learned Python."""
        graph = make_graph([skill_years(8, "Python")], DOCUMENT)
        gh = github(created="2023-01-01", first_seen={"Python": "2024-03-01"})
        report = assemble(graph, bundle(graph, github=gh))
        result = outcome(report, "G9")
        assert result.status is RuleStatus.ABSTAINED
        assert "younger than the claim" in (result.reason or "")

    def test_evidence_matching_the_claim_is_clean(self) -> None:
        graph = make_graph([skill_years(8, "Python")], DOCUMENT)
        gh = github(created="2015-01-01", first_seen={"Python": "2017-03-01"})
        report = assemble(graph, bundle(graph, github=gh))
        assert outcome(report, "G9").status is RuleStatus.CLEAN

    def test_a_language_never_observed_abstains_rather_than_firing(self) -> None:
        """Guardrail 4. Work code is private and coursework lives elsewhere, so a
        language with no public artefact produces no finding."""
        graph = make_graph([skill_years(8, "Rust")], DOCUMENT)
        gh = github(created="2015-01-01", first_seen={"Python": "2024-03-01"})
        report = assemble(graph, bundle(graph, github=gh))
        assert outcome(report, "G9").status is RuleStatus.ABSTAINED

    def test_abstains_when_no_skill_states_years(self) -> None:
        graph = make_graph([], DOCUMENT)
        gh = github(created="2015-01-01", first_seen={"Python": "2017-03-01"})
        result = outcome(assemble(graph, bundle(graph, github=gh)), "G9")
        assert result.status is RuleStatus.ABSTAINED
        assert "how many years" in (result.reason or "")


EXPERIENCE_DOC = DOCUMENT + " 5+ years of professional experience in software"


class TestD6DurationArithmetic:
    """Attention, and the catalogue's `decisive` is wrong here. A CV need not list
    every role — a page forces the choice — so a stated total larger than the dated
    roles is the ordinary shape of an edited CV rather than a lie."""

    def test_a_stated_total_beyond_the_dated_roles_is_a_question(self) -> None:
        graph = make_graph([role("Acme", "Jan 2022 - Dec 2022")], EXPERIENCE_DOC)
        report = assemble(graph, bundle(graph))
        finding = next(f for f in report.discrepancies if f.rule_id == "D6")
        assert finding.tier is Tier.ATTENTION
        assert finding.params["stated_years"] == 5.0
        assert finding.params["listed_years"] == 1.0
        assert "need not list every role" in finding.innocent_explanation
        assert finding.finding_id in report.buckets.needs_context

    def test_roles_held_at_once_are_merged_before_summing(self) -> None:
        """Two jobs in the same year is one year of experience, not two — max spans,
        merged, which is the reading most generous to the candidate."""
        graph = make_graph(
            [
                role("Acme", "Jan 2020 - Dec 2022", claim_id="ca1"),
                role("Globex", "Jan 2021 - Dec 2021", claim_id="cb1"),
            ],
            EXPERIENCE_DOC,
        )
        report = assemble(graph, bundle(graph))
        finding = next(f for f in report.discrepancies if f.rule_id == "D6")
        assert finding.params["listed_years"] == 3.0

    def test_clean_when_the_dated_roles_cover_the_claim(self) -> None:
        graph = make_graph([role("Acme", "Jan 2018 - Dec 2022")], EXPERIENCE_DOC)
        report = assemble(graph, bundle(graph))
        assert outcome(report, "D6").status is RuleStatus.CLEAN

    def test_abstains_when_the_cv_states_no_total(self) -> None:
        graph = make_graph([role("Acme", "Jan 2022 - Dec 2022")], DOCUMENT)
        result = outcome(assemble(graph, bundle(graph)), "D6")
        assert result.status is RuleStatus.ABSTAINED
        assert "states no total" in (result.reason or "")

    def test_abstains_when_it_states_a_total_but_dates_no_role(self) -> None:
        graph = make_graph([], EXPERIENCE_DOC)
        result = outcome(assemble(graph, bundle(graph)), "D6")
        assert result.status is RuleStatus.ABSTAINED
        assert "dates no role" in (result.reason or "")


class TestD7TechnologyAnachronism:
    """A date against a date — no judgement about a career anywhere in it."""

    def test_fires_when_the_technology_postdates_the_project(self) -> None:
        graph = make_graph([project("Portal", "2011-2012", tech=("React",))], DOCUMENT)
        report = assemble(graph, bundle(graph))
        finding = next(f for f in report.discrepancies if f.rule_id == "D7")
        assert finding.tier is Tier.DECISIVE
        assert finding.params["technology"] == "React"
        assert finding.params["released"] == "2013-05-29"
        assert finding.finding_id in report.buckets.contradicted

    def test_a_year_precision_project_never_fires_on_that_same_year(self) -> None:
        """React shipped in May 2013. A project dated only "2013" ran for all of it
        under the max-span reading, so there is no month at which it is impossible."""
        graph = make_graph([project("Portal", "2013", tech=("React",))], DOCUMENT)
        report = assemble(graph, bundle(graph))
        assert not [f for f in report.discrepancies if f.rule_id == "D7"]

    def test_an_unlisted_technology_is_unknown_not_anachronistic(self) -> None:
        graph = make_graph([project("Portal", "2011", tech=("Chakra UI",))], DOCUMENT)
        report = assemble(graph, bundle(graph))
        assert outcome(report, "D7").status is RuleStatus.CLEAN

    def test_punctuation_never_hides_a_match(self) -> None:
        graph = make_graph([project("Portal", "2014", tech=("next.js",))], DOCUMENT)
        report = assemble(graph, bundle(graph))
        finding = next(f for f in report.discrepancies if f.rule_id == "D7")
        assert finding.params["released"] == "2016-10-25"

    def test_abstains_when_no_project_is_both_dated_and_described(self) -> None:
        graph = make_graph([project("Portal", "2011")], DOCUMENT)
        result = outcome(assemble(graph, bundle(graph)), "D7")
        assert result.status is RuleStatus.ABSTAINED
