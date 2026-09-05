"""The checks, against recorded evidence. No network.

conventions: connectors are tested from recorded responses, so a test run needs no
token, hits no rate limit, and does not fail when Codeforces has an outage — which it
did, mid-spike.
"""

from __future__ import annotations

import datetime

import pytest

from cvv.models import (
    Artefact,
    ArtefactType,
    ClaimKind,
    ContestResult,
    DeploymentEvidence,
    EvidenceBundle,
    Gap,
    GapReason,
    Platform,
    PlatformEvidence,
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
    graph, *, platforms=(), deployments=(), gaps=()
) -> EvidenceBundle:
    return EvidenceBundle(
        bundle_id="eb_test",
        graph_id=graph.graph_id,
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
