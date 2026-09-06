"""What a person still has to do, prepared.

The H group — seniority, portfolio substance, code quality in context, whether an
explanation satisfies, any contested finding, the decision itself — is human by
design. So are degree, CGPA, employment and identity, which no accessible source can
settle. Naming them and stopping there would be honest but useless: a reviewer who is
told "the degree was not verified" still has to work out which institution, which
roll number, and what to ask.

This module does that work. Every line it emits is derived from a claim or a finding
that already exists — it invents no fact, no contact and no question about anything
the CV did not say. Where the operator has supplied a verification contact in
`data/institutions.json` it is printed; where they have not, the worksheet says whom
to look for by role rather than inventing an address.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cvv.models import ClaimGraph, ClaimKind, FindingsReport, Tier
from cvv.reference import institution_contact


@dataclass(frozen=True)
class Task:
    """One thing a person must do, with everything they need to do it."""

    task_id: str
    section: str
    ask: str
    of: str
    why: str
    context: list[str] = field(default_factory=list)


def _roll_context(graph: ClaimGraph) -> list[str]:
    """The roll number, decoded. D9 already parsed it; the reviewer gets the parse."""
    out: list[str] = []
    for claim in graph.claims:
        if claim.kind is not ClaimKind.IDENTIFIER or not claim.parsed:
            continue
        parsed = claim.parsed
        out.append(
            f"roll {claim.provenance.verbatim} decodes to admission year "
            f"{parsed.get('admission_year')}, department code "
            f"{parsed.get('dept_code')}, serial {parsed.get('serial')}"
        )
    return out


def institution_tasks(graph: ClaimGraph) -> list[Task]:
    """Degree and CGPA. Only the awarding institution can confirm these."""
    tasks: list[Task] = []
    roll = _roll_context(graph)

    for claim in graph.claims:
        if claim.kind is not ClaimKind.EDUCATION or not claim.org:
            continue
        # A single-year education claim is a completion year, not an open range —
        # the CDC template prints it in a leading column. Rendering it as "from 2027
        # to ongoing" told a reviewer something the CV never said.
        span = ""
        if claim.interval and claim.interval.end:
            span = f", programme running {claim.interval.start.year}-{claim.interval.end.year}"
        elif claim.interval:
            span = f" (the CV states {claim.interval.start.year})"

        contact = institution_contact(claim.org)
        tasks.append(
            Task(
                task_id=f"MC-{claim.claim_id}",
                section="Ask the institution",
                ask=(
                    f"Confirm that {claim.degree or 'the qualification claimed'} was "
                    f"awarded{span}, and confirm the CGPA or percentage if one is stated."
                ),
                of=contact or f"{claim.org} — academic / examinations section",
                why=(
                    "Degree and CGPA have no accessible source. Only the awarding "
                    "institution can confirm them, and this system never implies "
                    "otherwise."
                ),
                context=[f"as written on the CV: {claim.provenance.verbatim[:90]!r}", *roll],
            )
        )
    return tasks


def employer_tasks(graph: ClaimGraph, report: FindingsReport) -> list[Task]:
    """Employment. Activity data corroborates a period; it never confirms a job."""
    corroborated = [
        outcome.note
        for outcome in report.rule_outcomes
        if outcome.rule_id in ("G10", "G11") and outcome.note
    ]
    tasks: list[Task] = []

    for claim in graph.claims:
        if claim.kind is not ClaimKind.EMPLOYMENT or not claim.org:
            continue
        dates = ""
        if claim.interval:
            end = claim.interval.end.year if claim.interval.end else "present"
            dates = f", dated {claim.interval.start.year} to {end}"
        tasks.append(
            Task(
                task_id=f"MC-{claim.claim_id}",
                section="Ask the employer",
                ask=(
                    f"Confirm the role {claim.title or 'as claimed'}{dates}, and its "
                    "employment type."
                ),
                of=claim.org,
                why=(
                    "Employment cannot be verified without the employer. Public "
                    "activity corroborates a period of work; it never confirms a job."
                ),
                context=corroborated,
            )
        )
    return tasks


def candidate_tasks(graph: ClaimGraph, report: FindingsReport) -> list[Task]:
    """H4 and H5 — every attention finding is a question, not a conclusion.

    An attention finding carries its innocent reading by construction, so the task is
    always "put this to the candidate and hear the answer", never "treat this as
    established". H5 exists because a contested finding is exactly the point at which
    automation has reached its limit.
    """
    # `scoring` is the filter, and it is exactly the right one. A non-scoring finding
    # describes the EXTRACTION (D2), the DOCUMENT (D3, D4), a career's shape (D11,
    # D12) or a naming habit (P6, G3) — never a claim the candidate made. Turning one
    # into "ask how this came about" produced three questions nobody could answer:
    # the candidate does not know why our extractor dropped a proposal, did not write
    # their own CDC's disclaimer, and owes nobody an account of a gap in their dates.
    tasks = [
        Task(
            task_id=f"MC-{f.finding_id}",
            section="Ask the candidate",
            ask=f"{f.explanation} Ask how this came about.",
            of="the candidate",
            why=(
                "H4/H5 — only a person can hear an explanation, and a contested "
                "finding is the signal that automation has reached its limit."
            ),
            context=[f"benign reading already on record: {f.innocent_explanation}"]
            if f.innocent_explanation
            else [],
        )
        for f in report.discrepancies
        if f.tier is Tier.ATTENTION and f.scoring
    ]

    # G3: the one manual step that CHANGES a machine result rather than replacing it.
    handles = [
        c.handle
        for c in graph.claims
        if c.kind is ClaimKind.PROFILE and (c.platform or "") == "github" and c.handle
    ]
    if any(o.rule_id == "G3" and o.status.value == "fired" for o in report.rule_outcomes):
        tasks.append(
            Task(
                task_id="MC-ownership",
                section="Ask the candidate",
                ask=(
                    "Ask them to prove control of "
                    + ", ".join(f"github.com/{h}" for h in handles)
                    + " — a gist, a commit, or a profile-bio string you supply."
                ),
                of="the candidate",
                why=(
                    "G3. Public data can never bind an account to a person. Proving "
                    "control raises the weight of every finding from that account "
                    "that CORROBORATES the CV; it creates no new findings, and "
                    "declining to do it is not a mark against anyone."
                ),
            )
        )
    return tasks


def look_tasks(graph: ClaimGraph, report: FindingsReport) -> list[Task]:
    """W2 — a URL responding is not a URL doing what the CV says it does."""
    return [
        Task(
            # The host, not a tail slice — "MC-tps://atma-ar.vercel.app" is what
            # slicing a URL from the end gives you.
            task_id=f"MC-{artefact.url.split('//')[-1].split('/')[0]}",
            section="Open and look",
            ask=(
                f"Open {artefact.url} and confirm it does what {claim.title or 'the CV'} "
                "describes."
            ),
            of="you",
            why=(
                "W1 proved the URL responds. Whether the thing behind it matches the "
                "description is W2, and no machine reads a screen for meaning."
            ),
            context=[f"claimed: {claim.provenance.verbatim[:110]!r}"],
        )
        for claim in graph.claims
        for artefact in claim.artefacts
        if artefact.type.value == "deployment"
    ]


JUDGEMENT = [
    ("H1", "Does the work match the claimed seniority?",
     "Requires a role model this system does not hold and must not invent."),
    ("H2", "Is the portfolio substantial for this level?",
     "Norms differ by institution, year and market; encoding them encodes bias."),
    ("H3", "Code quality in context",
     "Static metrics do not survive contact with intent and constraints."),
    ("H6", "The hiring decision",
     "Not the system's to make, under any configuration."),
]


def worksheet(graph: ClaimGraph, report: FindingsReport) -> list[Task]:
    """Every manual task this document generates, in the order a reviewer works."""
    return [
        *institution_tasks(graph),
        *employer_tasks(graph, report),
        *candidate_tasks(graph, report),
        *look_tasks(graph, report),
    ]


def render_worksheet(graph: ClaimGraph, report: FindingsReport) -> str:
    """What `cvv worksheet` prints."""
    tasks = worksheet(graph, report)
    out: list[str] = ["=" * 78, "  MANUAL CHECK WORKSHEET", f"  {len(tasks)} task(s)", "=" * 78]

    section = ""
    for task in tasks:
        if task.section != section:
            section = task.section
            out += ["", section.upper(), "-" * 78]
        out += [f"  [{task.task_id}]  of: {task.of}", f"      {task.ask}",
                f"      why: {task.why}"]
        out += [f"      · {line}" for line in task.context if line]
        out.append("")

    out += ["", "JUDGEMENT ONLY — no machine result exists or should", "-" * 78]
    out += [f"  [{i}] {q}\n      {w}" for i, q, w in JUDGEMENT]
    out += ["", "=" * 78,
            "  Nothing above is a finding. These are the questions the evidence",
            "  could not answer, prepared so a person can answer them.",
            "=" * 78]
    return "\n".join(out)
