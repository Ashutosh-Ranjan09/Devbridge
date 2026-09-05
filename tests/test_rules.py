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
    EvidenceBundle,
    Gap,
    GapReason,
    GitHubEvidence,
    Ownership,
    Platform,
    PlatformEvidence,
    RepoEvidence,
    RuleStatus,
    Tier,
)
from cvv.report import assemble
from cvv.rules import REGISTRY
from tests.cvdata import AGGREGATE, CF_RANK, CF_RATING, DOCUMENT, make_claim, make_graph

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
) -> RepoEvidence:
    return RepoEvidence(
        name=name,
        exists=exists,
        is_fork=is_fork,
        owner_matches=owner_matches,
        is_readme_only=readme_only,
        created_at=datetime.date.fromisoformat(created),
        first_commit=None,  # no trustworthy server-side value exists
    )


def github(
    *,
    repos: tuple[RepoEvidence, ...] = (),
    public: tuple[RepoEvidence, ...] = (),
    windows: tuple[tuple[str, int], ...] = (),
) -> GitHubEvidence:
    return GitHubEvidence(
        handle="Ashutosh-Ranjan09",
        ownership=Ownership.CLAIMED_UNVERIFIED,
        account_created=datetime.date(2024, 6, 29),
        repos=list(repos),
        public_repos=list(public or repos),
        public_repo_count=len(public or repos),
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


def project(title: str, dates: str, repo_url: str = "") -> object:
    interval = parse_interval(dates)
    assert interval is not None, dates
    return make_claim(
        CF_RATING,
        DOCUMENT,
        claim_id="c" + title[:6].lower().replace(" ", ""),
        kind=ClaimKind.PROJECT,
        title=title,
        interval=interval,
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
