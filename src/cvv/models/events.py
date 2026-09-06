"""The M6 projection — `schemas/evidence-event.schema.json`, as pydantic.

The schema's own description is the design brief, and it inverts what this system
mostly produces: *"M6 does NOT consume discrepancies — it has no interest in fraud.
It consumes corroborated capability signals."*

So this is not the FindingsReport in another shape. A contradiction is a fact about a
CV, not a capability signal, and most of what M5 finds is deliberately withheld —
which is what `not_emitted` is for. Filtering that is invisible is filtering nobody
can audit.
"""

from __future__ import annotations

import datetime
from enum import StrEnum

from pydantic import Field

from cvv.models.claims import Confidence, Id, Model


class EventKind(StrEnum):
    """`cv_claim` is self-reported and weak; `platform_rating` comes from an
    authoritative API and is the strongest. The gap between them is the whole point
    of the verification."""

    CV_CLAIM = "cv_claim"
    CLAIM_CORROBORATED = "claim_corroborated"
    CLAIM_CONTRADICTED = "claim_contradicted"
    REPO_ARTIFACT = "repo_artifact"
    PLATFORM_RATING = "platform_rating"
    ARTIFACT_LIVE = "artifact_live"
    CREDENTIAL_VERIFIED = "credential_verified"


class Direction(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


class SuppressionReason(StrEnum):
    """Why something M5 knows was not sent. Every value is a real category here, not
    a placeholder: `institution_disclaimed` exists because a CDC footer saying "could
    not verify" scopes every claim under it, and passing those on as capability
    signals would launder a caveat the issuer wrote."""

    NOT_A_CAPABILITY_SIGNAL = "not_a_capability_signal"
    NON_SCORING_RULE = "non_scoring_rule"
    NO_SKILL_MAPPING = "no_skill_mapping"
    INSTITUTION_DISCLAIMED = "institution_disclaimed"
    CONSENT_SCOPE_EXCLUDED = "consent_scope_excluded"


class SkillRef(Model):
    """`skill_id` is meant to be an ESCO-seeded canonical id and this system has no
    resolver — `/v1/resolve` returns 501 because there is no registry installed. So
    ids are emitted in an explicit `surface:` namespace and `relevance` is reduced,
    rather than a surface form being passed off as canonical. M6 can then map or
    reject them knowingly instead of storing a made-up identifier."""

    skill_id: str
    relevance: Confidence


class ReliabilityFactor(Model):
    """Every multiplier applied to the base reliability, named. A capped value is
    auditable instead of magic."""

    factor: str
    value: float = Field(ge=0.0, le=1.0)
    reason: str


class EventSource(Model):
    module: str = "m5-cv-verification"
    module_version: str
    origin: str
    verification_id: str | None = None
    claim_refs: list[Id] = Field(default_factory=list)
    evidence_ref: str | None = None


class EvidenceEvent(Model):
    event_id: str
    kind: EventKind
    # When the ACTIVITY happened, not when it was observed — M6's decay kernel reads
    # this. Server-side dates only, for the same reason guardrail 6 exists.
    occurred_at: datetime.datetime
    skill_refs: list[SkillRef]
    strength: Confidence
    reliability: Confidence
    reliability_factors: list[ReliabilityFactor] = Field(default_factory=list)
    direction: Direction
    source: EventSource
    payload: dict[str, object] = Field(default_factory=dict)


class Suppressed(Model):
    what: str
    reason: SuppressionReason


class EvidenceEventBatch(Model):
    schema_version: str = "1.0.0"
    batch_id: str
    verification_id: str
    subject_ref: str
    emitted_at: datetime.datetime
    # EMPTY BY DEFAULT, and that is the safe default rather than an oversight: the
    # schema says M6 must refuse events whose scope does not cover skill-graph
    # inclusion. This system holds no consent record, so it asserts none. A caller
    # who has one passes it.
    consent_scope: list[str] = Field(default_factory=list)
    events: list[EvidenceEvent] = Field(default_factory=list)
    not_emitted: list[Suppressed] = Field(default_factory=list)
