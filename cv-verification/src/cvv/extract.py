"""Text to claims — the one place a model is involved in extraction.

The model proposes; deterministic code decides what is real. Everything it returns is
a hypothesis until `ground()` confirms it against the document.

Three things this module learned from running against a real CV:

1. **Narrow passes, not one wide call.** A single call with every field optional
   returned 18 claims carrying `kind` and `verbatim` and nothing else — the model
   segmented the document and populated none of it. Four narrow calls with `required`
   in the schema returned every value correctly. `required` is the lever.

2. **A prompt is not an enforcement mechanism.** `qwen3:4b`, told explicitly to ignore
   JEE ranks, returned them anyway. Anything the design excludes is dropped by code
   after extraction.

3. **Some things need no model at all — but only two.** Both models missed the roll
   number and the repository URLs. Those have a grammar rather than a phrasing, so a
   pattern finds them every time. Handles and the institution's disclaimer used to be
   regexes too, and each one encoded how one CV happened to be worded; they are model
   passes now (guardrail 10, and `regex_claims` below).
"""

from __future__ import annotations

import datetime
import re
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from cvv.dates import parse_interval, slash_convention
from cvv.filters import GITHUB_REPO
from cvv.filters import apply as apply_filters
from cvv.ids import claim_id
from cvv.ingest import Document, Section, input_hash, line_at, section_text, sections
from cvv.logs import get
from cvv.models import (
    Artefact,
    ArtefactType,
    Claim,
    ClaimGraph,
    ClaimKind,
    EmploymentType,
    ExtractionMeta,
    Platform,
    Proficiency,
    SourceInfo,
    SpanProvenance,
)
from cvv.providers import LLMProvider, default_provider
from cvv.reference import named_scheme, roll_patterns
from cvv.spans import recover_span, recover_token

log = get("cvv.extract")

PROMPT_VERSION = "extract/v2-narrow"

COPY_EXACTLY = (
    "`verbatim` MUST be copied from the CV character for character. Never paraphrase, "
    "never correct a typo, never round a number. If you cannot copy it exactly, omit "
    "the claim. Never invent a claim: if the CV does not say it, it does not exist."
)


class ProposedClaim(BaseModel):
    """What a model is allowed to say.

    Note what is absent: no character offsets (LLMs cannot count characters) and no
    parsed dates (precision drives the interval algebra, and a model asked about
    `2022-26` will confidently guess). It returns the date TEXT; our parser reads it.
    """

    model_config = ConfigDict(extra="ignore")

    kind: ClaimKind
    verbatim: str = ""
    org: str | None = None
    title: str | None = None
    degree: str | None = None
    platform: str | None = None
    handle: str | None = None
    metric: str | None = None
    value: int | float | str | None = None
    qualifier: str | None = None
    contest: str | None = None
    skill_refs: list[str] = Field(default_factory=list)
    proficiency: Proficiency | None = None
    stated_years: int | float | None = None
    employment_type: EmploymentType | None = None
    date_text: str | None = None
    urls: list[str] = Field(default_factory=list)
    # skills pass only — one item per technology, grouped into a claim per line
    name: str | None = None
    category: str | None = None
    years: float | None = None
    categories: dict[str, str] = Field(default_factory=dict)

    # Set by the caller after validation, never by the model (extra="ignore" drops
    # anything the model tries to put here). The span search is scoped to this window
    # so a verbatim that occurs twice in the CV resolves inside its own section.
    window_start: int = 0
    window_end: int | None = None


@dataclass(frozen=True)
class Pass:
    """One narrow extraction call.

    `required` is the whole point. When a field is optional the grammar permits the
    model to skip it, and a small model will.
    """

    name: str
    kind: ClaimKind
    instruction: str
    properties: dict[str, Any]
    required: list[str] = field(default_factory=lambda: ["verbatim"])
    # Headings whose section this pass reads. Empty means the whole document.
    sections: tuple[str, ...] = ()
    # Or a fraction of the document from one end, for a fact that lives under no
    # heading at all. Positional windows carry no assumption about WORDING, which is
    # the point — a phrase-matching window is the regex this replaced.
    footer: float = 0.0
    header: float = 0.0
    # The routing category this pass consumes, when the model identifies one.
    routes_to: str = ""
    # Force at least this many items. A pass whose honest answer is usually "none"
    # gets nothing at all from a small model otherwise — the summary pass returned an
    # empty list for a CV reading "3 yrs of hands-on industry experience", because an
    # empty list was permitted and is always the cheaper answer. Made mandatory, the
    # model has to look; a zero is then a real answer and is dropped downstream.
    min_items: int = 0

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "claims": {
                    "type": "array",
                    "minItems": self.min_items,
                    "items": {
                        "type": "object",
                        "properties": self.properties,
                        "required": self.required,
                    },
                }
            },
            "required": ["claims"],
        }

    def prompt(self, text: str) -> str:
        return f"{self.instruction}\n\n{COPY_EXACTLY}\n\nReturn JSON only.\n\nCV:\n{text}"


