"""The models the HTTP surface exchanges — §05 of the integration spec.

Everything here is a wrapper around what the pipeline already produces. Nothing new
is computed at this layer, deliberately: the API is a transport, and a transport that
derives a fact is a second place for that fact to be wrong.
"""

from __future__ import annotations

import datetime

from pydantic import Field

from cvv.models.claims import ClaimGraph, Id, Model, Url
from cvv.models.enums import ReportStatus
from cvv.models.findings import FindingsReport


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


class VerificationRequest(Model):
    """The JSON body. A multipart upload carries the file instead of `document_url`."""

    document_url: Url | None = None
    external_signals: ExternalSignals | None = None
    options: VerificationOptions = Field(default_factory=VerificationOptions)


class VerificationAccepted(Model):
    verification_id: Id
    status: str
    estimated_seconds: int


class VerificationReport(Model):
    """What a client gets back. The whole audit trail, in one object.

    `claim_graph` travels with the findings on purpose: a finding cites claim ids,
    and a report whose claims live somewhere else is a report nobody can check.
    """

    schema_version: str = "1.0.0"
    verification_id: Id
    status: ReportStatus
    claim_graph: ClaimGraph
    findings: FindingsReport
    narrative: Narrative | None = None
    created_at: datetime.datetime
    completed_at: datetime.datetime | None = None
    failure: str | None = None


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
