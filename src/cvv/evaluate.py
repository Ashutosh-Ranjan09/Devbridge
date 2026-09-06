"""Does the system catch what it claims to catch, and only that?

294 unit tests prove each rule does what its author intended. They cannot prove the
SYSTEM detects a falsified CV, because every one of them hands the rule a fixture
built to exercise it. This measures something different: take a real document that
ran end to end, corrupt exactly one fact in it, and ask whether the check responsible
notices — and whether anything else fires that should not have.

Two numbers come out, and the second matters more.

**Detection** is how many mutations the responsible rule caught. It is the number a
thesis quotes and it is the easy one to make look good.

**Collateral** is how many OTHER rules fired under a mutation they had no business
noticing. A system that flags six things when one number changes is not sensitive; it
is noisy, and every extra finding lands on a real person. Collateral is where an
unfair rule shows itself, and it is measured here for that reason.

Mutations run against a saved baseline rather than the model, so a run is
deterministic and costs no inference: the model's own variance is measured
separately, by re-running extraction, and mixing the two would make neither
answerable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from cvv.models import (
    Claim,
    ClaimGraph,
    ClaimKind,
    ContestResult,
    DeploymentEvidence,
    EvidenceBundle,
    FuzzyDate,
    Gap,
    GapReason,
    Interval,
    Platform,
    Precision,
    RuleStatus,
)
from cvv.report import assemble

Pair = tuple[ClaimGraph, EvidenceBundle]
Mutator = Callable[[ClaimGraph, EvidenceBundle], Pair | None]


@dataclass(frozen=True)
class Mutation:
    """One corruption, and the rule that owes us a finding for it.

    `expect` is declared, never inferred from what happened. A mutation whose
    expected rule stays silent is a miss even when some other rule fires — "something
    noticed" is not the same as "the check responsible noticed", and conflating them
    is how a detection rate stops meaning anything.
    """

    mutation_id: str
    expect: str
    describes: str
    apply: Mutator


@dataclass(frozen=True)
class Outcome:
    mutation_id: str
    expect: str
    describes: str
    caught: bool
    collateral: list[str] = field(default_factory=list)
    skipped: str | None = None


# --------------------------------------------------------------------------- #
# Helpers — every mutation is a pure function on a copy
# --------------------------------------------------------------------------- #


def _claims(graph: ClaimGraph, kind: ClaimKind) -> list[Claim]:
    return [c for c in graph.claims if c.kind is kind]


def _with_claims(graph: ClaimGraph, claims: list[Claim]) -> ClaimGraph:
    return graph.model_copy(update={"claims": claims})


def _replace(graph: ClaimGraph, target: Claim, updated: Claim) -> ClaimGraph:
    return _with_claims(graph, [updated if c is target else c for c in graph.claims])


def _achievement(graph: ClaimGraph, platform: str, metric: str) -> Claim | None:
    return next(
        (
            c
            for c in _claims(graph, ClaimKind.ACHIEVEMENT)
            if (c.platform or "").lower() == platform and c.metric == metric
        ),
        None,
    )


def _year(y: int) -> FuzzyDate:
    return FuzzyDate(year=y, precision=Precision.YEAR)


# --------------------------------------------------------------------------- #
# The catalogue
# --------------------------------------------------------------------------- #


def _inflate_rating(g: ClaimGraph, b: EvidenceBundle) -> Pair | None:
    """The single most common CV inflation: a rating that never happened."""
    claim = _achievement(g, "codeforces", "max_rating")
    if claim is None or not isinstance(claim.value, int):
        return None
    return _replace(g, claim, claim.model_copy(update={"value": claim.value + 305})), b


def _inflate_rank(g: ClaimGraph, b: EvidenceBundle) -> Pair | None:
    claim = _achievement(g, "codeforces", "contest_rank")
    if claim is None or not isinstance(claim.value, int):
        return None
    return _replace(g, claim, claim.model_copy(update={"value": 40})), b


def _inflate_leetcode(g: ClaimGraph, b: EvidenceBundle) -> Pair | None:
    """A LeetCode count the platform contradicts, injected with its evidence."""
    achievement = next(iter(_claims(g, ClaimKind.ACHIEVEMENT)), None)
    if achievement is None:
        return None
    claim = achievement.model_copy(
        update={
            "claim_id": "cmut_lc",
            "platform": "leetcode",
            "metric": "problems_solved",
            "value": 900,
        }
    )
    from cvv.models import PlatformEvidence

    evidence = PlatformEvidence(
        platform=Platform.LEETCODE, handle="ar009", found=True, problems_solved=310
    )
    return (
        _with_claims(g, [*g.claims, claim]),
        b.model_copy(update={"platforms": [*b.platforms, evidence]}),
    )


def _account_missing(g: ClaimGraph, b: EvidenceBundle) -> Pair | None:
    """The account named on the CV does not exist."""
    if b.github is None:
        return None
    gap = Gap(
        source="github",
        reason=GapReason.NOT_FOUND,
        detail=f"No GitHub account exists at github.com/{b.github.handle}.",
    )
    return g, b.model_copy(update={"github": None, "gaps": [*b.gaps, gap]})


def _repo_is_a_fork(g: ClaimGraph, b: EvidenceBundle) -> Pair | None:
    if b.github is None or not b.github.repos:
        return None
    repos = [r.model_copy(update={"is_fork": True}) for r in b.github.repos]
    return g, b.model_copy(update={"github": b.github.model_copy(update={"repos": repos})})


def _repo_is_empty(g: ClaimGraph, b: EvidenceBundle) -> Pair | None:
    if b.github is None or not b.github.repos:
        return None
    first = b.github.repos[0]
    empty = first.model_copy(
        update={"is_readme_only": True, "authored_files": 0, "authored_bytes": 0}
    )
    repos = [empty, *b.github.repos[1:]]
    return g, b.model_copy(update={"github": b.github.model_copy(update={"repos": repos})})


def _wrong_stack(g: ClaimGraph, b: EvidenceBundle) -> Pair | None:
    """The CV describes a stack the linked repository does not contain."""
    project = next((c for c in _claims(g, ClaimKind.PROJECT) if c.skill_refs), None)
    if project is None:
        return None
    return _replace(g, project, project.model_copy(update={"skill_refs": ["Go", "Redis"]})), b


def _silent_window(g: ClaimGraph, b: EvidenceBundle) -> Pair | None:
    """No public activity at all in the months a project claims."""
    if b.github is None or not b.github.contribution_windows:
        return None
    quiet = [
        w.model_copy(update={"commit_count": 0, "active_days": 0})
        for w in b.github.contribution_windows
    ]
    return g, b.model_copy(
        update={"github": b.github.model_copy(update={"contribution_windows": quiet})}
    )


def _anachronism(g: ClaimGraph, b: EvidenceBundle) -> Pair | None:
    """A project dated before the technology it names existed."""
    project = next((c for c in _claims(g, ClaimKind.PROJECT) if c.skill_refs), None)
    if project is None:
        return None
    old = Interval(start=_year(2011), end=_year(2012))
    return (
        _replace(
            g,
            project,
            project.model_copy(update={"interval": old, "skill_refs": ["React", "Next.js"]}),
        ),
        b,
    )


def _roll_year(g: ClaimGraph, b: EvidenceBundle) -> Pair | None:
    """A roll number whose admission year cannot reach the claimed graduation."""
    roll = next((c for c in _claims(g, ClaimKind.IDENTIFIER) if c.parsed), None)
    if roll is None:
        return None
    parsed = {**(roll.parsed or {}), "admission_year": 2015}
    return _replace(g, roll, roll.model_copy(update={"parsed": parsed})), b


def _concurrent_roles(g: ClaimGraph, b: EvidenceBundle) -> Pair | None:
    """Two full-time roles over the same months."""
    from cvv.models import EmploymentType

    base = next(iter(_claims(g, ClaimKind.ACHIEVEMENT)), None)
    if base is None:
        return None
    span = Interval(
        start=FuzzyDate(year=2024, month=1, precision=Precision.MONTH),
        end=FuzzyDate(year=2024, month=12, precision=Precision.MONTH),
    )
    common = {
        "kind": ClaimKind.EMPLOYMENT,
        "interval": span,
        "employment_type": EmploymentType.FULL_TIME,
        "title": "Engineer",
        "platform": None,
        "metric": None,
        "value": None,
    }
    a = base.model_copy(update={**common, "claim_id": "cmut_e1", "org": "Acme"})
    c = base.model_copy(update={**common, "claim_id": "cmut_e2", "org": "Globex"})
    return _with_claims(g, [*g.claims, a, c]), b


def _same_role_twice(g: ClaimGraph, b: EvidenceBundle) -> Pair | None:
    """One role, two mentions, dates that cannot both be true."""
    from cvv.models import EmploymentType

    base = next(iter(_claims(g, ClaimKind.ACHIEVEMENT)), None)
    if base is None:
        return None
    common = {
        "kind": ClaimKind.EMPLOYMENT,
        "org": "Acme",
        "title": "Engineer",
        "employment_type": EmploymentType.INTERNSHIP,
        "platform": None,
        "metric": None,
        "value": None,
    }
    a = base.model_copy(update={**common, "claim_id": "cmut_d1",
                                "interval": Interval(start=_year(2022), end=_year(2022))})
    c = base.model_copy(update={**common, "claim_id": "cmut_d2",
                                "interval": Interval(start=_year(2024), end=_year(2024))})
    return _with_claims(g, [*g.claims, a, c]), b


def _degree_span(g: ClaimGraph, b: EvidenceBundle) -> Pair | None:
    degree = next(iter(_claims(g, ClaimKind.EDUCATION)), None)
    if degree is None or not degree.degree:
        return None
    stretched = Interval(start=_year(2020), end=_year(2027))
    return _replace(g, degree, degree.model_copy(update={"interval": stretched})), b


def _dead_deployment(g: ClaimGraph, b: EvidenceBundle) -> Pair | None:
    if not b.deployments:
        return None
    dead = [
        DeploymentEvidence(url=d.url, reachable=False, status_code=404, checked_at=d.checked_at)
        for d in b.deployments
    ]
    return g, b.model_copy(update={"deployments": dead})


def _contest_absent(g: ClaimGraph, b: EvidenceBundle) -> Pair | None:
    """The named contest is not in the account's history at all."""
    cf = next((p for p in b.platforms if p.platform is Platform.CODEFORCES), None)
    if cf is None or not cf.contests:
        return None
    other = [
        ContestResult(name="Codeforces Round 512 (Div. 2)", rank=c.rank, rating_after=c.rating_after)
        for c in cf.contests
    ]
    platforms = [
        p.model_copy(update={"contests": other}) if p is cf else p for p in b.platforms
    ]
    return g, b.model_copy(update={"platforms": platforms})