_STR = {"type": "string"}

PASSES: list[Pass] = [
    Pass(
        name="achievements",
        routes_to="achievements",
        sections=("ACHIEVEMENT", "AWARD"),
        kind=ClaimKind.ACHIEVEMENT,
        instruction=(
            "Extract every competitive-programming achievement from this CV.\n"
            "  platform   codeforces | codechef | leetcode | atcoder | hackerrank\n"
            "  metric     max_rating | contest_rank | problems_solved\n"
            "  value      the number, as an integer\n"
            "  qualifier  the rank title in brackets, e.g. Specialist, 3-Star\n"
            "  contest    the contest's name as written, for a rank. Empty otherwise\n"
            "  handle     the account handle, if the sentence states one"
        ),
        properties={
            "verbatim": _STR,
            "platform": _STR,
            "metric": {"type": "string", "enum": ["max_rating", "contest_rank", "problems_solved"]},
            "value": {"type": "integer"},
            "qualifier": _STR,
            "handle": _STR,
            "contest": _STR,
        },
        # `contest` is REQUIRED so the key is always emitted — an optional field is
        # one a small model skips. An empty string is the legitimate answer for a
        # rating or a problem count, and the span check drops anything unsupported.
        required=["verbatim", "platform", "metric", "value", "contest"],
    ),
    Pass(
        name="projects",
        routes_to="projects",
        sections=("PROJECT",),
        kind=ClaimKind.PROJECT,
        instruction=(
            "Extract every project from this CV.\n"
            "  title      the project name\n"
            "  urls       every URL belonging to the project, copied exactly\n"
            "  date_text  the date range exactly as written, e.g. \"Mar '25 - Apr '25\"\n"
            "  org        the institution, if the project names one\n"
            "  skill_refs every technology the project's bullets name — languages,\n"
            "             frameworks, libraries, databases — each copied exactly\n"
            "\n"
            "A feature is not a technology. 'Edge editing', 'real-time validation' and\n"
            "'path highlighting' are things the project DOES; React, Postgres and\n"
            "Docker are things it is BUILT WITH. Name only the second kind."
        ),
        properties={
            "verbatim": _STR,
            "title": _STR,
            "urls": {"type": "array", "items": _STR},
            "date_text": _STR,
            "org": _STR,
            "skill_refs": {"type": "array", "items": _STR},
        },
        # skill_refs is required so the key is always emitted — an optional field is
        # one a small model skips. An empty list is a legitimate answer; a missing
        # key is a silently unchecked stack.
        required=["verbatim", "title", "skill_refs"],
    ),
    Pass(
        name="employment",
        routes_to="employment",
        # Headings vary more here than anywhere else on a CV. Missing the section is
        # not fatal — section_text falls back to the whole document, just with a
        # wider window and worse precision.
        sections=("EXPERIENCE", "EMPLOYMENT", "WORK", "INTERNSHIP", "PROFESSIONAL"),
        kind=ClaimKind.EMPLOYMENT,
        instruction=(
            "Extract every job, internship or professional role from this CV.\n"
            "  org              the employer\n"
            "  title            the role title, as written\n"
            "  employment_type  full_time | part_time | internship | freelance\n"
            "  date_text        the date range exactly as written, e.g. "
            '"Jun 2024 - Aug 2024"\n'
            "\n"
            "A university is an employer only for a paid role there. A degree is not a "
            "job, and a course project is not an internship."
        ),
        properties={
            "verbatim": _STR,
            "org": _STR,
            "title": _STR,
            "employment_type": {
                "type": "string",
                "enum": ["full_time", "part_time", "internship", "freelance"],
            },
            "date_text": _STR,
        },
        required=["verbatim", "org", "title"],
    ),
    Pass(
        name="education",
        routes_to="education",
        sections=("EDUCATION",),
        kind=ClaimKind.EDUCATION,
        instruction=(
            "Extract every degree, diploma or school examination from this CV.\n"
            "  degree     the qualification, e.g. B.Tech, CBSE Class XII\n"
            "  org        the institution awarding it\n"
            "  date_text  the year exactly as written"
        ),
        properties={"verbatim": _STR, "degree": _STR, "org": _STR, "date_text": _STR},
        required=["verbatim", "degree", "org"],
    ),
    Pass(
        name="skills",
        routes_to="skills",
        sections=("SKILL", "EXPERTISE"),
        kind=ClaimKind.SKILL,
        instruction=(
            "Categorise every technology named in this CV section.\n"
            "  name      the technology, exactly as written\n"
            "  category  language | framework | library | tool | concept | not_a_skill\n"
            "  years     years of experience the line states for it, or 0 if none\n"
            "\n"
            "Use not_a_skill for a heading or category label rather than a skill: a line\n"
            "reading 'Frameworks and Libraries : Next.js | Express.js' names two skills,\n"
            "and 'Frameworks and Libraries' is not one of them."
        ),
        # No `verbatim` here, deliberately. Asking for both `name` and `verbatim`
        # made the model set them equal and return the whole line as the skill name.
        # The line is derived from where the name sits — see group_skills().
        properties={
            "name": _STR,
            # The enum is what does the work. The prompt DESCRIBES the categories; the
            # schema CONSTRAINS them, and Ollama grammar-constrains generation to the
            # schema — so a seventh category is unreachable rather than discouraged.
            "category": {
                "type": "string",
                "enum": ["language", "framework", "library", "tool", "concept", "not_a_skill"],
            },
            "years": {"type": "number"},
        },
        required=["name", "category", "years"],
    ),
    Pass(
        name="summary",
        # The top of the page. A stated total of experience is a headline claim and
        # lives above everything else; it is also written a hundred ways — "5+ years
        # of professional experience", "8 yrs in industry", "since 2016" — which is
        # exactly what a regex could not follow.
        header=0.15,
        kind=ClaimKind.EMPLOYMENT,
        instruction=(
            "Extract the candidate's stated total professional experience from this "
            "CV header.\n"
            "  verbatim  the phrase that states it, copied exactly from the text\n"
            "  years     the number of years that phrase states\n"
            "\n"
            "A total is one figure covering the whole career — years of professional, "
            "industry, or hands-on experience. One job's dates are not a total, a "
            "degree's length is not a total, and a course is not a total.\n"
            "\n"
            "Answer with exactly one entry. Where the header states no total, answer "
            "years 0 with an empty verbatim."
        ),
        properties={"verbatim": _STR, "years": {"type": "number"}},
        required=["verbatim", "years"],
        min_items=1,
    ),
    Pass(
        name="declarations",
        # POSITIONAL, not by heading: an issuer's disclaimer lives in a footer, under
        # no heading at all. `footer` is a fraction of the document rather than a
        # phrase to look for, so it carries no assumption about how any institution
        # words its disclaimer — which is the whole reason this replaced a regex.
        footer=0.2,
        kind=ClaimKind.DECLARATION_MARKER,
        instruction=(
            "Find any statement in this document, written by the INSTITUTION that "
            "issued it rather than by the candidate, about what the institution did "
            "not itself verify.\n"
            "  verbatim  that sentence, copied exactly\n"
            "\n"
            "It is usually a footer. Return an empty list if there is none — most "
            "documents have none, and inventing one would misdescribe the document."
        ),
        properties={"verbatim": _STR},
        required=["verbatim"],
    ),
    Pass(
        name="handles",
        routes_to="achievements",
        # Handles sit beside the achievements that cite them, or in a links or
        # contact block. Whole-document was measured and is worse than useless here:
        # qwen3:1.7b returned project titles as handles and stamped 'AR009' onto
        # three of them — guardrail 7's failure, reached through guardrail 8's.
        sections=("ACHIEVEMENT", "AWARD", "PROFILE", "LINK", "CONTACT", "CODING"),
        kind=ClaimKind.PROFILE,
        instruction=(
            "List every account name this CV states for an online platform.\n"
            "  platform  codeforces | codechef | leetcode | atcoder | hackerrank |\n"
            "            github | gitlab | kaggle\n"
            "  handle    the account name, copied exactly, character for character\n"
            "\n"
            "The CV may write it in any form — 'handle: ar009', 'Codeforces: ar009', "
            "a profile URL, or a name in brackets after a rating. Copy the account "
            "name exactly as printed, including its capitalisation."
        ),
        # No `verbatim`, for the reason the skills pass has none: asked for both, the
        # model COMPOSES one. It returned "Codeforces: AR009" for a document that
        # says "(handle: AR009)" — a phrase that is not in the CV, so grounding
        # dropped it and eleven proposals with it. The handle is a token; the line it
        # sits on is found here, the way group_skills does it.
        properties={"platform": _STR, "handle": _STR},
        required=["platform", "handle"],
    ),
]


