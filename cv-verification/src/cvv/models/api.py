"""The models the HTTP surface exchanges — §05 of the integration spec.

Everything here is a wrapper around what the pipeline already produces. Nothing new
is computed at this layer, deliberately: the API is a transport, and a transport that
derives a fact is a second place for that fact to be wrong.
"""

from __future__ import annotations

import datetime

from pydantic import Field, model_validator

from cvv.models.claims import ClaimGraph, DocumentInfo, Id, Model, Url
from cvv.models.enums import ReportStatus, SkillSource
from cvv.models.evidence import EvidenceBundle
from cvv.models.findings import FindingsReport, VerificationCoverage


class Narrative(Model):
    """Prose over a FindingsReport, and the provenance of the prose itself.

    `fallback_used` is not an error flag. A model that embellishes is rejected and
    the deterministic summary is rendered instead, which is the SAFE outcome — but a
    reader must be able to tell which one they are looking at, and `rejected_because`
    says why in the words the check used.
    """

    summary: str
    sections: dict[str, str] = Field(default_factory=dict)
    cited_finding_ids: list[str] = Field(default_factory=list)
    model_id: str
    prompt_version: str
    fallback_used: bool = False
    rejected_because: str | None = None


class ExternalSignals(Model):
    """Evidence gathered by another system, if one is doing the gathering.

    Every field is optional and an absent field makes its dependent rules ABSTAIN —
    never pass, never fail. The spec puts this on the request because a wider
    platform may already hold activity data; this system gathers its own when none
    arrives, which is what makes the document-only path real.
    """

    activity_windows: list[dict[str, object]] = Field(default_factory=list)
    verified_orgs: list[str] = Field(default_factory=list)
    first_seen_skills: dict[str, datetime.date] = Field(default_factory=dict)
    source: str | None = None


class VerificationOptions(Model):
    narrative: bool = True
    rules_profile: str = "default"
    offline: bool = False  # skip evidence gathering; document-intrinsic checks only


class Subject(Model):
    """Who a report is about, by reference only.

    `subject_ref` comes from the caller, never from the CV: minting an identifier out
    of a name or a roll number makes someone linkable across verifications they never
    connected. `consent_ref` is the contract's, and this system never sets it.
    """

    subject_ref: str
    # The schema types this as a string, not a nullable one, so an unknown tenant is
    # left out of the JSON rather than written as null.
    tenant_id: str | None = Field(default=None, exclude_if=lambda v: v is None)
    consent_ref: str | None = None


# A platform username: letters, digits, `_ . -`, at most 39 characters (GitHub's limit,
# the longest of the four). Anything else is refused before it reaches a URL.
HANDLE = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,38}$"


class Handles(Model):
    """Handles the candidate typed on upload. They fill in what the CV leaves out; a
    handle the CV states wins. Typed, not proven: ownership stays claimed_unverified,
    exactly as for a handle read from the CV. Every field is optional."""

    github: str | None = Field(default=None, pattern=HANDLE)
    codeforces: str | None = Field(default=None, pattern=HANDLE)
    leetcode: str | None = Field(default=None, pattern=HANDLE)
    codechef: str | None = Field(default=None, pattern=HANDLE)


class VerificationRequest(Model):
    """The JSON body. A multipart upload carries the file instead of `document_url`."""

    document_url: Url | None = None
    subject: Subject | None = None
    external_signals: ExternalSignals | None = None
    handles: Handles | None = None
    options: VerificationOptions = Field(default_factory=VerificationOptions)


class VerificationAccepted(Model):
    verification_id: Id
    status: str
    estimated_seconds: int


class ReportProvenance(Model):
    """Everything needed to explain a finding months later, when the sources have moved."""

    cvv_version: str
    contract_version: str
    model_id: str | None = None
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    rule_versions: dict[str, str]
    sources_queried: list[dict[str, object]] = Field(default_factory=list)
    # Not in the contract: handles the candidate typed on upload that were used, because
    # the CV names none for that platform. Without it a reader cannot tell an account
    # the candidate typed from one the CV names.
    typed_handles: dict[str, str] = Field(default_factory=dict)


class SkillDecision(Model):
    """Which shared skill one name means, and who said so. `id` None is "none of
    them" — a tool, a library, or something not on the list."""

    id: str | None
    by: SkillSource


class VerificationReport(Model):
    """The contract's VerificationReport — the one artefact M6 reads.

    Every stage travels together on purpose: a finding cites claim ids and evidence,
    and a report whose claims or evidence live somewhere else is a report nobody can
    check — and one M6 cannot project, because the capability signals are in the
    evidence bundle, not in the findings.

    `failure` is this system's one addition at this level: the contract has no field
    for why a verification failed, and a failure that cannot say why leaves the
    client nothing to tell the candidate.
    """

    schema_version: str = "1.0.0"
    verification_id: Id
    status: ReportStatus
    supersedes: Id | None = None
    subject: Subject
    # None only on a failed report whose file could not be read at all.
    document: DocumentInfo | None
    claim_graph: ClaimGraph
    evidence_bundle: EvidenceBundle
    findings: FindingsReport
    narrative: Narrative | None = None
    coverage: VerificationCoverage
    provenance: ReportProvenance
    valid_as_of: datetime.datetime
    signature: dict[str, str] | None = None
    failure: str | None = Field(default=None, exclude_if=lambda v: v is None)
    # Name -> the shared skill it means. Not in the contract: M6 reads it first, so
    # what a name refers to travels with the report and a re-projection months later
    # gives the same graph whatever the cache or the alias file say by then.
    skill_resolution: dict[str, SkillDecision] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _failure_is_explained(self) -> VerificationReport:
        # A report that failed without saying why, or one that completed while
        # carrying a failure, is a report a client cannot act on.
        if (self.status is ReportStatus.FAILED) != (self.failure is not None):
            raise ValueError("status=failed requires a failure reason, and only then")
        if self.document is None and self.status is not ReportStatus.FAILED:
            raise ValueError("only a failed report may lack its document")
        return self


class ProvenanceView(Model):
    """Where a claim came from, for a reviewer who wants to see it on the page.

    `bbox` is null until ingest keeps per-character geometry. Null is honest; a
    guessed rectangle would send a reviewer to the wrong line and cost more than
    showing none.
    """

    claim_id: Id
    verbatim: str
    char_start: int
    char_end: int
    page: int | None = None
    bbox: list[float] | None = None
    snippet: str


class Webhook(Model):
    webhook_id: Id
    url: Url
    created_at: datetime.datetime


class Usage(Model):
    """Metered counts. Deliberately not per-candidate: this system must not become a
    record of who has been investigated."""

    verifications_total: int
    verifications_completed: int
    verifications_failed: int
    since: datetime.datetime


class ApiError(Model):
    error: str
    detail: str
    ocr_confidence: float | None = None