CATALOGUE: list[Mutation] = [
    Mutation("rating-inflated", "P1", "Codeforces rating raised by 305", _inflate_rating),
    Mutation("rank-inflated", "P2", "contest rank improved to 40", _inflate_rank),
    Mutation("contest-absent", "P2", "the named contest removed from history", _contest_absent),
    Mutation("leetcode-inflated", "P4", "900 LeetCode problems against 310", _inflate_leetcode),
    Mutation("account-missing", "G2", "the GitHub account does not resolve", _account_missing),
    Mutation("repo-forked", "G4", "every named repository is a fork", _repo_is_a_fork),
    Mutation("repo-empty", "G7", "a named repository holds nothing authored", _repo_is_empty),
    Mutation("stack-wrong", "G6", "the project claims Go and Redis", _wrong_stack),
    Mutation("window-silent", "G5", "no public activity in the claimed months", _silent_window),
    Mutation("anachronism", "D7", "React claimed on a 2011-2012 project", _anachronism),
    Mutation("roll-year", "D9", "admission year cannot reach graduation", _roll_year),
    Mutation("roles-concurrent", "D5", "two full-time roles over the same year", _concurrent_roles),
    Mutation("role-twice", "D10", "one role dated two incompatible ways", _same_role_twice),
    Mutation("degree-stretched", "D8", "a 4-year degree claimed over 7", _degree_span),
    Mutation("deployment-dead", "W1", "every live URL returns 404", _dead_deployment),
]


