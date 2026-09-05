"""The checks.

This module imports `models` and stdlib. Nothing else — no httpx, no gather. If a rule
needs data it arrives in the EvidenceBundle or the rule abstains with a typed reason.
That constraint is what makes every rule testable from a JSON fixture with no token, no
rate limit and no network.

Four checks for now: P1, P2, P3, W1. The remaining 37 in docs/plan.md.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Protocol

from cvv.ids import finding_id
from cvv.intervals import bounds
from cvv.models import (
    ClaimGraph,
    ClaimKind,
    Discrepancy,
    EvidenceBundle,
    GapReason,
    GitHubEvidence,
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

    def github(self) -> GitHubEvidence:
        if self.bundle.github is not None:
            return self.bundle.github
        for gap in self.bundle.gaps:
            if gap.source == "github":
                raise Abstain(gap.detail or f"github: {gap.reason.value}")
        raise Abstain("No GitHub evidence was gathered.")

    def named_repos(self) -> dict[str, str]:
        """Repository name -> the claim that named it."""
        return {
            a.url.rstrip("/").split("/")[-1]: c.claim_id
            for c in self.graph.claims
            for a in c.artefacts
            if a.type.value == "repo"
        }


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


_ROUND = re.compile(r"\bround\s+#?(\d{2,4})\b", re.I)


def _round_number(text: str) -> int | None:
    """The contest number out of "Codeforces Round 998 (Div. 3)".

    Read from the claim's own verbatim rather than a model-supplied field: the model
    controls its fields, but it cannot alter text it copied from the document.
    """
    m = _ROUND.search(text)
    return int(m[1]) if m else None


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
    """Claimed peak rating against the API's max.

    Two asymmetries, both deliberate.

    **Direction.** `max_rating` is a peak and only ever rises, so a CV written six
    months ago saying 1495 will disagree with an API now reporting 1550 — and the
    candidate UNDERSTATED. That is never a finding. Understating is not penalised
    anywhere in this design: the reference event batch records a candidate who claimed
    "familiar" with TypeScript while having shipped 335 KB as corroboration exceeding
    the claim.

    **Bandwidth, on the firing side only.** Codeforces rerates contests after cheat
    removals, days later, so a rating recorded shortly after a contest can shift by
    tens of points. A small overstatement is consistent with a stale snapshot; a large
    one is not. The band picks the TIER, never whether to report — suppressing a
    factual mismatch would be the system deciding what is significant, which is the
    reviewer's job.

    `band` is a documented prior to be swept in the evaluation, not a fitted constant.
    """

    rule_id: str = "P1"
    rule_version: str = "2.0"
    tier: Tier = Tier.DECISIVE
    soft_tier: Tier = Tier.ATTENTION
    band: int = 30  # rating points; rejudging moves a rating by tens, not hundreds
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
            if claimed is None or cf.max_rating >= claimed:
                continue  # the record is at least as good as the claim

            overstated = claimed - cf.max_rating
            soft = overstated <= self.band
            yield Discrepancy(
                finding_id=finding_id(ctx.report_id, self.rule_id, [c.claim_id]),
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                tier=self.soft_tier if soft else self.tier,
                severity=Severity.INFO if soft else Severity.HIGH,
                confidence=1.0,
                scoring=self.scoring,
                claim_refs=[c.claim_id],
                evidence_refs=["codeforces.user.info"],
                params={
                    "claimed": claimed,
                    "actual": cf.max_rating,
                    "overstated_by": overstated,
                    "handle": cf.handle,
                },
                explanation=(
                    f"The CV claims a peak Codeforces rating of {claimed}. The API "
                    f"reports a maximum of {cf.max_rating} for {cf.handle!r} — "
                    f"{overstated} points lower."
                ),
                innocent_explanation=(
                    "Codeforces rerates contests after cheat removals, sometimes days "
                    "later, so a rating copied shortly after a contest can be a few "
                    "points above the settled value."
                )
                if soft
                else None,
            )


@register
@dataclass(frozen=True)
class P2ContestRank:
    """Match the NAMED contest first, then compare ranks within it.

    An earlier version asked only whether the claimed rank appeared anywhere in the
    history. Against a real CV that produced a technically true and useless finding:
    "no contest records rank 1106". The account had in fact competed in the very
    contest named, placing 1109 — three places out.

    Saying "claimed 1106 in Round 998, the API records 1109" lets a reviewer see in
    one line that this is a standings-timing artefact and not a fabrication. Codeforces
    ranks move after system testing and after cheat removals, and a CV written from
    the live standings can be a few places off. Severity scales with the size of the
    gap, because a three-place difference on 1100 is not the same claim as saying 100
    when the record says 5000.
    """

    rule_id: str = "P2"
    rule_version: str = "3.0"
    tier: Tier = Tier.DECISIVE
    soft_tier: Tier = Tier.ATTENTION
    band: float = 0.02  # relative; three places matters at rank 4, not at rank 1100
    scoring: bool = True
    summary: str = "Claimed contest rank vs. the contest history"

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        claims = _achievements(ctx, Platform.CODEFORCES, "contest_rank")
        if not claims:
            raise Abstain("No Codeforces contest rank claimed.")
        cf = ctx.platform(Platform.CODEFORCES)
        if not cf.contests:
            raise Abstain("Codeforces returned no contest history for this handle.")

        for claim in claims:
            claimed = int(claim.value) if isinstance(claim.value, int | float) else None
            if claimed is None:
                continue

            # The contest is identified from the claim's OWN span, not from a model
            # field — guardrail 7. "Codeforces Round 998 (Div. 3)" gives 998.
            round_no = _round_number(claim.provenance.verbatim)
            match = None
            if round_no is not None:
                match = next(
                    (c for c in cf.contests if _round_number(c.name) == round_no), None
                )

            if match is None:
                if any(c.rank == claimed for c in cf.contests):
                    continue  # the rank is on record, just not tied to a named round
                yield Discrepancy(
                    finding_id=finding_id(ctx.report_id, self.rule_id, [claim.claim_id]),
                    rule_id=self.rule_id,
                    rule_version=self.rule_version,
                    tier=self.tier,
                    severity=Severity.MEDIUM,
                    confidence=1.0,
                    scoring=self.scoring,
                    claim_refs=[claim.claim_id],
                    evidence_refs=["codeforces.user.rating"],
                    params={"claimed_rank": claimed, "contests_on_record": len(cf.contests)},
                    explanation=(
                        f"The CV claims a contest rank of {claimed}. No contest in the "
                        f"{len(cf.contests)}-contest rated history for {cf.handle!r} "
                        "records that rank, and the contest named could not be matched."
                    ),
                )
                continue

            # Lower is better. A recorded rank at least as good as the claim is not
            # a finding — the candidate understated, or the standings improved after
            # rejudging.
            if match.rank <= claimed:
                continue

            delta = match.rank - claimed
            relative = delta / max(match.rank, 1)
            soft = relative <= self.band
            severity = (
                Severity.INFO if soft else Severity.MEDIUM if relative < 0.25 else Severity.HIGH
            )
            yield Discrepancy(
                finding_id=finding_id(ctx.report_id, self.rule_id, [claim.claim_id]),
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                tier=self.soft_tier if soft else self.tier,
                severity=severity,
                confidence=1.0,
                scoring=self.scoring,
                claim_refs=[claim.claim_id],
                evidence_refs=["codeforces.user.rating"],
                params={
                    "contest": match.name,
                    "claimed_rank": claimed,
                    "actual_rank": match.rank,
                    "difference": delta,
                },
                explanation=(
                    f"The CV claims rank {claimed} in {match.name}. The Codeforces API "
                    f"records rank {match.rank} for {cf.handle!r} in that contest — "
                    f"{delta} " + ("place" if delta == 1 else "places") + " lower."
                ),
                innocent_explanation=(
                    "Ranks shift after system testing and after cheat removals, so a CV "
                    "written from the live standings can be a few places out."
                )
                if soft
                else None,
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


# --------------------------------------------------------------------------- #
# G · GitHub
# --------------------------------------------------------------------------- #


@register
@dataclass(frozen=True)
class G2AccountExists:
    """The simplest decisive check in the system: does the account resolve at all."""

    rule_id: str = "G2"
    rule_version: str = "1.0"
    tier: Tier = Tier.DECISIVE
    scoring: bool = True
    summary: str = "The GitHub account named on the CV exists"

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        for gap in ctx.bundle.gaps:
            if gap.source == "github" and gap.reason is GapReason.NOT_FOUND:
                yield Discrepancy(
                    finding_id=finding_id(ctx.report_id, self.rule_id, []),
                    rule_id=self.rule_id,
                    rule_version=self.rule_version,
                    tier=self.tier,
                    severity=Severity.HIGH,
                    confidence=1.0,
                    scoring=self.scoring,
                    claim_refs=[
                        c.claim_id for c in ctx.claims(ClaimKind.PROFILE)
                        if (c.platform or "") == "github"
                    ],
                    evidence_refs=["github.users"],
                    params={"detail": gap.detail},
                    explanation=gap.detail or "The GitHub account does not exist.",
                )
                return
        ctx.github()  # abstains with the gap's reason if there is no evidence at all


@register
@dataclass(frozen=True)
class G4RepoExistsOwnedNotFork:
    """Three facts about a named repository, each settled by the API.

    A fork is the one that matters most: presenting someone else's work as a project
    is a different claim from writing it, and GitHub records the distinction.
    """

    rule_id: str = "G4"
    rule_version: str = "1.0"
    tier: Tier = Tier.DECISIVE
    scoring: bool = True
    summary: str = "Named repositories exist, are owned, and are not forks"

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        gh = ctx.github()
        if not gh.repos:
            raise Abstain("No repositories named on the CV.")
        by_claim = ctx.named_repos()

        for repo in gh.repos:
            refs = [by_claim[repo.name]] if repo.name in by_claim else []
            common = {
                "rule_id": self.rule_id,
                "rule_version": self.rule_version,
                "tier": self.tier,
                "confidence": 1.0,
                "scoring": self.scoring,
                "claim_refs": refs,
                "evidence_refs": [f"github.repos[{repo.name}]"],
            }
            if not repo.exists:
                yield Discrepancy(
                    finding_id=finding_id(ctx.report_id, self.rule_id, [repo.name]),
                    severity=Severity.HIGH,
                    params={"repo": repo.name},
                    explanation=(
                        f"The repository {repo.name!r} named on the CV does not exist at "
                        f"github.com/{gh.handle}/{repo.name}."
                    ),
                    **common,  # type: ignore[arg-type]
                )
            elif repo.is_fork:
                yield Discrepancy(
                    finding_id=finding_id(ctx.report_id, self.rule_id, [repo.name, "fork"]),
                    severity=Severity.HIGH,
                    params={"repo": repo.name, "is_fork": True},
                    explanation=(
                        f"{repo.name!r} is a fork of another repository, not original work."
                    ),
                    **common,  # type: ignore[arg-type]
                )
            elif repo.owner_matches is False:
                yield Discrepancy(
                    finding_id=finding_id(ctx.report_id, self.rule_id, [repo.name, "owner"]),
                    severity=Severity.MEDIUM,
                    params={"repo": repo.name},
                    explanation=f"{repo.name!r} is not owned by {gh.handle!r}.",
                    **common,  # type: ignore[arg-type]
                )


@register
@dataclass(frozen=True)
class G5ActivityDuringClaimedWindow:
    """Was the account active when the CV says the work happened?

    Reads the contributions calendar, never repo.created_at. Measured on a real CV:
    the ATMA project claims Mar-Apr 2025 and its repository was created 2025-06-24 —
    two months later — which a created_at comparison would report as a contradiction.
    The calendar records 20 contributions across March and April. The repository was
    pushed after the work, which is what a course project looks like.

    ATTENTION, not decisive, and the catalogue's `decisive` is wrong here. The
    calendar excludes private contributions unless the account owner opted in, so a
    quiet window means "no PUBLIC activity", never "no work".
    """

    rule_id: str = "G5"
    rule_version: str = "1.0"
    tier: Tier = Tier.ATTENTION
    scoring: bool = True
    summary: str = "Account activity during the claimed project window"

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        gh = ctx.github()
        if not gh.contribution_windows:
            raise Abstain(
                "No contributions calendar was gathered. It needs an authenticated "
                "GraphQL request; set CVV_GITHUB_TOKEN."
            )
        covered_from = min(w.start for w in gh.contribution_windows)
        covered_to = max(w.end for w in gh.contribution_windows)

        for claim in ctx.claims(ClaimKind.PROJECT):
            if claim.interval is None:
                continue
            lo = bounds(claim.interval.start)[0]
            hi = bounds(claim.interval.end or claim.interval.start)[1]
            if lo < covered_from or hi > covered_to:
                continue  # the calendar does not cover it; no claim either way

            total = sum(
                w.commit_count
                for w in gh.contribution_windows
                if w.start <= hi and lo <= w.end
            )
            if total > 0:
                continue

            yield Discrepancy(
                finding_id=finding_id(ctx.report_id, self.rule_id, [claim.claim_id]),
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                tier=self.tier,
                severity=Severity.LOW,
                confidence=0.5,
                scoring=self.scoring,
                claim_refs=[claim.claim_id],
                evidence_refs=["github.contribution_windows"],
                params={"project": claim.title, "window": f"{lo} .. {hi}", "contributions": 0},
                explanation=(
                    f"{claim.title!r} is dated {lo:%b %Y} to {hi:%b %Y}, and GitHub records "
                    f"no public contributions from {gh.handle!r} in that period."
                ),
                innocent_explanation=(
                    "The contributions calendar counts only public activity unless the "
                    "account owner has enabled private contributions. Work done in a "
                    "private repository, on an institutional system, or pushed later "
                    "leaves no trace here."
                ),
            )


@register
@dataclass(frozen=True)
class G7RepoSubstance:
    """Is there anything in the repository but a README?

    Deliberately not a size or commit-count threshold. Those encode an opinion about
    how big a project should be, which differs by institution, language and year, and
    a two-file Python program is a program.
    """

    rule_id: str = "G7"
    rule_version: str = "1.0"
    tier: Tier = Tier.DECISIVE
    scoring: bool = True
    summary: str = "Named repositories contain more than a README"

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        gh = ctx.github()
        present = [r for r in gh.repos if r.exists and r.is_readme_only is not None]
        if not present:
            raise Abstain("No repository contents were gathered.")
        by_claim = ctx.named_repos()

        for repo in present:
            if not repo.is_readme_only:
                continue
            yield Discrepancy(
                finding_id=finding_id(ctx.report_id, self.rule_id, [repo.name]),
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                tier=self.tier,
                severity=Severity.MEDIUM,
                confidence=1.0,
                scoring=self.scoring,
                claim_refs=[by_claim[repo.name]] if repo.name in by_claim else [],
                evidence_refs=[f"github.repos[{repo.name}]"],
                params={"repo": repo.name, "size_kb": repo.size_kb},
                explanation=(
                    f"{repo.name!r} is presented as a project but contains no files "
                    "beyond a README and boilerplate."
                ),
            )


@register
@dataclass(frozen=True)
class G8PortfolioComposition:
    """What proportion of the account is forked rather than written.

    Attention tier: forking is a normal way to learn and to contribute, and a high
    ratio is a question rather than a finding.
    """

    rule_id: str = "G8"
    rule_version: str = "1.0"
    tier: Tier = Tier.ATTENTION
    scoring: bool = True
    summary: str = "Proportion of the account that is forked rather than original"
    threshold: float = 0.75

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        gh = ctx.github()
        if gh.public_repo_count is None:
            raise Abstain("The account's repository list was not gathered.")
        if not gh.public_repos:
            raise Abstain("The account has no public repositories to compose.")

        forks = sum(1 for r in gh.public_repos if r.is_fork)
        ratio = forks / len(gh.public_repos)
        if ratio < self.threshold:
            return

        yield Discrepancy(
            finding_id=finding_id(ctx.report_id, self.rule_id, []),
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            tier=self.tier,
            severity=Severity.LOW,
            confidence=0.6,
            scoring=self.scoring,
            claim_refs=[],
            evidence_refs=["github.public_repos"],
            params={"forks": forks, "total": len(gh.public_repos), "ratio": round(ratio, 2)},
            explanation=(
                f"{forks} of {len(gh.public_repos)} public repositories on "
                f"{gh.handle!r} are forks of other people's work."
            ),
            innocent_explanation=(
                "Forking is how contributions to other projects begin, and how most "
                "people follow a tutorial. A high ratio says the account is used for "
                "reading and contributing, not that the named projects are not the "
                "candidate's own — those are checked separately by G4."
            ),
        )