# --------------------------------------------------------------------------- #
# Deterministic pre-pass — no model
# --------------------------------------------------------------------------- #


def regex_claims(text: str) -> list[ProposedClaim]:
    """The three things both models missed entirely, and one they only found by luck.

    Two things, and only two, because only two have a grammar rather than a
    convention. A roll number's shape is declared per institution in
    `data/roll-schemes.json`; a URL's shape is declared by the internet. Everything
    else a regex used to take here — the disclaimer, labelled handles, years of
    experience, contest numbers — encoded how ONE document happened to be phrased,
    and returned nothing on a CV phrased differently. Those are model passes now.

    A URL stays because guardrail 1 is explicit that a model normalises tokens: it
    returns `ar-009` for `AR009`, the API 404s, and the report says a real account
    does not exist. The `handles` pass runs anyway, and the two agree or the span
    check drops the disagreement.

    A roll number stays for a different reason, measured: it is an unremarkable token
    in a wall of prose and a model has no semantic reason to emit it, while
    `23CS10004` decodes into an admission year and a department for a decisive check.
    """
    out: list[ProposedClaim] = []

    # Shapes come from data/roll-schemes.json, never from a pattern written here. A
    # hardcoded one finds one institution's roll numbers and silently finds nobody
    # else's, and adding an institution to the data file would not fix it.
    seen_rolls: set[str] = set()
    for _, pattern in roll_patterns():
        for m in pattern.finditer(text):
            if m.group(0) not in seen_rolls:
                seen_rolls.add(m.group(0))
                out.append(ProposedClaim(kind=ClaimKind.IDENTIFIER, verbatim=m.group(0)))

    # One entry per owner, keeping the FIRST URL that names them. The previous
    # version re-searched from the start of the document for every owner, so with two
    # owners both profile claims cited the first owner's URL — a verbatim that does
    # not contain the handle it carries. One owner hid it.
    first_url_by_owner: dict[str, str] = {}
    for m in GITHUB_REPO.finditer(text):
        first_url_by_owner.setdefault(m.group(1), m.group(0))
    for owner, url in sorted(first_url_by_owner.items()):
        out.append(
            ProposedClaim(
                kind=ClaimKind.PROFILE, verbatim=url, platform="github", handle=owner
            )
        )

    return out