# --------------------------------------------------------------------------- #
# Running it
# --------------------------------------------------------------------------- #


def _fired(graph: ClaimGraph, bundle: EvidenceBundle) -> set[str]:
    report = assemble(graph, bundle, report_id="fr_eval")
    return {
        o.rule_id for o in report.rule_outcomes if o.status is RuleStatus.FIRED
    }


def run(graph: ClaimGraph, bundle: EvidenceBundle) -> tuple[set[str], list[Outcome]]:
    """The baseline's own findings, then one run per mutation.

    Baseline findings are subtracted from every mutated run, so a rule that already
    fires on the honest document is never counted as collateral. That subtraction is
    the reason the baseline set is returned too: a reader must be able to see what
    was excused.
    """
    baseline = _fired(graph, bundle)
    outcomes: list[Outcome] = []

    for mutation in CATALOGUE:
        mutated = mutation.apply(graph, bundle)
        if mutated is None:
            outcomes.append(
                Outcome(
                    mutation.mutation_id,
                    mutation.expect,
                    mutation.describes,
                    caught=False,
                    skipped="the document carries nothing to corrupt this way",
                )
            )
            continue

        fired = _fired(*mutated)
        outcomes.append(
            Outcome(
                mutation.mutation_id,
                mutation.expect,
                mutation.describes,
                caught=mutation.expect in fired,
                collateral=sorted(fired - baseline - {mutation.expect}),
            )
        )
    return baseline, outcomes


def render_evaluation(baseline: set[str], outcomes: list[Outcome]) -> str:
    applied = [o for o in outcomes if o.skipped is None]
    caught = [o for o in applied if o.caught]
    collateral = sum(len(o.collateral) for o in applied)

    out = ["=" * 78, "  MUTATION EVALUATION", "=" * 78, ""]
    out.append(f"  {'MUTATION':22} {'EXPECT':7} {'CAUGHT':7} COLLATERAL")
    for o in outcomes:
        if o.skipped:
            out.append(f"  {o.mutation_id:22} {o.expect:7} {'skip':7} {o.skipped}")
            continue
        mark = "yes" if o.caught else "NO"
        out.append(
            f"  {o.mutation_id:22} {o.expect:7} {mark:7} "
            + (", ".join(o.collateral) or "—")
        )

    rate = len(caught) / len(applied) if applied else 0.0
    out += [
        "",
        "-" * 78,
        f"  detection    {len(caught)}/{len(applied)} ({rate:.0%}) of applied mutations "
        "caught by the rule responsible",
        f"  collateral   {collateral} finding(s) from rules the mutation did not concern",
        f"  baseline     {', '.join(sorted(baseline)) or 'nothing'} fired on the "
        "unmutated document and is excused throughout",
        "",
        "  Detection is the number a thesis quotes. Collateral is the number that says",
        "  whether the system is sensitive or merely noisy — every extra finding lands",
        "  on a real person.",
        "=" * 78,
    ]
    return "\n".join(out)
