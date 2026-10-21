"""The checks.

This module imports `models` and stdlib. Nothing else — no httpx, no gather. If a rule
needs data it arrives in the EvidenceBundle or the rule abstains with a typed reason.
That constraint is what makes every rule testable from a JSON fixture with no token, no
rate limit and no network.

Four checks for now: P1, P2, P3, W1. The remaining 37 in docs/plan.md.
"""

from __future__ import annotations

import calendar
import datetime
import itertools
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Protocol, cast

from rapidfuzz import fuzz

from cvv.filters import is_aggregate
from cvv.ids import finding_id
from cvv.intervals import (
    Rel,
    bounds,
    core_span,
    gap_between,
    max_span,
    merge_non_overlapping,
    overlap,
)
from cvv.logs import get
from cvv.models import (
    ArtefactType,
    Claim,
    ClaimGraph,
    ClaimKind,
    Discrepancy,
    DocumentInfo,
    EmploymentType,
    EvidenceBundle,
    FuzzyDate,
    GapReason,
    GitHubEvidence,
    Interval,
    Ownership,
    Platform,
    PlatformEvidence,
    Precision,
    RuleOutcome,
    RuleStatus,
    Severity,
    Tier,
)
from cvv.reference import (
    department_matches,
    named_scheme,
    programme_years,
    roll_schemes,
    tech_releases,
)
from cvv.reference import (
    normalise_tech as _norm,
)

# Contest names differ in punctuation and in how much of the title a CV bothers to
# copy, never in their number — which the numeral guard above checks separately.
CONTEST_THRESHOLD = 85

log = get("cvv.rules")


class Abstain(Exception):  # noqa: N818 - a control signal, not an error
    """A rule declining to run, with the reason a reader will see.

    Not a failure. A check that cannot run must say so: silence in a report reads as
    a pass, which is the one thing this system must never do.
    """


class Corroborated(Exception):  # noqa: N818 - a control signal, not an error
    """A rule finishing with something POSITIVE to say.

    Some checks can only ever confirm. GitHub organisation membership is private by
    default, so its presence is real evidence and its absence is the ordinary state
    of an honest employee — a rule reading it must be able to report the first
    without inventing the second. `Corroborated` is how it says so: the outcome is
    CLEAN, and the message reaches the reader in the `verified` bucket.
    """


@dataclass(frozen=True)
class Context:
    graph: ClaimGraph
    bundle: EvidenceBundle
    report_id: str
    document: DocumentInfo | None = None
    today: datetime.date = field(default_factory=lambda: datetime.date.today())

    def claims(self, kind: ClaimKind) -> list[Claim]:
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
        """Repository name -> the claim that named it, by bare name and by owner/name.

        The bare name is how a repository under the named account is recorded; the
        owner/name form is how one linked under another account is.
        """
        out: dict[str, str] = {}
        for c in self.graph.claims:
            for a in c.artefacts:
                if a.type.value != "repo":
                    continue
                path = a.url.rstrip("/").split("github.com/", 1)[-1]
                out[path.split("/")[-1]] = c.claim_id
                out[path] = c.claim_id
        return out


class Rule(Protocol):
    rule_id: str
    rule_version: str
    tier: Tier
    scoring: bool
    summary: str

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]: ...


REGISTRY: list[Rule] = []


def register[R](rule: type[R]) -> type[R]:
    """Registers an INSTANCE and returns the class.

    Appending the class instead of an instance leaves `evaluate` unbound, which fails
    with a TypeError at evaluation time. The runner caught all four and recorded them
    as `status="error"` with the reason attached — the report still rendered, which is
    what rule isolation is for.
    """
    REGISTRY.append(cast("Rule", rule()))
    return rule


def same_contest(claimed: str, actual: str) -> bool:
    """Is this the same contest, named two ways?

    Platform-agnostic by construction: a contest is identified by its name, and the
    LARGEST number in that name is what makes it this contest rather than the one
    before it. Divisions, stages and parts are small; a year, where one appears at
    all, appears in the platform's record rather than in what a CV copies. So the
    guard is: the biggest number the CV writes must be present in the recorded name.

    That handles both directions of partial naming, which a subset rule does not:

        "Codeforces Round 998"           vs  "Codeforces Round 998 (Div. 3)"   same
        "Codeforces Round 998 (Div. 3)"  vs  "Codeforces Round 998"            same
        "Meta Hacker Cup Round 2"        vs  "Meta Hacker Cup 2024 Round 2"    same
        "Codeforces Round 99"            vs  "Codeforces Round 998 (Div. 3)"   different
        "AtCoder Beginner Contest 350"   vs  "AtCoder Beginner Contest 351"    different
        "Codeforces Round 998 (Div. 3)"  vs  "Codeforces Round 3"              different

    It is also what makes the fuzzy tier safe. Every "different" row above scores far
    above any workable similarity threshold — one digit barely moves a ratio, and the
    digit is the whole of the identity.
    """
    a, b = _norm_contest(claimed), _norm_contest(actual)
    if not a or not b:
        return False
    if a == b:
        return True
    claimed_numbers = [int(n) for n in re.findall(r"\d+", a)]
    if claimed_numbers and str(max(claimed_numbers)) not in re.findall(r"\d+", b):
        return False
    return fuzz.token_set_ratio(a, b) >= CONTEST_THRESHOLD