# --------------------------------------------------------------------------- #
# The model calls
# --------------------------------------------------------------------------- #


def _call(p: Pass, text: str, offset: int, provider: LLMProvider) -> list[ProposedClaim]:
    raw = provider.complete_json(p.prompt(text), p.schema())
    claims: list[ProposedClaim] = []
    for item in raw.get("claims", []):
        item["kind"] = p.kind.value
        if "verbatim" not in p.properties:
            # This pass does not cite a span — the skills pass returns bare names and
            # the line is derived afterwards. Without this the item fails validation
            # and is swallowed by the except below, which is how the skills pass
            # silently returned zero claims.
            item["verbatim"] = ""
        try:
            claim = ProposedClaim.model_validate(item)
        except Exception:
            continue
        # The window is set here, never by the model. Grounding will refuse anything
        # outside it, which is what stops a confabulated claim being rescued by
        # matching text somewhere else in the document.
        claims.append(
            claim.model_copy(
                update={"window_start": offset, "window_end": offset + len(text)}
            )
        )
    return claims


def group_skills(
    skills: list[ProposedClaim], doc: Document, window: tuple[int, int]
) -> list[ProposedClaim]:
    """One item per technology in, one claim per source LINE out.

    The line is derived, not asked for. Requesting both `name` and `verbatim` made the
    model set them equal and return the whole line as the skill name — so it returns
    only the name, and `line_at` finds the line the name sits on.

    Line-level provenance rather than token-level: `recover_span` on "C" finds the
    first capital C in the window, which under a heading like "Core Skills" is inside
    the word "Core". A span covering one letter highlights nothing a reader can use.

    A name that is not in the section is dropped — guardrail 7, applied here.
    """
    lines: dict[tuple[int, int], dict[str, str]] = {}
    years: dict[tuple[int, int], set[float]] = {}
    lo, hi = window

    for p in skills:
        if not p.name or p.category == "not_a_skill":
            continue
        found = doc.text.lower().find(p.name.lower(), lo, hi)
        if found == -1:
            continue  # the section does not contain it
        key = line_at(doc, found)
        lines.setdefault(key, {})[p.name.lower()] = p.category or "unknown"
        if p.years:
            years.setdefault(key, set()).add(float(p.years))

    return [
        ProposedClaim(
            kind=ClaimKind.SKILL,
            verbatim=doc.text[start:end],
            skill_refs=sorted(categories),
            categories=categories,
            stated_years=_one_year(years.get((start, end))),
            window_start=start,
            window_end=end,
        )
        for (start, end), categories in lines.items()
        if categories
    ]


