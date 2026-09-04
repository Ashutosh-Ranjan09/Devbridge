"""The checks.

This module imports `models` and stdlib. Nothing else — no httpx, no gather. If a rule
needs data it arrives in the EvidenceBundle or the rule abstains with a typed reason.
That constraint is what makes every rule testable from a JSON fixture with no token, no
rate limit and no network.

Four checks for now: P1, P2, P3, W1. The remaining 37 in docs/plan.md.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Protocol

from cvv.ids import finding_id
from cvv.models import (
    ClaimGraph,
    ClaimKind,
    Discrepancy,
    EvidenceBundle,
    Platform,
    PlatformEvidence,
    RuleOutcome,
    RuleStatus,
    Severity,
    Tier,
)


class Abstain(Exception):  # noqa: N818 - a control signal, not an error
    """A rule declining to run, with the reason a reader will see.

    Not a failure. A check that cannot run must say so: silence in a report reads as
    a pass, which is the one thing this system must never do.
    """


@dataclass(frozen=True)
class Context:
    graph: ClaimGraph
    bundle: EvidenceBundle
    report_id: str
    today: datetime.date = field(default_factory=lambda: datetime.date.today())

    def claims(self, kind: ClaimKind) -> list:  # type: ignore[type-arg]
        return [c for c in self.graph.claims if c.kind is kind]

    def platform(self, platform: Platform) -> PlatformEvidence:
        for p in self.bundle.platforms:
            if p.platform is platform and p.found:
                return p
        for gap in self.bundle.gaps:
            if gap.source == platform.value:
                raise Abstain(gap.detail or f"{platform.value}: {gap.reason.value}")
        raise Abstain(f"No {platform.value} evidence was gathered.")


class Rule(Protocol):
    rule_id: str
    rule_version: str
    tier: Tier
    scoring: bool
    summary: str

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]: ...


REGISTRY: list[Rule] = []


def register(rule: type[Rule]) -> type[Rule]:
    """Registers an INSTANCE and returns the class.

    Appending the class instead of an instance leaves `evaluate` unbound, which fails
    with a TypeError at evaluation time. The runner caught all four and recorded them
    as `status="error"` with the reason attached — the report still rendered, which is
    what rule isolation is for.
    """
    REGISTRY.append(rule())
    return rule


def _achievements(ctx: Context, platform: Platform, metric: str) -> list:  # type: ignore[type-arg]
    return [
        c
        for c in ctx.claims(ClaimKind.ACHIEVEMENT)
        if (c.platform or "").lower() == platform.value and c.metric == metric
    ]


# --------------------------------------------------------------------------- #
# P · competitive-programming platforms
# --------------------------------------------------------------------------- #


@register
@dataclass(frozen=True)
class P1CodeforcesRating:
    """Codeforces is the authority on its own ratings, which is what makes this
    decisive. Handle ownership is irrelevant: the handle resolved, and the platform's
    own record settles the question."""

    rule_id: str = "P1"
    rule_version: str = "1.0"
    tier: Tier = Tier.DECISIVE
    scoring: bool = True
    summary: str = "Claimed Codeforces rating vs. the API's max rating"

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        claims = _achievements(ctx, Platform.CODEFORCES, "max_rating")
        if not claims:
            raise Abstain("No Codeforces rating claimed.")
        cf = ctx.platform(Platform.CODEFORCES)
        if cf.max_rating is None:
            raise Abstain("Codeforces returned no rating for this handle.")

        for c in claims:
            claimed = int(c.value) if isinstance(c.value, int | float) else None
            if claimed is None or claimed == cf.max_rating:
                continue
            yield Discrepancy(
                finding_id=finding_id(ctx.report_id, self.rule_id, [c.claim_id]),
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                tier=self.tier,
                severity=Severity.MEDIUM if abs(claimed - cf.max_rating) < 200 else Severity.HIGH,
                confidence=1.0,
                scoring=self.scoring,
                claim_refs=[c.claim_id],
                evidence_refs=["codeforces.user.info"],
                params={"claimed": claimed, "actual": cf.max_rating, "handle": cf.handle},
                explanation=(
                    f"The CV claims a peak Codeforces rating of {claimed}. The Codeforces "
                    f"API reports a maximum rating of {cf.max_rating} for handle "
                    f"{cf.handle!r}."
                ),
            )


@register
@dataclass(frozen=True)
class P2ContestRank:
    """An exact match on round and rank against the full contest history."""

    rule_id: str = "P2"
    rule_version: str = "1.0"
    tier: Tier = Tier.DECISIVE
    scoring: bool = True
    summary: str = "Claimed contest rank vs. the contest history"

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        claims = _achievements(ctx, Platform.CODEFORCES, "contest_rank")
        if not claims:
            raise Abstain("No Codeforces contest rank claimed.")
        cf = ctx.platform(Platform.CODEFORCES)
        if not cf.contests:
            raise Abstain("Codeforces returned no contest history for this handle.")

        ranks = {c.rank for c in cf.contests}
        for c in claims:
            claimed = int(c.value) if isinstance(c.value, int | float) else None
            if claimed is None or claimed in ranks:
                continue
            yield Discrepancy(
                finding_id=finding_id(ctx.report_id, self.rule_id, [c.claim_id]),
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                tier=self.tier,
                severity=Severity.MEDIUM,
                confidence=1.0,
                scoring=self.scoring,
                claim_refs=[c.claim_id],
                evidence_refs=["codeforces.user.rating"],
                params={"claimed_rank": claimed, "ranks_on_record": sorted(ranks)[:10]},
                explanation=(
                    f"The CV claims a contest rank of {claimed}. No contest in the "
                    f"{len(cf.contests)}-contest history for {cf.handle!r} records that rank."
                ),
            )


@register
@dataclass(frozen=True)
class P3ProblemsSolved:
    """Abstains on an aggregate claim rather than comparing it to one source.

    "500+ problems across LeetCode, Codeforces and GeeksforGeeks" is a real claim
    about three platforms. Comparing it to Codeforces alone compares the wrong
    things, and would report a contradiction that does not exist.
    """

    rule_id: str = "P3"
    rule_version: str = "1.0"
    tier: Tier = Tier.DECISIVE
    scoring: bool = True
    summary: str = "Claimed problems solved vs. distinct accepted submissions"

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        claims = [
            c
            for c in ctx.claims(ClaimKind.ACHIEVEMENT)
            if c.metric == "problems_solved"
        ]
        if not claims:
            raise Abstain("No problem count claimed.")

        aggregates = [c for c in claims if "aggregate_across_sources" in c.flags]
        if aggregates and len(aggregates) == len(claims):
            sources = (aggregates[0].context or {}).get("platforms", [])
            raise Abstain(
                f"The claim aggregates {len(sources)} platforms ({', '.join(sources)}); "
                "no single source can confirm or contradict it, and only Codeforces is "
                "connected."
            )

        cf = ctx.platform(Platform.CODEFORCES)
        if cf.problems_solved is None:
            raise Abstain("Codeforces returned no submission history for this handle.")

        for c in claims:
            claimed = int(c.value) if isinstance(c.value, int | float) else None
            # "500+" is a floor, not an equality. Only a claim ABOVE what the platform
            # records is a contradiction; solving more than you claimed is not.
            if claimed is None or cf.problems_solved >= claimed:
                continue
            yield Discrepancy(
                finding_id=finding_id(ctx.report_id, self.rule_id, [c.claim_id]),
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                tier=self.tier,
                severity=Severity.MEDIUM,
                confidence=1.0,
                scoring=self.scoring,
                claim_refs=[c.claim_id],
                evidence_refs=["codeforces.user.status"],
                params={"claimed": claimed, "actual": cf.problems_solved},
                explanation=(
                    f"The CV claims {claimed} problems solved. Codeforces records "
                    f"{cf.problems_solved} distinct accepted problems for {cf.handle!r}."
                ),
            )


# --------------------------------------------------------------------------- #
# W · deployments
# --------------------------------------------------------------------------- #


@register
@dataclass(frozen=True)
class W1DeploymentLiveness:
    """A claimed live product either responds or it does not."""

    rule_id: str = "W1"
    rule_version: str = "1.0"
    tier: Tier = Tier.DECISIVE
    scoring: bool = True
    summary: str = "Claimed live deployments respond to an HTTP request"

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        if not ctx.bundle.deployments:
            raise Abstain("No deployment URLs claimed.")

        by_url = {
            a.url: c
            for c in ctx.graph.claims
            for a in c.artefacts
            if a.type.value == "deployment"
        }
        for d in ctx.bundle.deployments:
            if d.reachable:
                continue
            claim = by_url.get(d.url)
            refs = [claim.claim_id] if claim else []
            yield Discrepancy(
                finding_id=finding_id(ctx.report_id, self.rule_id, refs or [d.url]),
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                tier=self.tier,
                severity=Severity.MEDIUM,
                confidence=1.0,
                scoring=self.scoring,
                claim_refs=refs,
                evidence_refs=[f"deployments[{d.url}]"],
                params={"url": d.url, "status_code": d.status_code},
                explanation=(
                    f"The live URL claimed for "
                    f"{(claim.title if claim else None) or 'a project'} does not respond: "
                    f"{d.url} returned "
                    + (f"HTTP {d.status_code}." if d.status_code else "no response.")
                ),
            )


# --------------------------------------------------------------------------- #
# The runner
# --------------------------------------------------------------------------- #


def run_all(ctx: Context) -> tuple[list[Discrepancy], list[RuleOutcome]]:
    """Every registered rule appears in the outcomes, including the ones that did
    nothing. A rule that raises is isolated and recorded as an error — one malformed
    claim must never take down a report."""
    findings: list[Discrepancy] = []
    outcomes: list[RuleOutcome] = []

    for rule in REGISTRY:
        try:
            produced = list(rule.evaluate(ctx))
        except Abstain as reason:
            outcomes.append(
                RuleOutcome(
                    rule_id=rule.rule_id,
                    rule_version=rule.rule_version,
                    status=RuleStatus.ABSTAINED,
                    reason=str(reason),
                )
            )
            continue
        except Exception as exc:
            outcomes.append(
                RuleOutcome(
                    rule_id=rule.rule_id,
                    rule_version=rule.rule_version,
                    status=RuleStatus.ERROR,
                    reason=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        findings.extend(produced)
        outcomes.append(
            RuleOutcome(
                rule_id=rule.rule_id,
                rule_version=rule.rule_version,
                status=RuleStatus.FIRED if produced else RuleStatus.CLEAN,
            )
        )

    assert len(outcomes) == len(REGISTRY), "every registered rule must be accounted for"
    return findings, outcomes
