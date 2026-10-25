"""The append-only evidence log.

SQLite because it is in the standard library and this project has no package
manager; the SQL is kept to the subset Postgres also accepts, so moving to the
agreed Postgres is a driver swap and a type-name pass, not a rewrite.

Immutability is enforced by TRIGGER, not by the absence of an UPDATE method.
O4 recomputes every score by folding this log, so a row that quietly changes
rewrites history — and a rule that lives only in application code is one careless
migration away from not existing.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator

from .errors import ImmutableLog, IngestError

SCHEMA = """
CREATE TABLE IF NOT EXISTS batch (
    batch_id        TEXT PRIMARY KEY,
    verification_id TEXT NOT NULL,
    subject_ref     TEXT NOT NULL,
    emitted_at      TEXT NOT NULL,
    consent_scope   TEXT NOT NULL,
    not_emitted     TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    event_count     INTEGER NOT NULL,
    ingested_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_event (
    event_id        TEXT PRIMARY KEY,
    batch_id        TEXT NOT NULL REFERENCES batch(batch_id),
    verification_id TEXT NOT NULL,
    subject_ref     TEXT NOT NULL,
    kind            TEXT NOT NULL,
    occurred_at     TEXT NOT NULL,
    observed_at     TEXT,
    strength        REAL NOT NULL,
    reliability     REAL NOT NULL,
    direction       TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    document        TEXT NOT NULL,
    ingested_at     TEXT NOT NULL
);

-- Denormalised so 6.3 can fold one skill without parsing every document.
CREATE TABLE IF NOT EXISTS event_skill (
    event_id   TEXT NOT NULL REFERENCES evidence_event(event_id),
    skill_id   TEXT NOT NULL,
    relevance  REAL NOT NULL,
    resolved   INTEGER NOT NULL,
    PRIMARY KEY (event_id, skill_id)
);

CREATE INDEX IF NOT EXISTS event_fold_order
    ON evidence_event (subject_ref, occurred_at, event_id);
CREATE INDEX IF NOT EXISTS skill_lookup
    ON event_skill (skill_id, resolved);

-- Append-only, enforced by the database.
CREATE TRIGGER IF NOT EXISTS evidence_event_no_update
    BEFORE UPDATE ON evidence_event
    BEGIN SELECT RAISE(ABORT, 'evidence_event is append-only'); END;
CREATE TRIGGER IF NOT EXISTS evidence_event_no_delete
    BEFORE DELETE ON evidence_event
    BEGIN SELECT RAISE(ABORT, 'evidence_event is append-only'); END;
CREATE TRIGGER IF NOT EXISTS event_skill_no_update
    BEFORE UPDATE ON event_skill
    BEGIN SELECT RAISE(ABORT, 'event_skill is append-only'); END;
CREATE TRIGGER IF NOT EXISTS event_skill_no_delete
    BEFORE DELETE ON event_skill
    BEGIN SELECT RAISE(ABORT, 'event_skill is append-only'); END;
"""


def content_hash(document: Any) -> str:
    """Identity of a document's VALUE, independent of key order or whitespace.

    Two projections of the same report must hash identically; a projection that
    changed its mind about strength must not.
    """
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True, slots=True)
class StoredEvent:
    event_id: str
    subject_ref: str
    kind: str
    occurred_at: str
    document: dict[str, Any]
    quarantined_skills: tuple[str, ...] = ()


class EventLog:
    """Append-only storage. The only writes are inserts."""

    def __init__(self, path: str = ":memory:") -> None:
        # check_same_thread=False because the server is threaded: each request is
        # handled on its own thread and would otherwise be refused the connection.
        # Safe only in combination with the lock below, which serialises writes —
        # sqlite3 module-level thread safety does not extend to transactions, and
        # two interleaved appends would break batch atomicity.
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "EventLog":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextlib.contextmanager
    def exclusive(self) -> Iterator[None]:
        """Hold the log against other writers for a whole decision.

        Idempotency is a check-then-act: "is this batch already here, and if not,
        write it". Locking only the write leaves two threads free to both observe
        an absent batch and both proceed, so at-least-once delivery turns a replay
        into a primary-key collision. The lock is re-entrant, so append() taking
        it again inside this block is fine.
        """
        with self._lock:
            yield

    # ── reads ───────────────────────────────────────────────────────────────
    # Every one goes through _rows/_one, which hold the lock. A single sqlite3
    # Connection shared between threads raises InterfaceError under concurrent
    # use — reads included, not only writes — and the server is threaded.
    def has_batch(self, batch_id: str) -> bool:
        return self._one("SELECT 1 FROM batch WHERE batch_id = ?", (batch_id,)) is not None

    def batch_hash(self, batch_id: str) -> str | None:
        row = self._one("SELECT content_hash FROM batch WHERE batch_id = ?", (batch_id,))
        return row["content_hash"] if row else None

    def event_hash(self, event_id: str) -> str | None:
        row = self._one("SELECT content_hash FROM evidence_event WHERE event_id = ?", (event_id,))
        return row["content_hash"] if row else None

    def count(self) -> int:
        return int(self._one("SELECT COUNT(*) AS n FROM evidence_event")["n"])

    def events(self, subject_ref: str | None = None) -> list[StoredEvent]:
        """In fold order: (occurred_at, event_id). O4 folds in this order, so the
        log hands it back in this order rather than making every caller sort."""
        sql = ("SELECT * FROM evidence_event "
               + ("WHERE subject_ref = ? " if subject_ref else "")
               + "ORDER BY occurred_at, event_id")
        rows = self._rows(sql, (subject_ref,) if subject_ref else ())
        return [self._hydrate(r) for r in rows]

    def events_for_skill(self, skill_id: str, *, include_quarantined: bool = False,
                         subject_ref: str | None = None) -> list[StoredEvent]:
        """Every admissible event bearing on one skill, in fold order.

        `subject_ref` matters more than it looks: without it a multi-subject log
        folds everyone's evidence into every developer's score. The filter is not
        an optimisation.
        """
        sql = ("SELECT e.* FROM evidence_event e JOIN event_skill s ON s.event_id = e.event_id "
               "WHERE s.skill_id = ? "
               + ("" if include_quarantined else "AND s.resolved = 1 ")
               + ("AND e.subject_ref = ? " if subject_ref else "")
               + "ORDER BY e.occurred_at, e.event_id")
        args = (skill_id, subject_ref) if subject_ref else (skill_id,)
        return [self._hydrate(r) for r in self._rows(sql, args)]

    def resolved_skills(self, subject_ref: str | None = None) -> list[str]:
        """Skills with at least one event the ontology resolved.

        A skill that is quarantined on every event naming it must not appear in
        a graph at all — it has no admissible evidence, so reporting a score for
        it would report the prior dressed up as a measurement.
        """
        sql = ("SELECT DISTINCT s.skill_id FROM event_skill s "
               "JOIN evidence_event e ON e.event_id = s.event_id "
               "WHERE s.resolved = 1"
               + (" AND e.subject_ref = ?" if subject_ref else "")
               + " ORDER BY s.skill_id")
        return [r["skill_id"] for r in
                self._rows(sql, (subject_ref,) if subject_ref else ())]

    def quarantined(self) -> dict[str, list[str]]:
        """event_id -> the skill_ids the ontology could not resolve."""
        rows = self._rows("SELECT event_id, skill_id FROM event_skill WHERE resolved = 0 "
                          "ORDER BY event_id, skill_id")
        out: dict[str, list[str]] = {}
        for row in rows:
            out.setdefault(row["event_id"], []).append(row["skill_id"])
        return out

    def batches(self) -> list[dict[str, Any]]:
        return [dict(r) for r in
                self._rows("SELECT * FROM batch ORDER BY ingested_at, batch_id")]

    # ── the only write ──────────────────────────────────────────────────────
    def append(self, batch: dict[str, Any], events: list[tuple[dict[str, Any], dict[str, bool]]]
               ) -> None:
        """Insert one batch and its events atomically.

        `events` pairs each event document with a {skill_id: resolved} map. All of
        it lands or none of it does — a half-written batch would leave the fold
        reading a state that never existed.
        """
        stamp = _now()
        try:
            with self._lock, self._db:  # one transaction; rolls back on any exception
                self._db.execute(
                    "INSERT INTO batch (batch_id, verification_id, subject_ref, emitted_at,"
                    " consent_scope, not_emitted, content_hash, event_count, ingested_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (batch["batch_id"], batch["verification_id"], batch["subject_ref"],
                     batch["emitted_at"], json.dumps(batch.get("consent_scope") or []),
                     json.dumps(batch.get("not_emitted") or []), content_hash(batch),
                     len(batch.get("events") or []), stamp))
                for document, resolution in events:
                    self._db.execute(
                        "INSERT INTO evidence_event (event_id, batch_id, verification_id,"
                        " subject_ref, kind, occurred_at, observed_at, strength, reliability,"
                        " direction, content_hash, document, ingested_at)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (document["event_id"], batch["batch_id"], batch["verification_id"],
                         batch["subject_ref"], document["kind"], document["occurred_at"],
                         document.get("observed_at"), document["strength"],
                         document["reliability"], document["direction"],
                         content_hash(document), json.dumps(document), stamp))
                    for skill_id, resolved in resolution.items():
                        relevance = next(r["relevance"] for r in document["skill_refs"]
                                         if r["skill_id"] == skill_id)
                        self._db.execute(
                            "INSERT INTO event_skill (event_id, skill_id, relevance, resolved)"
                            " VALUES (?,?,?,?)",
                            (document["event_id"], skill_id, relevance, int(resolved)))
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as exc:
            # A trigger's RAISE(ABORT) and a primary-key collision both surface as
            # IntegrityError, and they mean very different things: the first is
            # someone rewriting history, the second is the ingestor's own dedupe
            # having missed. Reporting them as one error would hide a real bug.
            if "append-only" in str(exc):
                raise ImmutableLog(str(exc)) from exc
            if isinstance(exc, sqlite3.IntegrityError):
                raise IngestError(f"the log refused this batch: {exc}") from exc
            raise

    # ── internals ───────────────────────────────────────────────────────────
    # The lock is re-entrant so a read taken inside another read — _hydrate
    # called from events() — does not deadlock against itself.
    def _rows(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _one(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._db.execute(sql, args).fetchone()

    def _hydrate(self, row: sqlite3.Row) -> StoredEvent:
        unresolved = tuple(
            r["skill_id"] for r in self._rows(
                "SELECT skill_id FROM event_skill WHERE event_id = ? AND resolved = 0"
                " ORDER BY skill_id", (row["event_id"],)))
        return StoredEvent(event_id=row["event_id"], subject_ref=row["subject_ref"],
                           kind=row["kind"], occurred_at=row["occurred_at"],
                           document=json.loads(row["document"]), quarantined_skills=unresolved)

    def __iter__(self) -> Iterator[StoredEvent]:
        return iter(self.events())