def _one_year(found: set[float] | None) -> float | None:
    """The line's stated experience, when the technologies on it agree.

    The model answers per TECHNOLOGY and the claim is per LINE, so "Python (5 years)
    | Go (2 years)" offers two numbers with no way to assign them. Ambiguity drops
    the field: the claim survives without it and G9 abstains, which beats attaching
    5 to the wrong language.

    This replaced a regex for `N years`, which found that phrasing and no other —
    not "8 yrs", not "since 2016", not a line in any other language.
    """
    return next(iter(found)) if found and len(found) == 1 else None


ROUTING = Pass(
    name="routing",
    kind=ClaimKind.SKILL,  # unused; routing produces no claim
    instruction=(
        "Below are the section headings of one CV, one per line. For each heading, "
        "say what that section holds.\n"
        "  heading   the heading, copied exactly\n"
        "  category  achievements | projects | employment | education | skills | other\n"
        "\n"
        "  achievements  contests, ratings, ranks, competitive programming, awards\n"
        "  projects      things the candidate built\n"
        "  employment    jobs, internships, professional roles\n"
        "  education     QUALIFICATIONS — degrees, schools, board examinations\n"
        "  coursework    individual COURSES taken, which are not qualifications\n"
        "  skills        technologies, languages, tools\n"
        "  other         anything else — publications, interests, references"
    ),
    properties={
        "heading": _STR,
        "category": {
            "type": "string",
            "enum": [
                "achievements", "projects", "employment",
                "education", "coursework", "skills", "other",
            ],
        },
    },
    required=["heading", "category"],
)


def route(doc: Document, provider: LLMProvider) -> dict[str, list[tuple[int, int]]]:
    """Which section each pass should read, decided by the model, not by keywords.

    `sections=("ACHIEVEMENT", "AWARD")` is a hardcoded convention in exactly the way
    a regex is. Measured on a second CV: its competitive-programming section is
    headed "COMPETITIVE PROGRAMMING", matched nothing, and the achievements pass fell
    back to the whole document — the failure mode guardrail 8 is entirely about. Two
    of three ratings and the only contest rank were lost, silently, on a CV that had
    done nothing wrong.

    One call, and the answer is verified: a heading the model returns must be a
    heading the document actually has, compared on normalised text. An unroutable
    document falls back to the keyword lists and then to the whole document, so this
    can improve the window and never break it.
    """
    found = sections(doc)
    if not found:
        return {}

    listing = "\n".join(s.heading for s in found)
    answer = provider.complete_json(ROUTING.prompt(listing), ROUTING.schema())
    by_heading = {_norm_text(s.heading): s for s in found}

    windows: dict[str, list[Section]] = {}
    for item in answer.get("claims") or []:
        if not isinstance(item, dict):
            continue
        section = by_heading.get(_norm_text(str(item.get("heading", ""))))
        category = str(item.get("category", ""))
        # `coursework` and `other` are routed so the model has somewhere honest to put
        # them, and consumed by no pass. Sending a coursework list to the education
        # pass turned "Computer Science" and "Mathematics" into degrees awarded by
        # "University", and D9 then picked one of those and abstained on a CV whose
        # actual B.Tech was sitting two claims away.
        if section is None or category in ("other", "coursework"):
            continue
        windows.setdefault(category, []).append(section)

    return {category: _runs(group) for category, group in windows.items()}


