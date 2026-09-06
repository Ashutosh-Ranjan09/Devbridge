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

3. **Some things need no model at all.** Both models missed the roll number, every
   profile handle, and the institution's own disclaimer. Those have exact syntax, so a
   regex finds them every time.
"""

from __future__ import annotations

import datetime
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from cvv.dates import parse_interval
from cvv.filters import apply as apply_filters
from cvv.ids import claim_id
from cvv.ingest import Document, line_at, section_text
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
from cvv.providers import LLMProvider, OllamaProvider
from cvv.reference import roll_patterns
from cvv.spans import recover_span, recover_token

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

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "claims": {
                    "type": "array",
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
        sections=("SKILL", "EXPERTISE"),
        kind=ClaimKind.SKILL,
        instruction=(
            "Categorise every technology named in this CV section.\n"
            "  name      the technology, exactly as written\n"
            "  category  language | framework | library | tool | concept | not_a_skill\n"
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
        },
        required=["name", "category"],
    ),
]


# --------------------------------------------------------------------------- #
# Deterministic pre-pass — no model
# --------------------------------------------------------------------------- #

GITHUB_REPO = re.compile(r"github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)/([\w.-]+)")
LABELLED_HANDLE = re.compile(
    r"(codeforces|codechef|leetcode|atcoder|hackerrank|github)[^.\n]{0,60}?"
    r"handle\s*[:\-]\s*([A-Za-z0-9_.-]{2,32})",
    re.I,
)
# Bounded by sentence and bullet marks. After normalisation the document is one long
# line with no newlines, so an unbounded [^.\n]* run greedily swallowed the preceding
# 200 characters and captured the wrong sentence entirely.
DISCLAIMER = re.compile(
    r"[^.!•\n]*\b(?:could not verify|self[- ]declared|not verified by)\b[^.!•\n]*", re.I
)


def regex_claims(text: str) -> list[ProposedClaim]:
    """The three things both models missed entirely, and one they only found by luck.

    A roll number is an unremarkable token in a wall of prose — a model has no
    semantic reason to emit it, and `23CS10004` decodes into admission year and
    department for a decisive check. Handles were found only when they happened to sit
    inside an achievement sentence. The institution's own disclaimer scopes every
    other claim on the page and neither model produced it.
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

    for m in LABELLED_HANDLE.finditer(text):
        out.append(
            ProposedClaim(
                kind=ClaimKind.PROFILE,
                verbatim=m.group(0),
                platform=m.group(1).lower(),
                handle=m.group(2),
            )
        )

    for m in DISCLAIMER.finditer(text):
        out.append(ProposedClaim(kind=ClaimKind.DECLARATION_MARKER, verbatim=m.group(0).strip()))

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
    lo, hi = window

    for p in skills:
        if not p.name or p.category == "not_a_skill":
            continue
        found = doc.text.lower().find(p.name.lower(), lo, hi)
        if found == -1:
            continue  # the section does not contain it
        lines.setdefault(line_at(doc, found), {})[p.name.lower()] = p.category or "unknown"

    return [
        ProposedClaim(
            kind=ClaimKind.SKILL,
            verbatim=doc.text[start:end],
            skill_refs=sorted(categories),
            categories=categories,
            stated_years=_years_on(doc.text[start:end]),
            window_start=start,
            window_end=end,
        )
        for (start, end), categories in lines.items()
        if categories
    ]


_YEARS = re.compile(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\b", re.I)


def _years_on(line: str) -> float | None:
    """Stated experience, read off the line rather than asked for.

    Two figures on one line — "Python (5 years) | Go (2 years)" — cannot be assigned,
    because the claim is per LINE and the figures are per technology. Ambiguity drops
    the field; the claim survives without it and G9 abstains, which is the honest
    outcome rather than attaching one number to the wrong language.
    """
    found = {m.group(1) for m in _YEARS.finditer(line)}
    return float(next(iter(found))) if len(found) == 1 else None


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
    for p in PASSES:
        text, offset = section_text(doc, p.sections) if p.sections else (doc.text, 0)
        found = _call(p, text, offset, provider)
        counts[p.name] = len(found)
        if p.kind is ClaimKind.SKILL:
            found = group_skills(found, doc, (offset, offset + len(text)))
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


def _decode_roll(token: str) -> dict[str, Any] | None:
    """Named groups from whichever institution's scheme matches, or None.

    The groups a scheme declares are the groups it gets — `year`, `dept` and `serial`
    here, and a scheme that encodes something else contributes what it encodes. D9
    reads what is present and abstains on what is not, so an institution with no
    department in its roll number costs a sub-check rather than the whole rule.
    """
    for _, pattern in roll_patterns():
        m = pattern.fullmatch(token)
        if m is None:
            continue
        groups = m.groupdict()
        parsed: dict[str, Any] = {}
        if year := groups.get("year"):
            parsed["admission_year"] = 2000 + int(year) if len(year) == 2 else int(year)
        if dept := groups.get("dept"):
            parsed["dept_code"] = dept
        if serial := groups.get("serial"):
            parsed["serial"] = int(serial)
        return parsed or None
    return None


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
        parsed = _decode_roll(p.verbatim) if p.kind is ClaimKind.IDENTIFIER else None

        # The model returned the date TEXT; our parser reads it. An unrecognised
        # format drops the INTERVAL and keeps the claim: a project with an unreadable
        # date is still a project — the repository exists, the deployment is still
        # reachable — and the date-dependent rules abstain with that flag as the
        # reason. Dropping the claim would lose its artefacts and shrink coverage
        # silently, which reads as a pass.
        interval = parse_interval(p.date_text) if p.date_text else None
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
                stated_years=p.stated_years,
                context=context,
                interval=interval,
                parsed=parsed,
                artefacts=[_artefact(u) for u in urls],
                flags=flags,
            )
        )

    claims = scope_technologies(claims, windows, doc)
    claims, dropped = apply_filters(claims)
    span_failures += sum(dropped.values())

    return ClaimGraph(
        graph_id=graph_id,
        source=SourceInfo(document_id=doc.document_id, normalised_text=doc.text),
        claims=claims,
        extraction_meta=ExtractionMeta(
            model_id=model_id,
            prompt_version=PROMPT_VERSION,
            input_hash="sha256:" + hashlib.sha256(doc.text.encode()).hexdigest()[:32],
            span_failures=span_failures,
            extracted_at=datetime.datetime.now(datetime.UTC),
            degraded=span_failures > len(claims),
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
    provider = provider or OllamaProvider()
    proposed, counts = propose(doc, provider)
    graph = ground(proposed, doc, model_id=provider.model_id, graph_id=graph_id)
    return graph, counts
