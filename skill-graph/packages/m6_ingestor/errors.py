"""Every way an ingest can fail, as a distinct type.

The transport layer maps these to status codes, so the distinctions are the API
contract: a schema failure is the producer's bug (400), a consent refusal is a
policy decision that must never be retried into success (403), and a content
conflict means two different events claim the same identity (409).
"""
from __future__ import annotations


class IngestError(Exception):
    """Base for everything this package raises."""
    status = 400


class SchemaInvalid(IngestError):
    """The batch does not validate against evidence-event.schema.json.

    M5 and M6 are separate services, so the schema is re-checked here rather than
    assumed. A producer that has drifted must be told, not accommodated.
    """
    status = 400

    def __init__(self, message: str, path: str = "") -> None:
        super().__init__(f"{message} at {path}" if path else message)
        self.path = path


class ConsentRefused(IngestError):
    """consent_scope does not cover skill_graph_inclusion.

    Not an error in the producer — a correct refusal. Recorded, never retried.
    """
    status = 403


class ConflictingEvent(IngestError):
    """An event_id already in the log arrived with different content.

    event_id is sha256(verification_id, kind, discriminator), so identity is
    derived from the claim's subject, not its values. Two different values under
    one id means the projection changed its mind about the same evidence. The log
    is append-only, so history is not rewritten to accommodate that; a human
    decides whether to re-project under a new verification_id.
    """
    status = 409

    def __init__(self, event_id: str, stored: str, incoming: str) -> None:
        super().__init__(
            f"{event_id} is already stored with different content "
            f"(stored {stored[:12]}, incoming {incoming[:12]})")
        self.event_id = event_id


class ImmutableLog(IngestError):
    """Something tried to update or delete a stored event.

    Enforced by database trigger rather than by convention, because O4 recomputes
    every score by folding this log: a mutated row silently changes history.
    """
    status = 409