def _runs(group: list[Section]) -> list[tuple[int, int]]:
    """Routed sections as one window per CONTIGUOUS run, never one window overall.

    Sections are back-to-back — each runs to the next heading — so adjacent ones form
    a clean region and can be unioned. Non-adjacent ones cannot: the real CV routes
    both "EDUCATION" and "COURSEWORK INFORMATION" to education, correctly, and they
    sit at opposite ends of the page. Spanning them turned a 180-character window
    into a 4,252-character one holding every project and skill on the CV — the
    wide-window failure, arrived at by being RIGHT about the headings.

    Choosing between them was the next wrong answer: longest-first picked COURSEWORK
    over EDUCATION and would have lost every degree. There is no need to choose. The
    pass runs once per run, and the claims merge — one extra call on the uncommon CV
    that splits a topic in two.
    """
    ordered = sorted(group, key=lambda s: s.start)
    runs: list[list[Section]] = [[ordered[0]]]
    for section in ordered[1:]:
        if section.start == runs[-1][-1].end:
            runs[-1].append(section)
        else:
            runs.append([section])
    return [(run[0].start, run[-1].end) for run in runs]


def group_handles(
    handles: list[ProposedClaim], doc: Document, window: tuple[int, int]
) -> list[ProposedClaim]:
    """One handle per item in, one claim per source LINE out.

    The token is located with the DOCUMENT's casing — guardrail 1: a model returns
    `ar-009` for `AR009`, the API 404s, and the report says a real account does not
    exist.

    And it is located ON A LINE THAT NAMES ITS PLATFORM, which is guardrail 7 at the
    token level. A window-wide search takes the first textual match, so a CV carrying
    `AR009` on its Codeforces line and `ar009` on its CodeChef line gave BOTH claims
    the Codeforces line the moment the model miscased one of them — the pairing
    silently wrong while every field was individually real. A handle with no line
    naming its platform is dropped; the claim it would have made is not worth its
    risk of being about the wrong account.
    """
    out: list[ProposedClaim] = []
    lo, hi = window
    seen: set[tuple[str, str]] = set()
    lowered_text = doc.text.lower()

    for p in handles:
        if not p.handle or not p.platform:
            continue
        platform = p.platform.lower()

        found = -1
        cursor = lo
        while (hit := lowered_text.find(p.handle.lower(), cursor, hi)) != -1:
            start, end = line_at(doc, hit)
            if platform in lowered_text[start:end]:
                found = hit
                break
            cursor = hit + 1
        if found == -1:
            continue

        actual = doc.text[found : found + len(p.handle)]
        key = (platform, actual)
        if key in seen:
            continue
        seen.add(key)
        start, end = line_at(doc, found)
        out.append(
            ProposedClaim(
                kind=ClaimKind.PROFILE,
                verbatim=doc.text[start:end],
                platform=platform,
                handle=actual,
                window_start=start,
                window_end=end,
            )
        )
    return out


def propose(doc: Document, provider: LLMProvider) -> tuple[list[ProposedClaim], dict[str, int]]:
    """Deterministic pre-pass, then one narrow model call per claim kind — each
    against its own section rather than the whole CV.

    The window is the single biggest lever on extraction quality. Given the whole
    document, qwen3:1.7b found one achievement and stamped its field values onto
    fourteen unrelated sentences; given the 817-character achievements section, the
    same model and seed got all four right.
    """
    proposed = regex_claims(doc.text)
    counts = {"regex": len(proposed)}

    # The model says which heading holds what, and the keyword lists become the
    # fallback rather than the mechanism.
    try:
        routed = route(doc, provider)
    except Exception as exc:  # routing is an optimisation; never let it fail a run
        log.warning("routing.failed", error=type(exc).__name__)
        routed = {}
    counts["routing"] = len(routed)
    log.debug("routing.done", categories=sorted(routed))

    for p in PASSES:
        if windows := routed.get(p.routes_to):
            pass  # the model identified the section(s) this pass reads
        elif p.sections:
            text, offset = section_text(doc, p.sections)
            windows = [(offset, offset + len(text))]
        elif p.footer:
            windows = [(int(len(doc.text) * (1 - p.footer)), len(doc.text))]
        elif p.header:
            windows = [(0, int(len(doc.text) * p.header))]
        else:
            windows = [(0, len(doc.text))]

        began = time.monotonic()
        found: list[ProposedClaim] = []
        for offset, end in windows:
            batch = _call(p, doc.text[offset:end], offset, provider)
            if p.name == "summary":
                # `years: 0` is the pass's way of saying "no total stated", which is
                # the answer for most CVs. It is not a claim about anybody.
                batch = [c for c in batch if c.years and c.years > 0]
            if p.kind is ClaimKind.SKILL and p.name == "skills":
                batch = group_skills(batch, doc, (offset, end))
            elif p.name == "handles":
                batch = group_handles(batch, doc, (offset, end))
            found.extend(batch)

        counts[p.name] = len(found)
        log.debug(
            "pass.done",
            pass_name=p.name,
            windows=len(windows),
            chars=sum(end - start for start, end in windows),
            proposed=len(found),
            seconds=round(time.monotonic() - began, 1),
        )
        proposed.extend(found)
    return proposed, counts


