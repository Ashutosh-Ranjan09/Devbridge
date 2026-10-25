"""The ingest decision, with no transport in it.

Five responsibilities, from the plan: validation, idempotency, consent refusal,
immutable persistence, quarantine for unknown skills. No modelling — this module
must never compute a score, apply a decay, or decide what evidence is worth. It
decides only whether a batch may enter the log, and records what it did.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from typing import Any

from m6_ontology import SkillResolver, default_ontology

from .errors import ConflictingEvent, ConsentRefused, SchemaInvalid
from .store import EventLog, content_hash

SCHEMA_PATH = (pathlib.Path(__file__).resolve().parents[2]
               / "docs" / "docs" / "schemas" / "evidence-event.schema.json")
REQUIRED_SCOPE = "skill_graph_inclusion"


@dataclass(frozen=True, slots=True)
class Receipt:
    """What the ingest did, in enough detail to be audited or replayed."""
    batch_id: str
    accepted: tuple[str, ...] = ()
    duplicates: tuple[str, ...] = ()
    quarantined: dict[str, tuple[str, ...]] = field(default_factory=dict)
    replayed: bool = False
    ontology_version: str = ""

    @property
    def stored(self) -> int:
        return len(self.accepted)

    def to_dict(self) -> dict[str, Any]:
        return {"batch_id": self.batch_id, "accepted": list(self.accepted),
                "duplicates": list(self.duplicates),
                "quarantined": {k: list(v) for k, v in self.quarantined.items()},
                "replayed": self.replayed, "ontology_version": self.ontology_version}


def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text())


class Ingestor:
    """Accepts EvidenceEventBatch documents into an append-only log."""

    def __init__(self, log: EventLog, *, ontology: SkillResolver | None = None,
                 schema: dict[str, Any] | None = None) -> None:
        self.log = log
        # `is None`, not `or`: an ontology that is empty or defines __len__ is
        # falsy, and `or` would silently swap the caller's resolver for the seed
        # — turning an explicit "accept everything" into an unasked-for gate.
        self.ontology = default_ontology() if ontology is None else ontology
        self._schema = schema if schema is not None else _schema()

    # ── validation ──────────────────────────────────────────────────────────
    def validate(self, batch: Any) -> None:
        """Re-check the contract at the boundary.

        M5 and M6 are separate services and this is the trust edge between them.
        That the producer validated on its way out is not evidence that what
        arrived is valid — and a malformed event in an append-only log cannot be
        taken back out.
        """
        import jsonschema
        if not isinstance(batch, dict):
            raise SchemaInvalid(f"batch must be a JSON object, got {type(batch).__name__}")
        try:
            jsonschema.validate(instance=batch, schema=self._schema)
        except jsonschema.ValidationError as exc:
            path = "/".join(str(p) for p in exc.absolute_path)
            raise SchemaInvalid(exc.message, path) from exc

        # Uniqueness is a property of the batch, not of any one event, so the
        # schema cannot express it. Duplicate ids inside one batch would make the
        # accepted/duplicate counts in the receipt a lie.
        ids = [e["event_id"] for e in batch.get("events") or []]
        if len(ids) != len(set(ids)):
            duplicated = sorted({i for i in ids if ids.count(i) > 1})
            raise SchemaInvalid(f"event_id repeated within the batch: {', '.join(duplicated)}")

    # ── consent ─────────────────────────────────────────────────────────────
    def check_consent(self, batch: dict[str, Any]) -> None:
        """Refuse anything not cleared for skill-graph inclusion.

        Checked here as well as in the projection on purpose. Consent is the one
        rule where trusting the upstream service to have applied it is not good
        enough: the cost of being wrong is someone in a searchable talent pool
        who never agreed to be, and the log is append-only.
        """
        scope = batch.get("consent_scope") or []
        if REQUIRED_SCOPE not in scope:
            raise ConsentRefused(
                f"consent_scope {list(scope)} does not cover {REQUIRED_SCOPE!r}; "
                f"batch {batch.get('batch_id')} refused")

    # ── the main entry point ────────────────────────────────────────────────
    def ingest(self, batch: Any) -> Receipt:
        """Validate, refuse or accept, and report exactly what happened."""
        self.validate(batch)
        self.check_consent(batch)

        # Everything from here is one decision: whether this batch is already
        # known, and if not, what to write. Held exclusively so two concurrent
        # deliveries of the same batch cannot both conclude it is new.
        with self.log.exclusive():
            return self._decide(batch)

    def _decide(self, batch: dict[str, Any]) -> Receipt:
        batch_id = batch["batch_id"]
        incoming = content_hash(batch)
        stored_hash = self.log.batch_hash(batch_id)
        if stored_hash is not None:
            # Replay. The projection is deterministic, so an identical batch under
            # a known id is a no-op — that is what makes at-least-once delivery
            # safe. A DIFFERENT batch under a known id is not a delivery artefact.
            if stored_hash != incoming:
                raise ConflictingEvent(batch_id, stored_hash, incoming)
            return Receipt(batch_id=batch_id, replayed=True,
                           duplicates=tuple(e["event_id"] for e in batch["events"]),
                           ontology_version=self.ontology.ontology_version)

        accepted: list[str] = []
        duplicates: list[str] = []
        quarantined: dict[str, tuple[str, ...]] = {}
        pending: list[tuple[dict[str, Any], dict[str, bool]]] = []

        for event in batch["events"]:
            event_id = event["event_id"]
            seen = self.log.event_hash(event_id)
            if seen is not None:
                # Same event arriving inside a new batch — a re-verification that
                # reached the same conclusion. Conflict rules still apply.
                if seen != content_hash(event):
                    raise ConflictingEvent(event_id, seen, content_hash(event))
                duplicates.append(event_id)
                continue

            resolution = {ref["skill_id"]: self.ontology.knows(ref["skill_id"])
                          for ref in event["skill_refs"]}
            unknown = tuple(sorted(s for s, ok in resolution.items() if not ok))
            if unknown:
                # Stored, flagged, and held out of scoring. Dropping it would lose
                # evidence the ontology simply has not caught up with yet; scoring
                # it would invent a node nobody defined.
                quarantined[event_id] = unknown
            pending.append((event, resolution))
            accepted.append(event_id)

        self.log.append(batch, pending)
        return Receipt(batch_id=batch_id, accepted=tuple(accepted), duplicates=tuple(duplicates),
                       quarantined=quarantined,
                       ontology_version=self.ontology.ontology_version)
