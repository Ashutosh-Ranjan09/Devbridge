"""What the candidate claims — the ClaimGraph and everything under it.

Produced by ingest + extract, consumed by rules. Nothing here knows about HTTP.
"""

from __future__ import annotations

import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from cvv.models.enums import (
    ArtefactType,
    AssertedBy,
    ClaimKind,
    DeclarationEffect,
    EmploymentType,
    IngestMethod,
    Precision,
    Proficiency,
    Recovery,
    ResolutionMethod,
    ResolutionStatus,
)

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
Id = Annotated[str, Field(min_length=3, max_length=64)]

# The schema says format: uri. Deliberately NOT pydantic's HttpUrl — that type
# normalises on parse ("https://atma-ar.vercel.app" gains a trailing slash), which
# rewrites what the candidate actually wrote.
Url = Annotated[str, Field(json_schema_extra={"format": "uri"})]


class Model(BaseModel):
    """additionalProperties: false, on every model in the contract."""

    model_config = ConfigDict(extra="forbid")


class Frozen(Model):
    """A committed artefact. Immutable once produced."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class FuzzyDate(Model):
    """A CV date denotes a SET of dates, not a point.

    '2021' expands to 2021-01-01..2021-12-31. The expansion lives in intervals.py;
    this model only holds what the document committed to.
    """

    year: int = Field(ge=1950, le=2100)
    month: int | None = Field(default=None, ge=1, le=12)
    day: int | None = Field(default=None, ge=1, le=31)
    precision: Precision

    @model_validator(mode="after")
    def _precision_matches_components(self) -> FuzzyDate:
        if self.precision is Precision.EXACT and (self.month is None or self.day is None):
            raise ValueError("precision=exact requires month and day")
        if self.precision is Precision.MONTH and self.month is None:
            raise ValueError("precision=month requires month")
        if self.precision is Precision.YEAR and (self.month is not None or self.day is not None):
            raise ValueError("precision=year must not carry month or day")
        return self

    @model_validator(mode="after")
    def _day_is_a_real_calendar_day(self) -> FuzzyDate:
        """31 April would otherwise reach intervals.bounds() and raise there, during
        rule evaluation, far from the input that caused it."""
        if self.precision is Precision.EXACT:
            assert self.month is not None and self.day is not None
            try:
                datetime.date(self.year, self.month, self.day)
            except ValueError as exc:
                raise ValueError(f"not a real date: {self.year}-{self.month}-{self.day}") from exc
        return self


class Interval(Model):
    """end=None with ongoing=False is a POINT — a graduation year is a year, not
    "2027 onwards"."""

    start: FuzzyDate
    end: FuzzyDate | None = None
    ongoing: bool = False


class SpanProvenance(Model):
    """Where a claim came from. Offsets index ClaimGraph.source.normalised_text.

    The model never emits these — it returns `verbatim` and Python recovers the offsets
    by search. LLMs cannot count characters.
    """

    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    page: int | None = Field(default=None, ge=1)
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)
    verbatim: str
    recovery: Recovery

    @model_validator(mode="after")
    def _span_ordered(self) -> SpanProvenance:
        if self.char_end <= self.char_start:
            raise ValueError("char_end must exceed char_start")
        return self


class Artefact(Model):
    """A repo or deployment URL hanging off a claim. Without these the gather phase
    has nothing to fetch."""

    type: ArtefactType
    platform: str | None = None  # github · gitlab · vercel · npm
    url: Url
    owner: str | None = None  # for repos: the account segment, parsed from the path


class Resolution(Model):
    """A surface form tied to a canonical registry id — or not tied to one.

    `unresolved` everywhere in this system today: `/v1/resolve` returns 501 because
    no registry is installed. The model exists so an upstream payload that HAS
    resolutions parses, and so the field a consumer expects is present rather than
    silently absent.
    """

    status: ResolutionStatus = ResolutionStatus.UNRESOLVED
    canonical_id: str | None = None
    registry: str | None = None  # esco · aicte · ugc · companies · iitkgp_faculty
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    method: ResolutionMethod = ResolutionMethod.NONE


class Claim(Model):
    """One assertion the candidate makes about themselves.

    Fields are grouped by the kind that uses them. Nothing is cross-validated against
    `kind`: an over-strict boundary would reject a real CV over one missing field and
    lose the other twenty claims with it. A rule that lacks its input abstains.
    """

    claim_id: Id
    kind: ClaimKind
    provenance: SpanProvenance

    # temporal — employment · education · certification · project
    interval: Interval | None = None

    # employment · education · certification
    org: str | None = None
    title: str | None = None
    degree: str | None = None
    issuer: str | None = None
    credential_id: str | None = None
    employment_type: EmploymentType = EmploymentType.UNSTATED

    # Canonical-id resolution. Always None here — nothing resolves — but a claim
    # arriving from a system that DOES resolve must round-trip through this model.
    resolution: Resolution | None = None

    # skill
    skill_refs: list[str] = Field(default_factory=list)
    proficiency: Proficiency | None = None
    stated_years: int | float | None = Field(default=None, ge=0)

    # profile · achievement
    platform: str | None = None  # github · codeforces · leetcode · codechef · atcoder
    handle: str | None = None
    metric: str | None = None  # max_rating · contest_rank · problems_solved
    value: int | float | str | None = None
    qualifier: str | None = None  # "Specialist", "3-Star"
    context: dict[str, Any] | None = None

    # identifier — structure decoded from the id: {admission_year, dept_code, serial}
    parsed: dict[str, Any] | None = None

    # project
    supervisor: str | None = None
    artefacts: list[Artefact] = Field(default_factory=list)

    # declaration_marker
    scope: list[str] = Field(default_factory=list)
    asserted_by: AssertedBy | None = None
    effect: DeclarationEffect | None = None

    flags: list[str] = Field(default_factory=list)  # end_in_future · date_unparsed


class SourceInfo(Model):
    document_id: str
    normalised_text: str  # the exact string every char offset indexes into


class DocumentInfo(Model):
    """Provenance of the file itself — what `SourceInfo` deliberately does not carry.

    An institutional generator is itself a signal: a CV produced by a placement cell's
    template went through that cell, which is trust-INCREASING and the opposite of a
    finding. A modification long after creation is the signal that warrants a question.
    """

    document_id: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    pages: int = Field(ge=1)
    ingest_method: IngestMethod
    ocr_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    producer: str | None = None
    created_at: str | None = None
    modified_at: str | None = None


class HiddenText(Model):
    """Text the file carries that a reader of the rendered page cannot see.

    Found at ingest and kept OUT of `normalised_text`, so no model is shown it and no
    claim can ground in it. Recorded so D13 can tell a reviewer it was there.
    """

    page: int = Field(ge=1)
    # invisible: no ink where it sits on the rendered page — white on white, covered
    # by a shape, an invisible text mode. tiny: set below a size anyone reads.
    reason: Literal["invisible", "tiny"]
    text: str
    size: float | None = None  # points


class Reading(Model):
    """What reading the file found beyond its text, for the rules that need it.

    Not part of the contract and never serialised into a report: the contract's
    `document` object is closed, and nothing here is evidence about a claim. A rule
    that needs it abstains when it is absent — the /v1/evaluate path holds a claim
    graph and no file.
    """

    # The same value as ExtractionMeta.input_hash, so a rule can tell that this
    # reading and that claim graph are of one text, not a re-read that differs.
    input_hash: str
    hidden: list[HiddenText] = Field(default_factory=list)
    # Each non-empty line of the text, as normalised offsets [start, end).
    # Normalisation collapses line breaks, so the lines exist only here.
    lines: list[tuple[int, int]] = Field(default_factory=list)


class ExtractionMeta(Model):
    model_id: str
    prompt_version: str
    input_hash: str
    # UNGROUNDABLE — the quoted text is not in the document. The model invented or
    # garbled it, and dropping it is the guardrail working.
    span_failures: int = Field(default=0, ge=0)
    # FILTERED — the text was real and the claim was not usable: a field the span did
    # not support, an excluded exam, a duplicate. Kept apart from `span_failures`
    # because they mean opposite things about the model, and a report that says
    # "the quoted text could not be found" about a claim whose text was found
    # perfectly well is telling a reader something false.
    filtered: dict[str, int] = Field(default_factory=dict)
    retries: int = Field(default=0, ge=0)
    extracted_at: datetime.datetime
    degraded: bool = False


class ClaimGraph(Frozen):
    """`claims` may be empty. Extraction returning nothing is a valid graph, not a
    failure: every rule then abstains and the report says so."""

    graph_id: Id
    source: SourceInfo
    claims: list[Claim]
    extraction_meta: ExtractionMeta

    @model_validator(mode="after")
    def _spans_index_their_verbatim(self, info: ValidationInfo) -> ClaimGraph:
        """The single check that catches most integration breakage at the boundary.

        Waived only via validation context, for documentation fixtures whose
        normalised_text is truncated. No production path passes that context.
        """
        if (info.context or {}).get("source_text_truncated"):
            return self

        text = self.source.normalised_text
        for c in self.claims:
            p = c.provenance
            if p.char_end > len(text):
                raise ValueError(
                    f"{c.claim_id}: span {p.char_start}:{p.char_end} exceeds source text "
                    f"of length {len(text)}"
                )
            if p.recovery is Recovery.EXACT and text[p.char_start : p.char_end] != p.verbatim:
                raise ValueError(f"{c.claim_id}: span does not index its verbatim")
        return self