# --------------------------------------------------------------------------- #
# Grounding — where a proposal becomes a claim, or does not
# --------------------------------------------------------------------------- #


def _artefact(url: str) -> Artefact:
    is_repo = "github.com/" in url
    return Artefact(
        type=ArtefactType.REPO if is_repo else ArtefactType.DEPLOYMENT,
        platform="github" if is_repo else None,
        url=url,
        owner=url.split("github.com/")[1].split("/")[0] if is_repo else None,
    )


def _norm_text(value: str) -> str:
    """Lowercase, and every run of non-alphanumerics collapsed to one space.

    So "Codeforces Round 998 (Div. 3)" and "codeforces round 998 div 3" compare
    equal — punctuation around a contest name varies between a CV and an API and
    carries no meaning.
    """
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _decode_roll(token: str, text: str) -> dict[str, Any] | None:
    """Named groups from the scheme of an institution the CV names, or None.

    Every group is optional. A scheme contributes exactly what its pattern declares —
    `year`, `dept` and `serial` for IIT Kharagpur — and a scheme that encodes less
    contributes less. D9 reads what is present and abstains on what is not.

    A roll-shaped token under no named institution is NOT decoded. It stays an
    identifier claim, because it is real text, and nothing is read into it.
    """
    scheme = named_scheme(token, text)
    m = re.match(str(scheme["pattern"]), token) if scheme else None
    if m is None:
        return None
    groups = m.groupdict()
    parsed: dict[str, Any] = {}
    if year := groups.get("year"):
        parsed["admission_year"] = 2000 + int(year) if len(year) == 2 else int(year)
    if dept := groups.get("dept"):
        parsed["dept_code"] = dept
    if serial := groups.get("serial"):
        parsed["serial"] = int(serial)
    return parsed or None


def scope_technologies(
    claims: list[Claim], windows: dict[str, tuple[int, int]], doc: Document
) -> list[Claim]:
    """Guardrail 7 for a project's stack, where "its own span" is bigger than a line.

    A project's technologies live in its bullets, not in the title the model quoted
    as the verbatim — so the region that must contain them is the project BLOCK: from
    this project's span to the next project's span, bounded by the section. Anything
    the model names outside that block is dropped, which stops the skills section at
    the bottom of the CV corroborating a stack the project never claimed.
    """
    projects = sorted(
        (c for c in claims if c.kind is ClaimKind.PROJECT),
        key=lambda c: c.provenance.char_start,
    )
    if not projects:
        return claims

    lowered = doc.text.lower()
    starts = [p.provenance.char_start for p in projects]
    scoped: dict[str, list[str]] = {}
    for i, project in enumerate(projects):
        section_end = windows.get(project.claim_id, (0, len(doc.text)))[1]
        end = starts[i + 1] if i + 1 < len(starts) else section_end
        block = lowered[project.provenance.char_start : max(end, project.provenance.char_end)]
        scoped[project.claim_id] = [t for t in project.skill_refs if t.lower() in block]

    return [
        c.model_copy(update={"skill_refs": scoped[c.claim_id]}) if c.claim_id in scoped else c
        for c in claims
    ]


