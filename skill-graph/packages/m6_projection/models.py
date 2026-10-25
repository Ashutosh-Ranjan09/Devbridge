"""Dataclasses mirroring evidence-event.schema.json.

Deliberately stdlib-only. In the real repository these are generated from the
committed JSON Schema with pydantic v2, exactly as the M5 contracts are; the
field names and nesting here match that output so the swap is mechanical.

`to_dict()` is the schema-conformant projection. Note there is no `observed`
field: the schema sets additionalProperties:false and does not define one, so
the observation value is the scoring engine's business, derived from `payload`
via m6-parameters.yaml. See contracts/projection-rules.yaml `thresholds`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Literal

SCHEMA_VERSION = "1.0.0"

Kind = Literal["cv_claim", "claim_corroborated", "claim_contradicted", "repo_artifact",
               "platform_rating", "artifact_live", "credential_verified"]
Direction = Literal["positive", "negative"]
SuppressionReason = Literal["not_a_capability_signal", "non_scoring_rule", "no_skill_mapping",
                            "institution_disclaimed", "consent_scope_excluded"]

SUPPRESSION_REASONS: frozenset[str] = frozenset(
    ("not_a_capability_signal", "non_scoring_rule", "no_skill_mapping",
     "institution_disclaimed", "consent_scope_excluded"))


def _ts(value: date | datetime | str) -> str:
    """Schema wants date-time. A bare date means midnight UTC on that day."""
    if isinstance(value, str):
        return value if value.endswith("Z") or "+" in value[10:] else f"{value}T00:00:00Z"
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"{value.isoformat()}T00:00:00Z"


@dataclass(frozen=True, slots=True)
class SkillRef:
    skill_id: str
    relevance: float

    def to_dict(self) -> dict[str, Any]:
        return {"skill_id": self.skill_id, "relevance": round(self.relevance, 4)}


@dataclass(frozen=True, slots=True)
class ReliabilityFactor:
    """Every multiplier applied to reliability_base, named. A capped value must
    be auditable rather than magic."""
    factor: str
    value: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"factor": self.factor, "value": self.value, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class EventSource:
    module: str
    module_version: str
    origin: str
    verification_id: str | None = None
    claim_refs: tuple[str, ...] = ()
    evidence_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"module": self.module, "module_version": self.module_version,
                               "origin": self.origin}
        if self.verification_id:
            out["verification_id"] = self.verification_id
        if self.claim_refs:
            out["claim_refs"] = list(self.claim_refs)
        if self.evidence_ref is not None:
            out["evidence_ref"] = self.evidence_ref
        return out


@dataclass(frozen=True, slots=True)
class EvidenceEvent:
    event_id: str
    kind: Kind
    occurred_at: date | datetime | str
    skill_refs: tuple[SkillRef, ...]
    strength: float
    reliability: float
    direction: Direction
    source: EventSource
    observed_at: date | datetime | str | None = None
    reliability_base: float | None = None
    reliability_factors: tuple[ReliabilityFactor, ...] = ()
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "event_id": self.event_id,
            "kind": self.kind,
            "occurred_at": _ts(self.occurred_at),
            "skill_refs": [r.to_dict() for r in self.skill_refs],
            "strength": round(self.strength, 4),
            "reliability": round(self.reliability, 4),
            "direction": self.direction,
            "source": self.source.to_dict(),
        }
        if self.observed_at is not None:
            out["observed_at"] = _ts(self.observed_at)
        if self.reliability_base is not None:
            out["reliability_base"] = round(self.reliability_base, 4)
        if self.reliability_factors:
            out["reliability_factors"] = [f.to_dict() for f in self.reliability_factors]
        if self.payload:
            out["payload"] = self.payload
        return out


@dataclass(frozen=True, slots=True)
class Suppressed:
    what: str
    reason: SuppressionReason

    def to_dict(self) -> dict[str, Any]:
        return {"what": self.what, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class EvidenceEventBatch:
    batch_id: str
    verification_id: str
    subject_ref: str
    emitted_at: date | datetime | str
    events: tuple[EvidenceEvent, ...] = ()
    not_emitted: tuple[Suppressed, ...] = ()
    # Not part of the wire schema — surfaced to the caller so an unresolved skill
    # is visible rather than silently absent.
    quarantined: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "batch_id": self.batch_id,
            "verification_id": self.verification_id,
            "subject_ref": self.subject_ref,
            "emitted_at": _ts(self.emitted_at),
            "events": [e.to_dict() for e in self.events],
            "not_emitted": [s.to_dict() for s in self.not_emitted],
        }