def _norm_contest(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _achievements(ctx: Context, platform: Platform, metric: str) -> list[Claim]:
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
    r"""Match the NAMED contest first, then compare ranks within it.

    An earlier version asked only whether the claimed rank appeared anywhere in the
    history. Against a real CV that produced a technically true and useless finding:
    "no contest records rank 1106". The account had in fact competed in the very
    contest named, placing 1109 — three places out.

    Version 4 stops reading the contest out of the sentence with a regex. That regex
    was `round\s+#?(\d{2,4})`, which is a Codeforces naming convention and nothing
    more: it returned None for "AtCoder Beginner Contest 350", "LeetCode Weekly
    Contest 380", "ICPC Amritapuri Regionals 2024" and even "Meta Hacker Cup Round
    2". Every one of those claims fell to the weaker "is this rank anywhere in the
    history" path, silently, on a CV that had done nothing wrong. The contest is now
    a model field verified against the claim's own span, and matching is by NAME —
    which is what a contest is identified by on every platform.

    Saying "claimed 1106 in Round 998, the API records 1109" lets a reviewer see in
    one line that this is a standings-timing artefact and not a fabrication. Codeforces
    ranks move after system testing and after cheat removals, and a CV written from
    the live standings can be a few places off. Severity scales with the size of the
    gap, because a three-place difference on 1100 is not the same claim as saying 100
    when the record says 5000.
    """

    rule_id: str = "P2"
    rule_version: str = "4.0"
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

            # The contest name reached `context` only by appearing in this claim's
            # own span — guardrail 7 is enforced at extraction, not here.
            named = (claim.context or {}).get("contest")
            match = None
            if isinstance(named, str) and named:
                match = next((c for c in cf.contests if same_contest(named, c.name)), None)

            if match is None:
                # The lenient fallback belongs only to a claim that names no contest.
                # It existed because the old regex failed to identify one on most
                # platforms, and leaving it in place now would undo the matching: a
                # CV claiming rank 1106 IN ROUND 998 is making a claim about Round
                # 998, and holding 1106 in some other contest does not support it.
                if not named and any(c.rank == claimed for c in cf.contests):
                    continue
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
                    params={
                        "claimed_rank": claimed,
                        "contest": named,
                        "contests_on_record": len(cf.contests),
                    },
                    explanation=(
                        f"The CV claims a contest rank of {claimed}"
                        + (f" in {named!r}" if named else "")
                        + f". No contest in the {len(cf.contests)}-contest rated history "
                        f"for {cf.handle!r} records that rank"
                        + (", and no contest of that name is in it." if named else ".")
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
    """Codeforces' problem count, and nothing else's.

    Abstains on an aggregate claim rather than comparing it to one source: "500+
    problems across LeetCode, Codeforces and GeeksforGeeks" is a real claim about
    three platforms, and comparing it to Codeforces alone compares the wrong things.

    Version 1 then did precisely that in a way its own docstring had warned about. It
    took EVERY `problems_solved` claim, whatever platform it named, and measured it
    against Codeforces — so "Solved 800 problems on LeetCode" on an honest CV was
    contradicted, decisively, by a Codeforces count of 412. The mutation harness found
    it: a LeetCode mutation aimed at P4 fired P3 as collateral, and collateral is
    exactly the signal it exists to surface.

    A count naming another platform now belongs to that platform's check, and P3
    abstains rather than reaching for the only connector it happens to have.
    """

    rule_id: str = "P3"
    rule_version: str = "2.0"
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

        # Guardrail 7, one level up: a claim is compared against the platform it
        # NAMES, never against the platform we happen to have a connector for.
        mine = [
            c
            for c in claims
            if (c.platform or "").lower() == Platform.CODEFORCES.value and c not in aggregates
        ]
        if not mine:
            named = sorted({(c.platform or "unattributed") for c in claims})
            raise Abstain(
                "No problem count is attributed to Codeforces — the CV names "
                f"{', '.join(named)}. A count belongs to its own platform's check."
            )

        cf = ctx.platform(Platform.CODEFORCES)
        if cf.problems_solved is None:
            raise Abstain("Codeforces returned no submission history for this handle.")

        for c in mine:
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


@register
@dataclass(frozen=True)
class P4LeetCodeStatistics:
    """Claimed LeetCode counts and rating against the platform's own record.

    Decisive on problems solved, for the same reason P1 is decisive on rating: the
    platform is the authority on its own numbers, and no innocent reading makes 800
    accepted problems out of 300.

    The direction asymmetry from P1 applies here too — solving MORE than claimed is
    never a finding — and one addition specific to LeetCode. It publishes a live
    contest rating and no peak, so a CV recording a rating that has since fallen is
    reporting something that was true when written. Rating therefore gets a band, and
    a small overstatement is `attention`, never a contradiction.
    """

    rule_id: str = "P4"
    rule_version: str = "1.0"
    tier: Tier = Tier.DECISIVE
    soft_tier: Tier = Tier.ATTENTION
    band: int = 100  # LeetCode contest ratings move by this much in a single contest
    scoring: bool = True
    summary: str = "Claimed LeetCode statistics vs. the platform's own record"

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        solved = _achievements(ctx, Platform.LEETCODE, "problems_solved")
        rated = _achievements(ctx, Platform.LEETCODE, "max_rating")
        if not solved and not rated:
            raise Abstain("No LeetCode statistic is claimed.")
        lc = ctx.platform(Platform.LEETCODE)

        checked = False
        for c in solved:
            claimed = int(c.value) if isinstance(c.value, int | float) else None
            if claimed is None:
                continue
            if is_aggregate(c.provenance.verbatim):
                continue  # the number belongs to several platforms; P3 says so
            if lc.problems_solved is None:
                continue
            checked = True
            if lc.problems_solved >= claimed:
                continue  # solving more than claimed is never a finding

            yield Discrepancy(
                finding_id=finding_id(ctx.report_id, self.rule_id, [c.claim_id]),
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                tier=self.tier,
                severity=Severity.HIGH,
                confidence=1.0,
                scoring=self.scoring,
                claim_refs=[c.claim_id],
                evidence_refs=["leetcode.matchedUser.submitStatsGlobal"],
                params={
                    "claimed": claimed,
                    "actual": lc.problems_solved,
                    "overstated_by": claimed - lc.problems_solved,
                    "handle": lc.handle,
                },
                explanation=(
                    f"The CV claims {claimed} problems solved on LeetCode. The account "
                    f"{lc.handle!r} has {lc.problems_solved} accepted."
                ),
            )

        for c in rated:
            claimed = int(c.value) if isinstance(c.value, int | float) else None
            if claimed is None or lc.current_rating is None:
                continue
            checked = True
            if lc.current_rating >= claimed:
                continue
            overstated = claimed - lc.current_rating
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
                evidence_refs=["leetcode.userContestRanking"],
                params={
                    "claimed": claimed,
                    "actual": lc.current_rating,
                    "overstated_by": overstated,
                    "handle": lc.handle,
                },
                explanation=(
                    f"The CV claims a LeetCode contest rating of {claimed}. The platform "
                    f"reports {lc.current_rating} for {lc.handle!r} right now."
                ),
                innocent_explanation=(
                    "LeetCode publishes a live rating and no peak, so a CV written when "
                    "the rating was higher is reporting something that was true then. "
                    "A single contest moves a rating by this much."
                )
                if soft
                else None,
            )

        if not checked:
            raise Abstain("LeetCode returned no statistic matching what the CV claims.")


@register
@dataclass(frozen=True)
class P6CrossPlatformHandle:
    """The same handle across platforms, as corroboration of one public identity.

    Corroboration only, and the catalogue's "handles inconsistent across platforms"
    is not a check this system can fairly run. People pick different names on
    different sites for a hundred reasons — the one they wanted was taken, they made
    the account eight years apart, they changed how they present their name. Nothing
    about that is evidence of anything, and a finding there would penalise a habit
    rather than a claim.

    Reusing one handle IS mildly informative: each platform independently confirms an
    account under that name, so the accounts corroborate each other, and a reviewer
    tracing the candidate elsewhere has a name that works.
    """

    rule_id: str = "P6"
    rule_version: str = "1.0"
    tier: Tier = Tier.ATTENTION
    scoring: bool = False  # a naming habit is not evidence about a person
    summary: str = "One handle reused across platforms (displayed, never scored)"

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        found = [p for p in ctx.bundle.platforms if p.found]
        if len(found) < 2:
            raise Abstain(
                "Fewer than two platforms resolved, so there is no cross-platform "
                "identity to observe."
            )

        by_handle: dict[str, list[str]] = {}
        for p in found:
            by_handle.setdefault(p.handle.lower(), []).append(p.platform.value)

        shared = {h: ps for h, ps in by_handle.items() if len(ps) > 1}
        if not shared:
            raise Abstain(
                "Each platform uses a different handle, which is ordinary and is not "
                "a finding: the name someone wanted was taken, or the accounts are "
                "years apart. Nothing is concluded from it."
            )
        raise Corroborated(
            "One public identity across platforms — "
            + "; ".join(
                f"{handle!r} resolves on {' and '.join(sorted(ps))}"
                for handle, ps in sorted(shared.items())
            )
        )
        yield  # pragma: no cover - unreachable; keeps the generator signature


# --------------------------------------------------------------------------- #
# W · deployments
# --------------------------------------------------------------------------- #


@register
@dataclass(frozen=True)
class W1DeploymentLiveness:
    """A claimed live product either responds or it does not — and whose is it?

    Liveness alone proves less than it appears to. `https://atma-ar.vercel.app`
    returning 200 says a site exists at that address; it says nothing about the
    candidate, and any URL beside any repository would pass. Nothing in the system
    checked the PAIRING the CV asserts: this project, that repository, this live link.

    So when every URL responds, the rule looks for the link in GitHub's own record —
    the repository's declared `homepage`, which the owner sets or a deployment
    integration writes. Corroboration only: most people never fill that field in, and
    its absence is the ordinary case rather than evidence of anything. Presence ties
    the three together from a source that is not the CV.

    What this is NOT is W2. Whether the thing behind the URL does what the CV
    describes needs a person to look at a screen, and the worksheet asks them to.
    """

    rule_id: str = "W1"
    rule_version: str = "3.0"
    tier: Tier = Tier.DECISIVE
    soft_tier: Tier = Tier.ATTENTION
    # The only answers that say the deployment is GONE. Everything else that fails —
    # a refusal, a login wall, a server error — is the host answering something
    # other than "nothing here".
    gone: frozenset[int] = frozenset({404, 410})
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

        # Built as a list, not yielded straight out: `Corroborated` below is raised
        # only when nothing fired, and a generator that yields before raising loses
        # everything it yielded.
        #
        # Version 2 called every failure decisive, a timeout included. A timeout is
        # this machine's network as much as the site's, and a 403 is very often a
        # bot-protection layer refusing an automated request that a person's browser
        # would be shown the site for. Neither says the product is not there.
        findings: list[Discrepancy] = []
        silent = 0
        for d in ctx.bundle.deployments:
            if d.reachable:
                continue
            if d.status_code is None:
                silent += 1  # no answer at all; gather has opened a transient gap
                continue
            claim = by_url.get(d.url)
            refs = [claim.claim_id] if claim else []
            gone = d.status_code in self.gone
            findings.append(Discrepancy(
                finding_id=finding_id(ctx.report_id, self.rule_id, refs or [d.url]),
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                tier=self.tier if gone else self.soft_tier,
                severity=Severity.MEDIUM if gone else Severity.LOW,
                confidence=1.0,
                scoring=self.scoring,
                claim_refs=refs,
                evidence_refs=[f"deployments[{d.url}]"],
                params={"url": d.url, "status_code": d.status_code},
                explanation=(
                    f"The live URL claimed for "
                    f"{(claim.title if claim else None) or 'a project'} "
                    + ("is gone: " if gone else "did not serve a page: ")
                    + f"{d.url} returned HTTP {d.status_code}."
                ),
                innocent_explanation=None
                if gone
                else (
                    "Bot protection refuses automated requests that a browser would be "
                    "shown the site for, a login wall answers 401 or 403 to anyone "
                    "signed out, and a server error is often temporary. Opening the "
                    "link settles it, and the worksheet asks a reviewer to."
                ),
            ))

        if findings:
            yield from findings
            return
        if silent == len(ctx.bundle.deployments):
            raise Abstain(
                f"None of the {silent} claimed live URL(s) answered this machine — a "
                "timeout or a refused connection, which can be either side's network. "
                "Nothing is concluded; re-running may settle it."
            )

        linked = self._linked(ctx)
        if linked:
            raise Corroborated(
                "Live deployment tied to the repository by GitHub's own record — "
                + "; ".join(linked)
            )

    def _linked(self, ctx: Context) -> list[str]:
        """Claimed deployment URLs that a named repository declares as its homepage."""
        if ctx.bundle.github is None:
            return []
        claimed = {
            _site(a.url)
            for c in ctx.graph.claims
            for a in c.artefacts
            if a.type.value == "deployment"
        }
        return [
            f"{repo.name} declares {repo.homepage}"
            for repo in ctx.bundle.github.repos
            if repo.homepage and _site(repo.homepage) in claimed
        ]


def _site(url: str) -> str:
    """Host and path, without scheme, `www.` or a trailing slash.

    Compared as a whole rather than by host alone: two GitHub Pages projects for the
    same account share a host and differ only in the path, so matching on host would
    tie a deployment to the wrong repository.
    """
    stripped = url.split("://", 1)[-1].rstrip("/")
    return stripped.removeprefix("www.").lower()


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
        except Corroborated as confirmed:
            outcomes.append(
                RuleOutcome(
                    rule_id=rule.rule_id,
                    rule_version=rule.rule_version,
                    status=RuleStatus.CLEAN,
                    note=str(confirmed),
                )
            )
            continue
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
            # Isolation keeps the report rendering, and that is right — but it also
            # discards the traceback, so a rule broken by one malformed claim shows
            # up as a single line in a bucket nobody reads twice. The log is the only
            # place the stack survives.
            log.exception(
                "rule.error", rule_id=rule.rule_id, error=type(exc).__name__
            )
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
    log.info(
        "rules.evaluated",
        fired=sum(1 for o in outcomes if o.status is RuleStatus.FIRED),
        clean=sum(1 for o in outcomes if o.status is RuleStatus.CLEAN),
        abstained=sum(1 for o in outcomes if o.status is RuleStatus.ABSTAINED),
        errors=sum(1 for o in outcomes if o.status is RuleStatus.ERROR),
        findings=len(findings),
    )
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
    """Facts about each linked repository, each settled by the API.

    A fork is the one that matters most: presenting someone else's work as a project
    is a different claim from writing it, and GitHub records the distinction.

    A repository linked under ANOTHER owner is not a fork and not a contradiction —
    `apache/kafka` on a CV is a claim to have contributed, not to own. So the
    question for it is whether the account the CV names has commits there. Yes is
    corroboration. No is a question, never a contradiction: GitHub attributes a
    commit to an account only through an email address linked to it, and a team or
    organisation repository can carry work pushed by another member.
    """

    rule_id: str = "G4"
    rule_version: str = "2.0"
    tier: Tier = Tier.DECISIVE
    soft_tier: Tier = Tier.ATTENTION
    scoring: bool = True
    summary: str = "Linked repositories exist, are not forks, and belong to or carry the account"

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        gh = ctx.github()
        if not gh.repos:
            raise Abstain("No repositories named on the CV.")
        by_claim = ctx.named_repos()

        # Built as a list: `Corroborated` below is raised only when nothing fired, and
        # a generator that yields before raising loses everything it yielded.
        findings: list[Discrepancy] = []
        contributed: list[str] = []
        for repo in gh.repos:
            refs = [by_claim[repo.name]] if repo.name in by_claim else []
            common = {
                "rule_id": self.rule_id,
                "rule_version": self.rule_version,
                "confidence": 1.0,
                "scoring": self.scoring,
                "claim_refs": refs,
                "evidence_refs": [f"github.repos[{repo.name}]"],
            }
            # Under another owner: recorded as owner/name by the connector.
            elsewhere = "/" in repo.name
            if not repo.exists:
                where = (
                    f"github.com/{repo.name}" if elsewhere else f"github.com/{gh.handle}/{repo.name}"
                )
                findings.append(Discrepancy(
                    finding_id=finding_id(ctx.report_id, self.rule_id, [repo.name]),
                    tier=self.tier,
                    severity=Severity.HIGH,
                    params={"repo": repo.name},
                    explanation=(
                        f"The repository {repo.name!r} named on the CV does not exist at {where}."
                    ),
                    **common,
                ))
            elif repo.is_fork and not elsewhere:
                findings.append(Discrepancy(
                    finding_id=finding_id(ctx.report_id, self.rule_id, [repo.name, "fork"]),
                    tier=self.tier,
                    severity=Severity.HIGH,
                    params={"repo": repo.name, "is_fork": True},
                    explanation=(
                        f"{repo.name!r} is a fork of another repository, not original work."
                    ),
                    **common,
                ))
            elif elsewhere:
                if repo.commit_count is None:
                    continue  # the question could not be asked; nothing is concluded
                if repo.commit_count > 0:
                    count = (
                        f"{repo.commit_count}+" if repo.commit_count >= 100 else str(repo.commit_count)
                    )
                    contributed.append(f"{gh.handle!r} has {count} commit(s) in {repo.name}")
                    continue
                findings.append(Discrepancy(
                    finding_id=finding_id(ctx.report_id, self.rule_id, [repo.name, "commits"]),
                    tier=self.soft_tier,
                    severity=Severity.LOW,
                    params={"repo": repo.name, "account": gh.handle, "commits": 0},
                    explanation=(
                        f"{repo.name!r} is linked on the CV and belongs to another account. "
                        f"GitHub attributes no commits in it to {gh.handle!r}."
                    ),
                    innocent_explanation=(
                        "GitHub credits a commit to an account only through an email "
                        "address linked to that account, so commits made with a work or "
                        "university address are invisible here. A team or organisation "
                        "repository can also hold work another member pushed."
                    ),
                    **common,
                ))
            elif repo.owner_matches is False:
                findings.append(Discrepancy(
                    finding_id=finding_id(ctx.report_id, self.rule_id, [repo.name, "owner"]),
                    tier=self.tier,
                    severity=Severity.MEDIUM,
                    params={"repo": repo.name},
                    explanation=f"{repo.name!r} is not owned by {gh.handle!r}.",
                    **common,
                ))

        if findings:
            yield from findings
            return
        if contributed:
            raise Corroborated(
                "Contribution corroborated by GitHub's own attribution — "
                + "; ".join(contributed)
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
    """Is there anything in the repository that a person wrote?

    Deliberately not a size or commit-count threshold. Those encode an opinion about
    how big a project should be, which differs by institution, language and year, and
    a two-file Python program is a program. The trigger is ZERO authored files, which
    carries no opinion at all — which is what lets G7 be decisive.

    What changed in 2.0 is the definition of "authored", not the threshold. Asking
    only whether a filename sat outside eleven boilerplate names let two shapes
    through: a repository holding a README and a fifteen-thousand-line
    `package-lock.json`, and one holding a README and a committed minified bundle.
    Both are presented as projects and neither contains one.

    Not caught, and not claimed to be: an unmodified `create-next-app` scaffold.
    `app/page.js` is indistinguishable from source by its name, and separating
    generated source from written source needs the generator's template — data
    acquisition, not a filename rule.
    """

    rule_id: str = "G7"
    rule_version: str = "2.0"
    tier: Tier = Tier.DECISIVE
    scoring: bool = True
    summary: str = "Named repositories contain a file a person wrote"

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
                params={
                    "repo": repo.name,
                    "size_kb": repo.size_kb,
                    "authored_files": repo.authored_files,
                    "authored_bytes": repo.authored_bytes,
                },
                explanation=(
                    f"{repo.name!r} is presented as a project. Every file in it is a "
                    "README, a licence, a dependency lock file or generated output — "
                    "none was written by a person."
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


@register
@dataclass(frozen=True)
class G10ActivityDuringEmployment:
    """Public GitHub activity across a claimed employment window.

    CORROBORATION ONLY, and the asymmetry is the whole rule rather than a gap in it.
    The contributions calendar records PUBLIC activity; work code is normally private,
    on a company remote, behind a VPN, or in an enterprise instance the calendar never
    sees. A silent two-year window is what an ordinary salaried job looks like from
    outside, so firing on silence would flag most employed developers and would be
    the same mistake G5's first version made about projects.

    Activity that DOES span the window is real evidence, and this reports it.
    """

    rule_id: str = "G10"
    rule_version: str = "1.0"
    tier: Tier = Tier.ATTENTION
    scoring: bool = True
    summary: str = "Public activity across a claimed employment window"

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        gh = ctx.github()
        if not gh.contribution_windows:
            raise Abstain(
                "No contributions calendar was gathered. It needs an authenticated "
                "GraphQL request; set CVV_GITHUB_TOKEN."
            )
        roles = [c for c in ctx.claims(ClaimKind.EMPLOYMENT) if c.interval is not None]
        if not roles:
            raise Abstain("The CV dates no role to look for activity across.")

        covered_from = min(w.start for w in gh.contribution_windows)
        covered_to = max(w.end for w in gh.contribution_windows)

        confirmed: list[str] = []
        for claim in roles:
            assert claim.interval is not None
            lo = bounds(claim.interval.start)[0]
            hi = bounds(claim.interval.end or claim.interval.start)[1]
            if lo < covered_from or hi > covered_to:
                continue  # outside the calendar; no statement either way

            inside = [w for w in gh.contribution_windows if w.start <= hi and lo <= w.end]
            total = sum(w.commit_count for w in inside)
            active = sum(1 for w in inside if w.commit_count > 0)
            if total == 0:
                continue  # private work looks exactly like this; say nothing

            confirmed.append(
                f"{claim.title or 'the role'} at {claim.org or 'an unnamed employer'} "
                f"({lo:%b %Y} to {hi:%b %Y}): {total} public contributions across "
                f"{active} of {len(inside)} months"
            )

        if not confirmed:
            raise Abstain(
                "No claimed role falls inside the contributions calendar with public "
                "activity in it. That is the ordinary case — work code is normally "
                "private, and the calendar cannot see it — so nothing is concluded."
            )
        raise Corroborated(
            "Public GitHub activity spans a claimed role — " + "; ".join(confirmed)
        )
        yield  # pragma: no cover - unreachable; keeps the generator signature


@register
@dataclass(frozen=True)
class G11OrgMembership:
    """A claimed employer against the account's public GitHub organisations.

    Corroboration only, for a reason that is a fact about GitHub rather than a
    limitation here: organisation membership is PRIVATE BY DEFAULT. A member must go
    into the organisation's people page and switch their own membership to public,
    and most never do. Absence is therefore the normal state of a real employee, and
    a rule that fired on it would report a finding against nearly everyone who has
    ever held a job.

    Presence is different in kind. The organisation itself admitted the account, and
    nobody can add themselves — so a match is evidence from a party other than the
    candidate, which is the strongest thing this system ever gets.
    """

    rule_id: str = "G11"
    rule_version: str = "1.0"
    tier: Tier = Tier.ATTENTION
    scoring: bool = True
    summary: str = "Claimed employers against public GitHub organisation membership"

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        gh = ctx.github()
        employers = [c for c in ctx.claims(ClaimKind.EMPLOYMENT) if c.org]
        if not employers:
            raise Abstain("The CV names no employer to look for.")
        if not gh.org_memberships:
            raise Abstain(
                "The account lists no public organisation membership. GitHub hides "
                "membership by default and a member must opt in to being listed, so "
                "an empty list is the normal case and says nothing either way."
            )

        matched = [
            f"{claim.org!r} is corroborated by the GitHub organisation "
            f"{org!r}, which lists {gh.handle!r} publicly"
            for claim in employers
            for org in gh.org_memberships
            if _same_org(claim.org or "", org)
        ]
        if not matched:
            raise Abstain(
                "None of the claimed employers appears among this account's public "
                f"organisations ({', '.join(sorted(gh.org_memberships))}). Membership "
                "is private by default and an employer need not run a GitHub "
                "organisation at all, so this is not evidence against the claim."
            )
        raise Corroborated("Employer corroborated from outside the CV — " + "; ".join(matched))
        yield  # pragma: no cover - unreachable; keeps the generator signature


@register
@dataclass(frozen=True)
class G6StackVsRepository:
    """A project's claimed stack against the repository the CV itself links.

    Fires on ONE thing: the repository contains NOTHING the project says it is built
    with. Not "one technology is missing" — that version would be technically correct
    and unfair, because a CV names databases, protocols and services that no language
    census and no dependency manifest will ever show. MongoDB is not a language and
    is not an npm package.

    Comparing against languages ALONE would be worse still: a Next.js application
    reports as TypeScript, so every React project on every honest CV would contradict
    itself. Languages and dependency manifests are read together, and one match
    anywhere is enough to settle it.
    """

    rule_id: str = "G6"
    rule_version: str = "1.1"
    tier: Tier = Tier.DECISIVE
    scoring: bool = True
    summary: str = "A project's claimed stack against the repository it links"

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        gh = ctx.github()
        by_name = {r.name.lower(): r for r in gh.repos if r.exists}
        checked = False
        blind: list[str] = []

        for claim in ctx.claims(ClaimKind.PROJECT):
            if not claim.skill_refs:
                continue
            for artefact in claim.artefacts:
                if artefact.type is not ArtefactType.REPO:
                    continue
                repo = by_name.get(artefact.url.rstrip("/").split("/")[-1].lower())
                # Empty languages means the census was not gathered, not that the
                # repository is empty. Never conflate them.
                if repo is None or not repo.languages:
                    continue

                observed = [_norm(x) for x in (*repo.languages, *repo.frameworks)]
                if any(_matches(_norm(tech), observed) for tech in claim.skill_refs):
                    checked = True
                    continue
                # No dependency manifest was read, so the only observation is the
                # language census — and it cannot see a library, a database or a
                # service. An OpenCV project reports as C++. "Nothing matches" is
                # then a statement about what GitHub can show, not about the
                # repository, and a decisive finding cannot rest on it.
                if not repo.frameworks:
                    blind.append(repo.name)
                    continue
                checked = True

                yield Discrepancy(
                    finding_id=finding_id(ctx.report_id, self.rule_id, [claim.claim_id]),
                    rule_id=self.rule_id,
                    rule_version=self.rule_version,
                    tier=self.tier,
                    severity=Severity.HIGH,
                    confidence=0.8,
                    scoring=self.scoring,
                    claim_refs=[claim.claim_id],
                    evidence_refs=[f"github.repos.{repo.name}.languages"],
                    params={
                        "project": claim.title,
                        "repo": repo.name,
                        "claimed": claim.skill_refs,
                        "observed": sorted(repo.languages),
                    },
                    explanation=(
                        f"{claim.title!r} is described as {', '.join(claim.skill_refs)}, "
                        f"and the repository the CV links for it — {repo.name} — contains "
                        f"none of that. GitHub reports {', '.join(sorted(repo.languages))}, "
                        "and its dependency manifests name nothing from the claimed stack "
                        "either."
                    ),
                )

        if not checked:
            if blind:
                raise Abstain(
                    f"No dependency manifest could be read for {', '.join(sorted(set(blind)))}, "
                    "and a language census alone cannot see a library, a database or a "
                    "service — an OpenCV project reports as C++. Nothing is concluded."
                )
            raise Abstain(
                "No project both names a stack and links a repository whose language "
                "census was gathered."
            )


@register
@dataclass(frozen=True)
class G9LanguageTenure:
    """Claimed years with a language against the earliest public evidence of it.

    The fairness lives in the ABSTENTION, not in the finding. `first_commit_by_language`
    is a lower bound on evidence — the earliest repository using the language — and
    the account is usually younger than the claim it is being asked about. Someone
    claiming eight years of Python whose GitHub is three years old is not contradicted
    by that account; the account simply is not a witness, and a finding there would
    report when they joined GitHub while appearing to report when they learned Python.

    So it abstains unless the account PREDATES the claimed start. Only then does its
    silence carry information, and even then only as a question.
    """

    rule_id: str = "G9"
    rule_version: str = "1.0"
    tier: Tier = Tier.ATTENTION
    scoring: bool = True
    summary: str = "Claimed years with a language against the earliest public evidence"
    slack_years: int = 1

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        gh = ctx.github()
        stated = [c for c in ctx.claims(ClaimKind.SKILL) if c.stated_years]
        if not stated:
            raise Abstain("No skill on the CV states how many years it has been used.")
        if not gh.first_commit_by_language:
            raise Abstain(
                "No language could be dated from the account, so there is nothing to "
                "compare a claimed tenure against."
            )
        if gh.account_created is None:
            raise Abstain("The account's creation date was not gathered.")

        checked = False
        for claim in stated:
            assert claim.stated_years is not None
            claimed_start = ctx.today.replace(
                year=ctx.today.year - int(claim.stated_years)
            )
            if gh.account_created > claimed_start:
                continue  # younger than the claim; it cannot witness it either way

            for tech in claim.skill_refs:
                first = next(
                    (
                        date
                        for language, date in gh.first_commit_by_language.items()
                        if _matches(_norm(tech), [_norm(language)])
                    ),
                    None,
                )
                if first is None:
                    continue  # never observed at all — absence abstains, guardrail 4
                checked = True
                if first.year <= claimed_start.year + self.slack_years:
                    continue

                yield Discrepancy(
                    finding_id=finding_id(ctx.report_id, self.rule_id, [claim.claim_id]),
                    rule_id=self.rule_id,
                    rule_version=self.rule_version,
                    tier=self.tier,
                    severity=Severity.LOW,
                    confidence=0.4,
                    scoring=self.scoring,
                    claim_refs=[claim.claim_id],
                    evidence_refs=["github.first_commit_by_language"],
                    params={
                        "technology": tech,
                        "stated_years": claim.stated_years,
                        "claimed_since": claimed_start.year,
                        "first_evidence": first.year,
                    },
                    explanation=(
                        f"{claim.stated_years:g} years of {tech} implies use since about "
                        f"{claimed_start.year}. The earliest public repository of "
                        f"{gh.handle!r} using it was created in {first.year}, and the "
                        f"account itself dates from {gh.account_created.year}."
                    ),
                    innocent_explanation=(
                        "The earliest repository using a language is a lower bound on "
                        "EVIDENCE, never a start date. Work before this account, work "
                        "in a private or institutional repository, coursework, a job, "
                        "and a repository since deleted all leave nothing here."
                    ),
                )

        if not checked:
            raise Abstain(
                "No stated tenure could be compared: either the account is younger "
                "than the claim, or the language was never observed in it."
            )


# --------------------------------------------------------------------------- #
# D · document-intrinsic — no network, ever
# --------------------------------------------------------------------------- #


@register
@dataclass(frozen=True)
class D6DurationArithmetic:
    """A stated total of experience against the roles the CV actually dates.

    ATTENTION, and the catalogue's `decisive` is wrong here for a reason worth
    stating: a CV need not list every role. Early jobs, short contracts, freelance
    work and anything outside the story a candidate is telling get left off on
    purpose, and a one-page CV forces that. A stated total larger than the listed
    roles is therefore the ordinary shape of an edited CV, not a lie — the arithmetic
    is worth a reviewer's question and nothing more.

    Overlapping roles are merged before summing, so holding two jobs at once counts
    once. Max spans are used throughout, which is the reading most generous to the
    candidate.
    """

    rule_id: str = "D6"
    rule_version: str = "1.0"
    tier: Tier = Tier.ATTENTION
    scoring: bool = True
    summary: str = "A stated total of experience against the roles the CV dates"
    slack_years: float = 1.0

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        # A stated total is an EMPLOYMENT claim carrying years and no dates: it
        # asserts a duration of employment and nothing else. That keeps it inside the
        # contract's nine claim kinds — a tenth would break the round-trip with the
        # upstream schema — and it replaces reading the document with a regex for
        # `N years of experience`, which found that phrasing and no other.
        totals = [
            c
            for c in ctx.claims(ClaimKind.EMPLOYMENT)
            if c.stated_years and c.interval is None
        ]
        if not totals:
            raise Abstain("The CV states no total years of experience to check.")

        stated_claim = max(totals, key=lambda c: float(c.stated_years or 0))
        years = float(stated_claim.stated_years or 0)
        roles = [c for c in ctx.claims(ClaimKind.EMPLOYMENT) if c.interval is not None]
        if not roles:
            raise Abstain(
                f"The CV states {years:g} years of experience but dates no role, so "
                "there is nothing to sum against it."
            )

        spans = merge_non_overlapping(
            [c.interval for c in roles if c.interval is not None], today=ctx.today
        )
        listed = sum((hi - lo).days for lo, hi in spans) / 365.25
        if years <= listed + self.slack_years:
            return

        yield Discrepancy(
            finding_id=finding_id(
                ctx.report_id, self.rule_id, [stated_claim.claim_id, *(c.claim_id for c in roles)]
            ),
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            tier=self.tier,
            severity=Severity.LOW,
            confidence=0.5,
            scoring=self.scoring,
            claim_refs=[stated_claim.claim_id, *(c.claim_id for c in roles)],
            evidence_refs=[stated_claim.claim_id],
            params={
                "stated_years": years,
                "listed_years": round(listed, 1),
                "roles_dated": len(roles),
            },
            explanation=(
                f"The CV states {years:g} years of experience. The {len(roles)} role(s) "
                f"it dates cover {listed:.1f} years once overlaps are merged."
            ),
            innocent_explanation=(
                "A CV need not list every role, and a one-page CV forces the choice. "
                "Early jobs, short contracts, freelance work and anything off the "
                "story being told are routinely omitted, so a stated total larger "
                "than the dated roles is the ordinary shape of an edited CV."
            ),
        )


@register
@dataclass(frozen=True)
class D7TechnologyAnachronism:
    """A project built with something that did not exist yet.

    Decisive, and one of the few document-intrinsic checks that earns it: this is not
    a judgement about a career, it is a date against a date. React shipped in May
    2013, so a project dated 2011-2015 that claims React is either misdated or
    misdescribed, and either way the document does not hold together.

    Two layers of caution, because a false accusation here is expensive. Every date in
    the table is biased early, and the release must fall after the project's ENTIRE
    max span — so a project dated only "2016" never fires on a technology released
    during 2016, whatever month it was.
    """

    rule_id: str = "D7"
    rule_version: str = "1.0"
    tier: Tier = Tier.DECISIVE
    scoring: bool = True
    summary: str = "A project dated before the technology it names existed"

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        releases = tech_releases()
        if not releases:
            raise Abstain("No technology release table is installed.")

        dated = [
            c
            for c in ctx.claims(ClaimKind.PROJECT)
            if c.interval is not None and c.skill_refs
        ]
        if not dated:
            raise Abstain("No project both names a technology and carries a date.")

        for claim in dated:
            assert claim.interval is not None
            _, latest = max_span(claim.interval, today=ctx.today)
            for tech in claim.skill_refs:
                released = releases.get(_norm(tech))
                # Unlisted is UNKNOWN, not anachronistic. Most of what a CV names
                # will not be in the table, and that must stay silent.
                if released is None or released <= latest:
                    continue

                yield Discrepancy(
                    finding_id=finding_id(ctx.report_id, self.rule_id, [claim.claim_id]),
                    rule_id=self.rule_id,
                    rule_version=self.rule_version,
                    tier=self.tier,
                    severity=Severity.HIGH,
                    confidence=0.9,
                    scoring=self.scoring,
                    claim_refs=[claim.claim_id],
                    evidence_refs=["data/tech-releases.json"],
                    params={
                        "project": claim.title,
                        "technology": tech,
                        "released": str(released),
                        "project_ended_by": str(latest),
                    },
                    explanation=(
                        f"{claim.title!r} names {tech}, and under the latest reading of "
                        f"its dates the project ended by {latest}. {tech} was not "
                        f"publicly available until {released}."
                    ),
                )




@register
@dataclass(frozen=True)
class D9RollNumberStructure:
    """A roll number encodes an admission year and a department, both checkable
    against the CV using nothing but the document.

    This is the invariant working: a candidate with no account, no repositories and no
    contest history still gets a decisive check, because the evidence is the
    document's own internal consistency.

    Two INDEPENDENT sub-checks. The department needs the CV to name one; the timeline
    needs a programme with a known duration and a completion year. Either can run
    without the other, and the rule abstains only when neither can — an earlier
    version abstained as soon as the department was unavailable and silently gave up
    the timeline check that would have run fine.

    Scoped honestly. `23CS10004` is IIT Kharagpur's scheme; another institution
    encodes different things in a different shape. A scheme applies only when its
    pattern matches, an unlisted department code is unknown rather than wrong, and a
    CV that names no department is not claiming a different one.
    """

    rule_id: str = "D9"
    rule_version: str = "2.0"
    tier: Tier = Tier.DECISIVE
    scoring: bool = True
    summary: str = "Roll-number structure against the claimed programme and dates"

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        # Any decoded field will do. Version 1 required a department code, so a
        # scheme encoding only a year switched the whole rule off — and one encoding
        # only a department crashed it on the missing year.
        identifiers = [c for c in ctx.claims(ClaimKind.IDENTIFIER) if c.parsed]
        if not identifiers:
            raise Abstain(
                "No roll number was decoded. Most CVs carry none, and one is decoded "
                "only where the CV names an institution whose format is on record."
            )
        degrees = [c for c in ctx.claims(ClaimKind.EDUCATION) if c.degree]
        if not degrees:
            raise Abstain("No degree claimed to check the roll number against.")

        skipped: list[str] = []
        checked: list[str] = []
        # A generator that yields and then raises loses what it yielded: run_all sees
        # only the Abstain. So the final abstention is for a rule that found nothing.
        # Version 1 dropped a real department mismatch whenever the timeline half
        # then had to skip.
        fired = False
        # The document's own words, plus the institutions as extracted — a model may
        # write "IIT Kharagpur" for "Indian Institute of Technology Kharagpur", and the
        # scheme lists both.
        named_text = " ".join([ctx.graph.source.normalised_text, *(d.org or "" for d in degrees)])

        for ident in identifiers:
            parsed = ident.parsed or {}
            roll = ident.provenance.verbatim
            scheme = named_scheme(roll, named_text)
            if scheme is None:
                skipped.append(
                    f"{roll!r} has the shape of a format on record, but no institution "
                    "the CV names uses it, so nothing is read into it"
                )
                continue

            code = str(parsed["dept_code"]) if parsed.get("dept_code") else None
            admission = int(parsed["admission_year"]) if parsed.get("admission_year") else None

            # Departments the CV actually names, searched across each education
            # claim's degree, institution and its own span — the document's words.
            named: dict[str, Claim] = {
                dept: d
                for d in degrees
                for dept in scheme.get("departments", {})
                if department_matches(
                    scheme, dept, f"{d.degree or ''} {d.org or ''} {d.provenance.verbatim}"
                )
            }

            if code is None:
                skipped.append(f"{scheme.get('label', 'this')} roll numbers encode no department")
            elif named and code not in named:
                subject = next(iter(named.values()))
                fired = True
                yield Discrepancy(
                    finding_id=finding_id(ctx.report_id, self.rule_id, [ident.claim_id]),
                    rule_id=self.rule_id,
                    rule_version=self.rule_version,
                    tier=self.tier,
                    severity=Severity.HIGH,
                    confidence=1.0,
                    scoring=self.scoring,
                    claim_refs=[ident.claim_id, subject.claim_id],
                    evidence_refs=["data/roll-schemes.json"],
                    params={
                        "roll": roll,
                        "dept_code": code,
                        "encodes": scheme["departments"].get(code, []),
                        "cv_names": sorted(named),
                    },
                    explanation=(
                        f"The roll number {roll} encodes department {code!r} "
                        f"({', '.join(scheme['departments'].get(code, []))}), but the CV "
                        f"names {', '.join(sorted(named))} instead."
                    ),
                )
            elif not named:
                # ABSENCE ABSTAINS. Fired here once, on an honest CV: the extracted
                # degree was "B.TECH" and "COMPUTER SCIENCE AND ENGINEERING" sat in
                # the header line. Not naming a department is not claiming a
                # different one.
                skipped.append(
                    f"the CV states no department to compare {roll} against"
                )

            # The timeline sub-check, independent of the above. Prefer the degree
            # whose department matches, else one at the scheme's own institution,
            # else the longest programme claimed.
            if admission is None:
                skipped.append(f"{roll} encodes no admission year")
                continue
            subject = (named.get(code) if code else None) or _degree_at(scheme, degrees) or degrees[0]
            years = programme_years(scheme, subject.degree or "")
            if years is None:
                skipped.append(f"{subject.degree!r} has no standard duration on record")
                continue
            if subject.interval is None:
                skipped.append(f"{subject.degree!r} carries no year to check against")
                continue
            if subject.interval.ongoing:
                # "2023 - Present" states no completion year. Version 1 read the START
                # as the end and told a second-year student their four-year degree
                # "completes in 2023", decisively — on the most common way a current
                # student dates one. The start is still worth saying when it agrees.
                skipped.append(
                    f"{subject.degree!r} is dated as ongoing, so the CV states no "
                    f"completion year to check {roll} against"
                )
                if subject.interval.start.year == admission:
                    checked.append(
                        f"{roll} encodes admission in {admission}, which is when the CV "
                        f"says the {subject.degree} began"
                    )
                continue

            # A single year with no range is the completion year, not an open range.
            end = subject.interval.end or subject.interval.start
            expected = admission + years
            if end.year == expected:
                # The timeline agrees. Recorded even though it produces no finding:
                # if the department could not be compared, the rule abstains, and the
                # reader must be told which half DID run. "Could not check the roll
                # number" and "checked the years, they line up, could not check the
                # department" are different statements.
                checked.append(
                    f"{roll} encodes admission in {admission} and a {years}-year "
                    f"{subject.degree} completes in {expected}, which the CV agrees with"
                )
                continue

            yield Discrepancy(
                finding_id=finding_id(ctx.report_id, self.rule_id, [ident.claim_id, "years"]),
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                tier=self.tier,
                severity=Severity.MEDIUM,
                confidence=1.0,
                scoring=self.scoring,
                claim_refs=[ident.claim_id, subject.claim_id],
                evidence_refs=["data/roll-schemes.json"],
                params={
                    "roll": roll,
                    "admission_year": admission,
                    "programme": subject.degree,
                    "programme_years": years,
                    "expected_completion": expected,
                    "claimed_completion": end.year,
                },
                explanation=(
                    f"The roll number {roll} encodes admission in {admission}. A "
                    f"{years}-year {subject.degree} started then completes in "
                    f"{expected}, but the CV gives {end.year}."
                ),
            )
            return

        if skipped and not fired:
            reason = "; ".join(dict.fromkeys(skipped)) + "."
            if checked:
                reason += " Checked: " + "; ".join(dict.fromkeys(checked)) + "."
            raise Abstain(reason)


def _degree_at(scheme: dict[str, object], degrees: list[Claim]) -> Claim | None:
    """The degree awarded by the scheme's own institution, if the CV names it."""
    institutions = scheme.get("institutions", [])
    assert isinstance(institutions, list)
    for d in degrees:
        # Whole words, for the reason named_scheme gives: "vit" is inside "activities".
        if any(re.search(rf"\b{re.escape(n)}\b", d.org or "", re.I) for n in institutions):
            return d
    return None


@register
@dataclass(frozen=True)
class G3OwnershipProof:
    """Reports whether the GitHub account was ever proven to be the candidate's.

    It verifies nothing, and cannot. Public GitHub data says an account exists and
    what it did; nothing in it links an account to a specific human, and no number of
    additional calls would change that. Anyone can print any handle on a CV.

    So this is a caveat rendered as a finding, so that a reviewer reading five green
    GitHub rows understands what they rest on. `scoring=false`: it is context for
    reading the other findings, not a finding about the candidate.

    The asymmetry it exists to explain: a self-claimed account that CONTRADICTS the CV
    is strong evidence, because nobody lists a handle that undermines them. One that
    CORROBORATES is weak, because it could be anyone's. So `claimed_unverified` caps
    evidence in one direction only.

    Moving off `claimed_unverified` needs the candidate to act — an OAuth grant, or a
    gist containing a nonce we issued. Neither can be a prerequisite: the invariant is
    that a candidate who never cooperates still gets a complete, honest report.
    """

    rule_id: str = "G3"
    rule_version: str = "1.0"
    tier: Tier = Tier.ATTENTION
    # The first non-scoring rule in the system. It describes how to READ the other
    # GitHub findings; letting it move a number would double-count them.
    scoring: bool = False
    summary: str = "Whether control of the GitHub account was proven"

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        gh = ctx.github()
        if gh.ownership in (Ownership.VERIFIED_OAUTH, Ownership.VERIFIED_CHALLENGE):
            return  # proven; nothing to caveat

        # Only the account that was checked. A CV linking someone else's repository
        # carries a profile claim for that owner too, and this caveat is not about
        # them.
        profiles = [
            c.claim_id
            for c in ctx.claims(ClaimKind.PROFILE)
            if (c.platform or "").lower() == "github"
            and (c.handle or "").lower() == gh.handle.lower()
        ]
        yield Discrepancy(
            finding_id=finding_id(ctx.report_id, self.rule_id, profiles),
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            tier=self.tier,
            severity=Severity.LOW,
            confidence=0.55,
            scoring=self.scoring,
            claim_refs=profiles,
            evidence_refs=["github.ownership"],
            params={"ownership": gh.ownership.value, "handle": gh.handle},
            explanation=(
                f"The GitHub account {gh.handle!r} was inferred from repository URLs "
                "printed on the CV; control of it has not been proven."
            ),
            innocent_explanation=(
                "Most candidates never complete an ownership challenge, and nothing "
                "about this is a mark against them. Its effect is one-directional: "
                "evidence from this account that CORROBORATES the CV is weighted down, "
                "while evidence that CONTRADICTS it is not — nobody prints a handle "
                "that undermines them. Proving control raises the weight of the "
                "supporting findings; it never creates new ones."
            ),
        )


@register
@dataclass(frozen=True)
class D5IntervalOverlap:
    """Two roles held at the same time, under every reading of the dates.

    Document-intrinsic: no network, no account, no cooperation. This and D9 are what
    the invariant rests on.

    **Only DEFINITE overlap.** Most Indian CVs give year precision only, and a
    single-point interval has an empty core, so "2023" against "2023" resolves as
    POSSIBLE and is never scored. Scoring POSSIBLE turns every clean CV into six
    contradictions.

    **Employment type decides the tier, and sometimes decides nothing fires at all.**
    Two full-time roles at once is a contradiction. An internship, a part-time job or
    freelance work concurrent with anything is ordinary life — students work while
    studying, and a rule that flags that penalises the people most likely to have to.
    Where the CV does not state a type, the overlap is real but its significance is
    not, so it is posed as a question rather than asserted as a fact.

    **And a SHORT overlap is a handover, not a second job.** Version 1 had exact
    dates for the first time on a third CV and called a twelve-day overlap between
    one role ending and the next beginning a decisive contradiction between two
    full-time jobs. That is how changing jobs works: you start the new one while
    notice at the old one is still running, or your last day is on the books after
    you have already begun. Below `handover_days` the overlap is posed as a question
    with that reading attached; above it, two months of dual full-time employment is
    not a notice period.

    Absolute days, not the fraction — a two-week handover between two one-month
    contracts is 50% of the shorter role and still a handover.
    """

    rule_id: str = "D5"
    rule_version: str = "2.1"
    tier: Tier = Tier.DECISIVE
    soft_tier: Tier = Tier.ATTENTION
    # Long enough to cover a notice period and a late final payroll date, short
    # enough that two months of concurrent full-time work is not called one. A
    # documented prior, swept in the evaluation rather than fitted.
    handover_days: int = 45
    scoring: bool = True
    summary: str = "Two roles held at the same time under every reading of the dates"

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        roles = [
            (c, c.interval)
            for c in ctx.claims(ClaimKind.EMPLOYMENT)
            if c.interval is not None
        ]
        if len(roles) < 2:
            raise Abstain(
                "Fewer than two dated roles are claimed; there is nothing to overlap."
            )

        for (a, a_interval), (b, b_interval) in itertools.combinations(roles, 2):
            # One role written twice is not two jobs at once. Whether its two
            # accounts agree is D10's question, and answering it here as well would
            # describe one fact twice.
            if _same_role(a, b):
                continue
            # Concurrency is normal for anything but two full-time roles. Not a
            # tolerance — a genuine statement that these combinations are not
            # contradictions.
            concurrent_is_normal = {
                EmploymentType.INTERNSHIP,
                EmploymentType.PART_TIME,
                EmploymentType.FREELANCE,
            }
            if {a.employment_type, b.employment_type} & concurrent_is_normal:
                continue

            relation, fraction = overlap(a_interval, b_interval, today=ctx.today)
            if relation is not Rel.DEFINITE:
                continue

            # The overlap the CORE spans share — what is true under every reading.
            a_core = core_span(a_interval, today=ctx.today)
            b_core = core_span(b_interval, today=ctx.today)
            days = (
                min(a_core[1], b_core[1]) - max(a_core[0], b_core[0])
            ).days + 1

            handover = days <= self.handover_days
            both_full_time = (
                a.employment_type is EmploymentType.FULL_TIME
                and b.employment_type is EmploymentType.FULL_TIME
            )
            decisive = both_full_time and not handover
            yield Discrepancy(
                finding_id=finding_id(ctx.report_id, self.rule_id, [a.claim_id, b.claim_id]),
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                tier=self.tier if decisive else self.soft_tier,
                severity=Severity.HIGH if decisive else Severity.LOW,
                confidence=1.0,
                scoring=self.scoring,
                claim_refs=[a.claim_id, b.claim_id],
                evidence_refs=[],
                params={
                    "a": a.org,
                    "b": b.org,
                    "overlap_days": days,
                    "overlap_fraction": round(fraction, 2),
                    "a_type": a.employment_type.value,
                    "b_type": b.employment_type.value,
                },
                explanation=(
                    f"{a.org!r} and {b.org!r} overlap by {days} day(s), {fraction:.0%} "
                    "of the shorter role, under every consistent reading of the dates."
                ),
                innocent_explanation=(
                    None
                    if decisive
                    else "A short overlap is how changing jobs works: the new role "
                    "starts while notice at the old one is still running, or the last "
                    "day is on the books after the next has begun."
                    if handover
                    else "Neither role states whether it was full-time. Concurrent "
                    "part-time, contract, notice-period or advisory work is ordinary, "
                    "and the dates alone cannot distinguish it from a contradiction."
                ),
            )


@register
@dataclass(frozen=True)
class D2SpanGrounding:
    """Claims the extractor produced and this system refused to keep.

    Not a finding about the candidate — a finding about the extraction. The honest
    consequence is lower coverage, stated openly, rather than a report that looks
    complete while missing things.

    TWO CAUSES, reported apart, because they mean opposite things about the model.
    *Ungroundable* means the quoted text is not in the document: the model invented or
    garbled it. *Filtered* means the text was real and the claim was not usable — a
    field the span did not support, an excluded exam, a duplicate.

    Version 1 added them together and called the total "text that could not be found".
    On a professional CV whose ACHIEVEMENTS section holds patents, GitHub stars and
    published books rather than contest ratings, the achievements pass returned six
    perfectly real sentences forced into a competitive-programming shape, the filters
    refused all six — correctly — and the report told a reader their text was not in
    their own CV.
    """

    rule_id: str = "D2"
    rule_version: str = "2.0"
    tier: Tier = Tier.ATTENTION
    scoring: bool = False  # about the extraction, not the person
    summary: str = "Claims dropped because their text was not in the document"

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        meta = ctx.graph.extraction_meta
        kept = len(ctx.graph.claims)
        filtered = sum(meta.filtered.values())
        dropped = meta.span_failures + filtered
        if dropped == 0:
            return
        total = kept + dropped

        causes = []
        if meta.span_failures:
            causes.append(
                f"{meta.span_failures} because the quoted text is not in the document"
            )
        if filtered:
            named = ", ".join(f"{k.replace('_', ' ')} ({v})" for k, v in sorted(meta.filtered.items()))
            causes.append(f"{filtered} refused by the extraction filters — {named}")
        yield Discrepancy(
            finding_id=finding_id(ctx.report_id, self.rule_id, []),
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            tier=self.tier,
            severity=Severity.HIGH if dropped > kept else Severity.LOW,
            confidence=1.0,
            scoring=self.scoring,
            claim_refs=[],
            evidence_refs=["claim_graph.extraction_meta"],
            params={
                "dropped": dropped,
                "ungroundable": meta.span_failures,
                "filtered": filtered,
                "filters": dict(meta.filtered),
                "kept": kept,
                "proposed": total,
            },
            explanation=(
                f"{dropped} of {total} proposed claims were dropped: " + "; ".join(causes) + "."
            ),
            innocent_explanation=(
                "This describes the extractor, not the candidate. Text that is not in "
                "the document was invented or garbled by the model; a filtered claim "
                "had real text this system could not use — a field its own sentence "
                "did not support, or a category the design excludes. Both are the "
                "guardrails working. The cost is coverage: something the CV says may "
                "have gone unchecked."
            ),
        )


@register
@dataclass(frozen=True)
class D3SelfDeclarationMarkers:
    """The document disclaiming itself.

    An institutional CV that says "CDC could not verify the relevant documents" has
    already told you the trust boundary. Inheriting it is more honest than re-deriving
    it, and far more honest than ignoring it — a reader who does not see the
    disclaimer may take the whole document as institutionally attested.

    Never a mark against the candidate: the institution wrote it, not them.
    """

    rule_id: str = "D3"
    rule_version: str = "1.0"
    tier: Tier = Tier.ATTENTION
    scoring: bool = False
    summary: str = "The document's own disclaimer about what it could not verify"

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        markers = ctx.claims(ClaimKind.DECLARATION_MARKER)
        if not markers:
            raise Abstain("The document carries no self-declaration marker.")

        for marker in markers:
            yield Discrepancy(
                finding_id=finding_id(ctx.report_id, self.rule_id, [marker.claim_id]),
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                tier=self.tier,
                severity=Severity.INFO,
                confidence=1.0,
                scoring=self.scoring,
                claim_refs=[marker.claim_id],
                evidence_refs=[],
                params={"marker": marker.provenance.verbatim},
                explanation=(
                    "The document disclaims part of its own content: "
                    f"{marker.provenance.verbatim!r}"
                ),
                innocent_explanation=(
                    "The institution wrote this, not the candidate, and it is a mark "
                    "against neither. It says which parts of the document the issuer "
                    "itself did not check, and those inherit that status here rather "
                    "than being presented as attested."
                ),
            )


@register
@dataclass(frozen=True)
class D4DocumentProvenance:
    """How the file itself was produced.

    Fires on ONE thing: a modification long after creation. An institutional producer
    is the opposite of a finding — a CV generated by a placement cell's template went
    through that cell — so it is reported as context inside the explanation, never as
    a signal against the candidate.
    """

    rule_id: str = "D4"
    rule_version: str = "1.0"
    tier: Tier = Tier.ATTENTION
    scoring: bool = False
    summary: str = "Document provenance — producer, and edits after generation"
    gap_days: int = 1
    # Beyond this the CREATED timestamp is not credible as this document's creation.
    # python-docx leaves its template's 2013 date in place unless the caller sets one,
    # and Word templates do the same — so the first DOCX read here reported a
    # four-thousand-day "edit gap" that was an artefact of the template, not an edit.
    implausible_days: int = 1826  # five years

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        if ctx.document is None:
            raise Abstain("No document metadata was supplied.")
        created = _doc_date(ctx.document.created_at)
        modified = _doc_date(ctx.document.modified_at)
        if created is None or modified is None:
            raise Abstain(
                "The file records no creation or modification time, which is normal "
                "for many exporters and says nothing either way."
            )
        gap = (modified - created).days
        if gap < self.gap_days:
            return
        if gap > self.implausible_days:
            raise Abstain(
                f"The file records a {gap}-day span between creation and last "
                "modification, which is not credible as an edit history. Document "
                "templates carry their own creation date, so this says nothing "
                "about when the CV was written."
            )

        producer = ctx.document.producer
        yield Discrepancy(
            finding_id=finding_id(ctx.report_id, self.rule_id, []),
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            tier=self.tier,
            severity=Severity.LOW,
            confidence=0.4,
            scoring=self.scoring,
            claim_refs=[],
            evidence_refs=["document.modified_at"],
            params={"created": str(created), "modified": str(modified), "gap_days": gap},
            explanation=(
                f"The file was created on {created} and last modified {gap} days later"
                + (f", by {producer!r}" if producer else "")
                + "."
            ),
            innocent_explanation=(
                "Editing a CV after generating it is the normal way a CV is written. "
                "This is recorded so a reviewer knows the file is not byte-identical "
                "to what its producer emitted, and for no stronger purpose."
            ),
        )


@register
@dataclass(frozen=True)
class D8DegreeDuration:
    """A programme's claimed span against its standard length.

    Attention, never decisive. Real degrees run long and short for reasons a CV has no
    obligation to explain — a year abroad, a medical leave, a backlog, an accelerated
    track, a transfer. The check surfaces the arithmetic; it does not interpret it.
    """

    rule_id: str = "D8"
    rule_version: str = "1.0"
    tier: Tier = Tier.ATTENTION
    scoring: bool = True
    summary: str = "Claimed degree span against the programme's standard length"

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        degrees = [
            c
            for c in ctx.claims(ClaimKind.EDUCATION)
            if c.degree and c.interval and c.interval.end
        ]
        if not degrees:
            raise Abstain(
                "No degree carries both a start and an end year, so no span can be "
                "compared."
            )

        checked = False
        for d in degrees:
            assert d.interval is not None and d.interval.end is not None
            scheme = next(
                (s for s in roll_schemes().values() if programme_years(s, d.degree or "")),
                None,
            )
            if scheme is None:
                continue
            standard = programme_years(scheme, d.degree or "")
            if standard is None:
                continue
            checked = True
            claimed = d.interval.end.year - d.interval.start.year
            if claimed == standard:
                continue

            yield Discrepancy(
                finding_id=finding_id(ctx.report_id, self.rule_id, [d.claim_id]),
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                tier=self.tier,
                severity=Severity.LOW,
                confidence=0.6,
                scoring=self.scoring,
                claim_refs=[d.claim_id],
                evidence_refs=["data/roll-schemes.json"],
                params={
                    "degree": d.degree,
                    "claimed_years": claimed,
                    "standard_years": standard,
                },
                explanation=(
                    f"{d.degree!r} is claimed over {claimed} years; the standard "
                    f"programme runs {standard}."
                ),
                innocent_explanation=(
                    "Degrees run long and short for reasons a CV has no obligation to "
                    "explain — a year abroad, medical leave, a backlog, an accelerated "
                    "track, a transfer between institutions. The arithmetic is shown; "
                    "what it means is not inferred."
                ),
            )

        if not checked:
            raise Abstain("No claimed degree has a standard duration on record.")


@register
@dataclass(frozen=True)
class D10InternalContradiction:
    """One stint of one role, given two accounts that cannot both be true.

    Version 1 fired when two mentions of a role did NOT overlap — and that is the
    shape of an honest career. "SDE Intern, Google" in the summer of 2023 and again
    in 2024 is a return offer; a rehire looks the same. It was reported decisively as
    "dates that cannot both be true" when both were true. The mutation harness could
    not see it, because its D10 mutation WAS a return internship: the false positive
    had been written down as the fabrication.

    Disjoint mentions are two stints, and say nothing. What a document cannot do is
    give ONE stint two irreconcilable accounts: mentions that overlap, so they cover
    the same period of the same role, and still disagree about when it began or
    ended — "2021 to 2023" in one place and "2022 to 2024" in another. Precision is
    not disagreement: "2022" and "Jan 2022 to Dec 2022" are one stint written twice,
    and a bare year is a single mention compatible with any range it falls inside.

    Employment type decides the tier, as it does in D5. Two full-time accounts of one
    job contradict each other. Anything else is posed as a question, because one
    title can honestly cover two concurrent engagements — a teaching assistant for
    two courses in one term — and the dates alone cannot tell those apart.
    """

    rule_id: str = "D10"
    rule_version: str = "2.0"
    tier: Tier = Tier.DECISIVE
    soft_tier: Tier = Tier.ATTENTION
    scoring: bool = True
    summary: str = "One stint of a role dated two irreconcilable ways"

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        dated = [
            (c, c.interval)
            for c in ctx.claims(ClaimKind.EMPLOYMENT)
            if c.interval is not None and c.org
        ]
        if len(dated) < 2:
            raise Abstain("Fewer than two dated roles are claimed.")

        for (a, ia), (b, ib) in itertools.combinations(dated, 2):
            if not _same_role(a, b):
                continue
            relation, _ = overlap(ia, ib, today=ctx.today)
            if relation is Rel.NONE:
                continue  # two stints of one role: a return offer, a rehire
            if _one_stint(ia, ib, today=ctx.today):
                continue  # the same stint, written twice at different precisions

            decisive = (
                a.employment_type is EmploymentType.FULL_TIME
                and b.employment_type is EmploymentType.FULL_TIME
            )
            yield Discrepancy(
                finding_id=finding_id(ctx.report_id, self.rule_id, [a.claim_id, b.claim_id]),
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                tier=self.tier if decisive else self.soft_tier,
                severity=Severity.HIGH if decisive else Severity.LOW,
                confidence=1.0,
                scoring=self.scoring,
                claim_refs=[a.claim_id, b.claim_id],
                evidence_refs=[],
                params={
                    "org": a.org,
                    "title": a.title,
                    "dated_a": _written(ia),
                    "dated_b": _written(ib),
                },
                explanation=(
                    f"{a.title!r} at {a.org!r} is dated {_written(ia)} in one place and "
                    f"{_written(ib)} in another. The two overlap, so they describe the "
                    "same period of the same role, and they disagree about when it "
                    "began or ended."
                ),
                innocent_explanation=(
                    None
                    if decisive
                    else "One title can cover two concurrent engagements — a teaching "
                    "assistant for two courses in one term, an internship extended past "
                    "its original dates. Neither mention says the role was full-time, "
                    "so the dates alone cannot tell that apart from a contradiction."
                ),
            )


def _same_role(a: Claim, b: Claim) -> bool:
    """The same employer and the same title, as written. D5 and D10 share it.

    Requires an employer: two mentions with no org are not known to be one role, and
    treating them as one would let D5 skip a real overlap.
    """
    return bool(a.org) and (a.org or "").strip().lower() == (b.org or "").strip().lower() and (
        (a.title or "").strip().lower() == (b.title or "").strip().lower()
    )


def _one_stint(a: Interval, b: Interval, *, today: datetime.date) -> bool:
    """Could two date ranges be one stint written twice?

    Yes when every bound admits a common reading: the starts could be the same day,
    and so could the ends. A single date with no range is one mention of a year or a
    month, not a range of its own, so it agrees with any range it falls inside — the
    overlap test before this has already established that it does.
    """
    if (a.end is None and not a.ongoing) or (b.end is None and not b.ongoing):
        return True

    def meets(x: tuple[datetime.date, datetime.date], y: tuple[datetime.date, datetime.date]) -> bool:
        return x[0] <= y[1] and y[0] <= x[1]

    def end(iv: Interval) -> tuple[datetime.date, datetime.date]:
        return (today, today) if iv.ongoing else bounds(iv.end or iv.start)

    return meets(bounds(a.start), bounds(b.start)) and meets(end(a), end(b))


def _written(iv: Interval) -> str:
    """An interval as a reader would write it back — "2021 to 2023", "Jan 2022 to
    present" — so a finding states both accounts rather than only that they differ."""

    def one(d: FuzzyDate) -> str:
        if d.precision is Precision.YEAR or d.month is None:
            return str(d.year)
        month = calendar.month_abbr[d.month]
        return f"{month} {d.year}" if d.precision is Precision.MONTH else f"{d.day} {month} {d.year}"

    if iv.ongoing:
        return f"{one(iv.start)} to present"
    return one(iv.start) if iv.end is None else f"{one(iv.start)} to {one(iv.end)}"


@register
@dataclass(frozen=True)
class D11TimelineGap:
    """An unexplained gap between roles.

    NON-SCORING, enforced here and structurally in the aggregator. A gap can be
    illness, caregiving, a visa, a failed startup, a sabbatical, or a job market. It
    measures career shape, which is not evidence of anything, and treating it as a
    signal penalises exactly the people whose lives did not run in a straight line.

    It is displayed so a reviewer can ask. It never moves a number.
    """

    rule_id: str = "D11"
    rule_version: str = "1.1"
    tier: Tier = Tier.ATTENTION
    scoring: bool = False
    summary: str = "Gap between claimed roles (displayed, never scored)"
    threshold_days: int = 365

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        dated = [
            (c, c.interval)
            for c in ctx.claims(ClaimKind.EMPLOYMENT)
            if c.interval is not None
        ]
        if len(dated) < 2:
            raise Abstain("Fewer than two dated roles are claimed.")

        ordered = sorted(dated, key=lambda pair: bounds(pair[1].start)[0])
        for (a, ia), (b, ib) in itertools.pairwise(ordered):
            # Two stints of one role are two stints, and the time between them is a
            # gap like any other. Version 1.0 skipped the pair because D10 reported
            # it as a contradiction; D10 no longer does, and a gap D10 is silent about
            # must not vanish. An irreconcilable account of ONE stint overlaps itself,
            # so it has no gap to report.
            days = gap_between(ia, ib, today=ctx.today)
            if days is None or days < self.threshold_days:
                continue
            yield Discrepancy(
                finding_id=finding_id(ctx.report_id, self.rule_id, [a.claim_id, b.claim_id]),
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                tier=self.tier,
                severity=Severity.INFO,
                confidence=0.9,
                scoring=self.scoring,
                claim_refs=[a.claim_id, b.claim_id],
                evidence_refs=[],
                params={"gap_days": days, "after": a.org, "before": b.org},
                explanation=(
                    f"{days} days separate {a.org!r} from {b.org!r} under every reading "
                    "of the dates."
                ),
                innocent_explanation=(
                    "A gap is not evidence of anything. Illness, caregiving, a visa, a "
                    "sabbatical, study, a failed venture and a bad job market all look "
                    "identical here, and a CV is under no obligation to account for its "
                    "own shape. This is shown so a reviewer may ask, and it is barred "
                    "from contributing to any total."
                ),
            )


@register
@dataclass(frozen=True)
class D12TitleProgression:
    """Seniority moving faster than tenure.

    NON-SCORING, for the same reason as D11 and more so. Titles are not comparable
    across companies: a "Senior Engineer" at a four-person startup and at a bank are
    different jobs with the same words. Promotion speed also tracks company size,
    sector and luck far more than it tracks ability.
    """

    rule_id: str = "D12"
    rule_version: str = "1.0"
    tier: Tier = Tier.ATTENTION
    scoring: bool = False
    summary: str = "Seniority against tenure (displayed, never scored)"
    fast_months: int = 18

    _LADDER: tuple[tuple[str, ...], ...] = (
        ("intern", "trainee"),
        ("junior", "associate", "graduate"),
        ("engineer", "developer", "analyst"),
        ("senior",),
        ("lead", "principal", "staff", "manager"),
        ("head", "director", "vp", "vice president", "chief"),
    )

    def _rank(self, title: str) -> int | None:
        lowered = title.lower()
        for level in range(len(self._LADDER) - 1, -1, -1):
            if any(word in lowered for word in self._LADDER[level]):
                return level
        return None

    def evaluate(self, ctx: Context) -> Iterator[Discrepancy]:
        dated = [
            (c, c.interval)
            for c in ctx.claims(ClaimKind.EMPLOYMENT)
            if c.interval is not None and c.title
        ]
        if len(dated) < 2:
            raise Abstain("Fewer than two dated, titled roles are claimed.")

        ordered = sorted(dated, key=lambda pair: bounds(pair[1].start)[0])
        for (a, ia), (b, ib) in itertools.pairwise(ordered):
            ra, rb = self._rank(a.title or ""), self._rank(b.title or "")
            if ra is None or rb is None or rb - ra < 2:
                continue
            months = (bounds(ib.start)[0] - bounds(ia.start)[0]).days // 30
            if months >= self.fast_months:
                continue

            yield Discrepancy(
                finding_id=finding_id(ctx.report_id, self.rule_id, [a.claim_id, b.claim_id]),
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                tier=self.tier,
                severity=Severity.INFO,
                confidence=0.5,
                scoring=self.scoring,
                claim_refs=[a.claim_id, b.claim_id],
                evidence_refs=[],
                params={"from": a.title, "to": b.title, "months": months},
                explanation=(
                    f"{a.title!r} to {b.title!r} in about {months} months."
                ),
                innocent_explanation=(
                    "Titles are not comparable across companies — a Senior Engineer at "
                    "a four-person startup and at a bank are different jobs sharing a "
                    "word. Promotion speed tracks company size, sector and timing far "
                    "more than ability. Shown so a reviewer may ask; barred from any "
                    "total."
                ),
            )


def _matches(tech: str, observed: list[str]) -> bool:
    """Containment either way, so "next.js" meets the npm package `next`.

    Two characters minimum, or "go" matches "django" and "c" matches everything.
    Substrings are checked at a word boundary of the normalised form instead: the
    shorter string must be a prefix or the whole of the longer one.
    """
    if len(tech) < 2:
        return tech in observed
    return any(o == tech or o.startswith(tech) or tech.startswith(o) for o in observed if o)


def _same_org(claimed: str, org_login: str) -> bool:
    """Does a GitHub organisation login name the employer the CV claims?

    Containment either way on alphanumerics: "Vercel" matches `vercel`, and "IIT
    Kharagpur, Dept. of CSE" matches `iitkgp` in neither direction — which is correct.
    An abbreviation the system cannot derive is a miss, and a miss abstains rather
    than contradicting, so the cost of being strict here is nothing.
    """
    a = re.sub(r"[^a-z0-9]", "", claimed.lower())
    b = re.sub(r"[^a-z0-9]", "", org_login.lower())
    if len(a) < 3 or len(b) < 3:
        return False
    return a in b or b in a


def _doc_date(value: str | None) -> datetime.date | None:
    """Two formats, because two ingest paths write them.

        PDF     D:20250704194743+05'30'
        DOCX    2013-12-23T23:15:00+00:00

    Handling only the first meant D4 silently abstained on every DOCX — not a wrong
    answer, but a check quietly not running, which is the failure this system exists
    to avoid.
    """
    if not value:
        return None
    text = value.removeprefix("D:")
    for fmt, cut in (("%Y%m%d", 8), ("%Y-%m-%d", 10)):
        try:
            return (
                datetime.datetime.strptime(text[:cut], fmt)
                .replace(tzinfo=datetime.UTC)
                .date()
            )
        except ValueError:
            continue
    return None