def ground(
    proposed: list[ProposedClaim], doc: Document, *, model_id: str, graph_id: str
) -> ClaimGraph:
    """Pure Python. No model.

    A claim survives only if its verbatim is in the document. Token-shaped fields are
    then re-read from the document rather than taken from the model.
    """
    claims: list[Claim] = []
    windows: dict[str, tuple[int, int]] = {}
    span_failures = 0
    seen: set[str] = set()

    # Whether this document writes 02/05/2024 as the 2nd of May or the 5th of
    # February. Nothing in one date can answer it; the rest of the page can, because
    # a CV writing 01/26/2024 anywhere has shown its hand. Computed once, over the
    # whole document, and applied to every date in it.
    slash_order = slash_convention(doc.text)

    for p in proposed:
        span = recover_span(
            p.verbatim, doc.text, window=(p.window_start, p.window_end or len(doc.text))
        )
        if span is None:
            span_failures += 1
            continue

        # A handle absent from the claim's own span is dropped; the CLAIM is not.
        # "peak Codeforces rating of 1495" is checkable whether or not the handle sits
        # in that same sentence — the profile claim from the regex pre-pass carries it.
        # Dropping the whole claim here cost seven claims and both handles.
        handle = recover_token(p.handle, doc.text, within=span) if p.handle else None

        urls = [u for u in p.urls if recover_token(u, doc.text) is not None]
        parsed = _decode_roll(p.verbatim, doc.text) if p.kind is ClaimKind.IDENTIFIER else None

        # The model returned the date TEXT; our parser reads it. An unrecognised
        # format drops the INTERVAL and keeps the claim: a project with an unreadable
        # date is still a project — the repository exists, the deployment is still
        # reachable — and the date-dependent rules abstain with that flag as the
        # reason. Dropping the claim would lose its artefacts and shrink coverage
        # silently, which reads as a pass.
        interval = (
            parse_interval(p.date_text, slash_order=slash_order) if p.date_text else None
        )
        flags = ["date_unparsed"] if p.date_text and interval is None else []

        context: dict[str, Any] | None = None
        if p.categories:
            context = {"categories": p.categories}
        # Guardrail 7. A contest name the claim's own sentence does not contain is
        # a name the model supplied from somewhere else, and contest identity is
        # what P2 matches on. It rides in `context` rather than as a new Claim
        # field: the contract's nine claim kinds come from the upstream schema and
        # `context` is its documented place for pass-specific extras.
        if p.contest and _norm_text(p.contest) in _norm_text(doc.text[span.text_slice]):
            context = {**(context or {}), "contest": p.contest.strip()}
        discriminator = handle or (p.skill_refs[0] if p.skill_refs else "") or (p.metric or "")
        cid = claim_id(graph_id, span.char_start, p.kind, discriminator)
        if cid in seen:
            continue  # the model repeats itself; one span+kind+discriminator is one claim
        seen.add(cid)
        windows[cid] = (p.window_start, p.window_end or len(doc.text))

        claims.append(
            Claim(
                claim_id=cid,
                kind=p.kind,
                provenance=SpanProvenance(
                    char_start=span.char_start,
                    char_end=span.char_end,
                    verbatim=doc.text[span.text_slice],  # the DOCUMENT's text, not the model's
                    recovery=span.recovery,
                ),
                org=p.org,
                title=p.title,
                degree=p.degree,
                employment_type=p.employment_type or EmploymentType.UNSTATED,
                platform=p.platform,
                handle=handle,
                metric=p.metric,
                value=p.value,
                qualifier=p.qualifier,
                skill_refs=p.skill_refs,
                proficiency=p.proficiency,
                # The summary pass sets `years` directly; the skills pass sets
                # `stated_years` after grouping a line's technologies.
                stated_years=p.stated_years if p.stated_years is not None else p.years,
                context=context,
                interval=interval,
                parsed=parsed,
                artefacts=[_artefact(u) for u in urls],
                flags=flags,
            )
        )

    claims = scope_technologies(claims, windows, doc)
    claims, dropped = apply_filters(claims)
    log.info(
        "extraction.done",
        graph_id=graph_id,
        proposed=len(proposed),
        claims=len(claims),
        span_failures=span_failures,
        filtered={k: v for k, v in dropped.items() if v},
    )

    return ClaimGraph(
        graph_id=graph_id,
        source=SourceInfo(document_id=doc.document_id, normalised_text=doc.text),
        claims=claims,
        extraction_meta=ExtractionMeta(
            model_id=model_id,
            prompt_version=PROMPT_VERSION,
            input_hash=input_hash(doc.text),
            span_failures=span_failures,
            filtered={k: v for k, v in dropped.items() if v},
            extracted_at=datetime.datetime.now(datetime.UTC),
            degraded=span_failures + sum(dropped.values()) > len(claims),
        ),
    )


def platform_handles(graph: ClaimGraph) -> dict[Platform, str]:
    """The handles gather needs, from profile and achievement claims alike."""
    out: dict[Platform, str] = {}
    for c in graph.claims:
        if not (c.platform and c.handle):
            continue
        try:
            out.setdefault(Platform(c.platform.lower()), c.handle)
        except ValueError:
            continue  # github is not a contest platform; other platforms not connected
    return out


def extract(
    doc: Document, *, provider: LLMProvider | None = None, graph_id: str = "cg_001"
) -> tuple[ClaimGraph, dict[str, int]]:
    """Document to ClaimGraph: propose, ground, filter."""
    provider = provider or default_provider()
    proposed, counts = propose(doc, provider)
    graph = ground(proposed, doc, model_id=provider.model_id, graph_id=graph_id)
    return graph, counts
