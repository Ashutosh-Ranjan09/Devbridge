"""Where verifications live between the POST that starts one and the GET that reads it.

Two implementations behind one Protocol. `MemoryStore` needs nothing and loses
everything on restart; `PostgresStore` survives one and can be shared by more than a
single process. `CVV_DATABASE_URL` chooses, `GET /healthz` reports which by name, and
`api.py` cannot tell the difference — the Protocol is what makes that true, and mypy
checks both satisfy it rather than trusting that they do.

The stored object is the VerificationReport itself, as JSONB. No ORM and no mapped
tables, deliberately: the report is a deep pydantic tree that already round-trips
through JSON by contract, and shredding it into columns would create a second schema
to keep in step with the first. What the columns hold is what has to be QUERIED —
the id, the status, the timestamps, the idempotency key.
"""

from __future__ import annotations

import datetime
import threading
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from cvv.config import settings
from cvv.logs import get
from cvv.models import VerificationReport, Webhook


@dataclass
class Pending:
    """A verification that has been accepted and has not finished.

    Held separately from the finished report rather than as a nullable field on one:
    a half-populated VerificationReport would be a model whose invariants — every
    bucket referencing a real finding — could not hold while it was being built.
    """

    verification_id: str
    created_at: datetime.datetime
    idempotency_key: str | None = None


class Duplicate(Exception):  # noqa: N818 - a settled race, not an error
    """This idempotency key already started a verification, and here is its id.

    Both stores raise it and the API turns it into the same 200 it returns from the
    pre-check. Without it the two implementations disagreed under a race that the
    pre-check cannot close: MemoryStore quietly rebound the key to a second
    verification, and PostgresStore raised a UniqueViolation that reached the client
    as a 500. The database is the only place that race can be settled, so the
    exception is how it is reported.
    """

    def __init__(self, verification_id: str) -> None:
        super().__init__(f"already started as {verification_id}")
        self.verification_id = verification_id


@runtime_checkable
class Store(Protocol):
    """Six methods. Anything satisfying these can back the HTTP surface."""

    name: str
    started: datetime.datetime

    def accept(self, verification_id: str, *, idempotency_key: str | None = None) -> Pending: ...
    def existing(self, idempotency_key: str) -> str | None: ...
    def complete(self, report: VerificationReport) -> None: ...
    def report(self, verification_id: str) -> VerificationReport | None: ...
    def pending(self, verification_id: str) -> Pending | None: ...
    def register(self, hook: Webhook) -> None: ...
    def webhooks(self) -> list[Webhook]: ...
    def counts(self) -> tuple[int, int, int]: ...


@dataclass
class MemoryStore:
    """Not thread-safe by accident — thread-safe on purpose.

    FastAPI runs sync handlers in a thread pool and `BackgroundTasks` in another, so
    a completion can land while a GET is reading. One lock over a few dict operations
    costs nothing measurable and removes a class of bug that only appears under load,
    which is exactly when nobody can reproduce it.
    """

    started: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
    _pending: dict[str, Pending] = field(default_factory=dict)
    _reports: dict[str, VerificationReport] = field(default_factory=dict)
    _by_key: dict[str, str] = field(default_factory=dict)
    _webhooks: list[Webhook] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    name = "memory"

    def accept(self, verification_id: str, *, idempotency_key: str | None = None) -> Pending:
        with self._lock:
            if idempotency_key and (known := self._by_key.get(idempotency_key)):
                raise Duplicate(known)
            job = Pending(
                verification_id=verification_id,
                created_at=datetime.datetime.now(datetime.UTC),
                idempotency_key=idempotency_key,
            )
            self._pending[verification_id] = job
            if idempotency_key:
                self._by_key[idempotency_key] = verification_id
            return job

    def existing(self, idempotency_key: str) -> str | None:
        """The verification this key already started, if it started one.

        Idempotency is not a nicety here. A client retrying a 30-second upload after
        a timeout would otherwise run the whole pipeline again — another model load,
        another set of API calls against someone's rate limit — and hand back a
        second id for the same document.
        """
        with self._lock:
            return self._by_key.get(idempotency_key)

    def complete(self, report: VerificationReport) -> None:
        with self._lock:
            self._reports[report.verification_id] = report
            self._pending.pop(report.verification_id, None)

    def report(self, verification_id: str) -> VerificationReport | None:
        with self._lock:
            return self._reports.get(verification_id)

    def pending(self, verification_id: str) -> Pending | None:
        with self._lock:
            return self._pending.get(verification_id)

    def register(self, hook: Webhook) -> None:
        with self._lock:
            # Deduplicated by id, matching the Postgres ON CONFLICT DO NOTHING. The
            # unconditional append was a real divergence: registering the same hook
            # twice made this store fire it twice per verification and Postgres fire
            # it once. Same shape, different behaviour — which is why one suite runs
            # against both.
            if any(existing.webhook_id == hook.webhook_id for existing in self._webhooks):
                return
            self._webhooks.append(hook)

    def webhooks(self) -> list[Webhook]:
        with self._lock:
            return list(self._webhooks)

    def counts(self) -> tuple[int, int, int]:
        """total, completed, failed."""
        with self._lock:
            completed = [r for r in self._reports.values() if r.status.value != "failed"]
            failed = [r for r in self._reports.values() if r.status.value == "failed"]
            return len(self._reports) + len(self._pending), len(completed), len(failed)


SCHEMA = """
CREATE TABLE IF NOT EXISTS verifications (
    verification_id TEXT PRIMARY KEY,
    status          TEXT NOT NULL,
    idempotency_key TEXT,
    created_at      TIMESTAMPTZ NOT NULL,
    completed_at    TIMESTAMPTZ,
    report          JSONB
);
-- Partial and UNIQUE: two concurrent retries of the same upload must not both start
-- a verification, and the check-then-insert in `accept` cannot prevent that on its
-- own. The database is the only place that race can be settled.
CREATE UNIQUE INDEX IF NOT EXISTS verifications_idempotency
    ON verifications (idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS verifications_status ON verifications (status);

CREATE TABLE IF NOT EXISTS webhooks (
    webhook_id TEXT PRIMARY KEY,
    url        TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
"""

PENDING = "pending"


class PostgresStore:
    """The same six methods, over psycopg 3 and plain SQL.

    A pool rather than a connection: FastAPI runs sync handlers in a thread pool and
    background tasks in another, and a single psycopg connection is not safe to share
    across threads. The pool hands each thread its own.

    The schema is applied at construction with `IF NOT EXISTS` rather than by a
    migration tool — Alembic is in the stack's "not used" list, and one idempotent
    DDL statement is the honest amount of machinery for two tables. When the schema
    needs to CHANGE rather than exist, that is the moment to add a migration tool,
    not before.
    """

    name = "postgres"

    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 8) -> None:
        from psycopg_pool import ConnectionPool

        self.started = datetime.datetime.now(datetime.UTC)
        self.pool = ConnectionPool(dsn, min_size=min_size, max_size=max_size, open=True)
        self.pool.wait(timeout=10.0)
        with self.pool.connection() as conn:
            conn.execute(SCHEMA)

    def close(self) -> None:
        self.pool.close()

    def accept(self, verification_id: str, *, idempotency_key: str | None = None) -> Pending:
        import psycopg

        now = datetime.datetime.now(datetime.UTC)
        try:
            with self.pool.connection() as conn:
                conn.execute(
                    "INSERT INTO verifications "
                    "(verification_id, status, idempotency_key, created_at) "
                    "VALUES (%s, %s, %s, %s)",
                    (verification_id, PENDING, idempotency_key, now),
                )
        except psycopg.errors.UniqueViolation as exc:
            # The race the pre-check cannot close: two retries of one upload arriving
            # together. The unique index settles it and the loser gets the winner's id.
            if idempotency_key and (known := self.existing(idempotency_key)):
                raise Duplicate(known) from exc
            raise
        return Pending(
            verification_id=verification_id, created_at=now, idempotency_key=idempotency_key
        )

    def existing(self, idempotency_key: str) -> str | None:
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT verification_id FROM verifications WHERE idempotency_key = %s",
                (idempotency_key,),
            ).fetchone()
        return str(row[0]) if row else None

    def complete(self, report: VerificationReport) -> None:
        """One statement, so a report is never half-written.

        `model_dump_json` rather than `model_dump`: the pydantic tree holds dates,
        datetimes and enums that json.dumps cannot serialise, and the model already
        knows how to render each of them exactly as the contract says.
        """
        with self.pool.connection() as conn:
            conn.execute(
                "UPDATE verifications SET status = %s, completed_at = %s, report = %s "
                "WHERE verification_id = %s",
                (
                    report.status.value,
                    datetime.datetime.now(datetime.UTC),
                    report.model_dump_json(),
                    report.verification_id,
                ),
            )

    def report(self, verification_id: str) -> VerificationReport | None:
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT report FROM verifications WHERE verification_id = %s",
                (verification_id,),
            ).fetchone()
        if row is None or row[0] is None:
            return None
        return VerificationReport.model_validate(row[0])

    def pending(self, verification_id: str) -> Pending | None:
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT created_at, idempotency_key FROM verifications "
                "WHERE verification_id = %s AND report IS NULL",
                (verification_id,),
            ).fetchone()
        if row is None:
            return None
        return Pending(
            verification_id=verification_id, created_at=row[0], idempotency_key=row[1]
        )

    def register(self, hook: Webhook) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                "INSERT INTO webhooks (webhook_id, url, created_at) VALUES (%s, %s, %s) "
                "ON CONFLICT (webhook_id) DO NOTHING",
                (hook.webhook_id, str(hook.url), hook.created_at),
            )

    def webhooks(self) -> list[Webhook]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                "SELECT webhook_id, url, created_at FROM webhooks ORDER BY created_at"
            ).fetchall()
        return [Webhook(webhook_id=r[0], url=r[1], created_at=r[2]) for r in rows]

    def counts(self) -> tuple[int, int, int]:
        """Counted in the database, not by loading every report into memory.

        The naive version reads every stored VerificationReport — each one a whole
        claim graph — to count three integers, and gets slower with every
        verification the service has ever done.
        """
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT count(*), "
                "count(*) FILTER (WHERE status IN ('completed', 'completed_degraded')), "
                "count(*) FILTER (WHERE status = 'failed') "
                "FROM verifications"
            ).fetchone()
        assert row is not None
        return int(row[0]), int(row[1]), int(row[2])


log = get("cvv.store")


def build(dsn: str | None) -> Store:
    """Postgres when a DSN is configured, memory when it is not.

    A DSN that is set and unreachable RAISES rather than falling back. Silently
    serving from memory when someone asked for a database is how a service comes back
    from a restart having lost everything while reporting itself healthy.
    """
    if not dsn:
        log.warning(
            "store.memory",
            detail="verifications are lost on restart and shared by no other process",
        )
        return MemoryStore()
    store = PostgresStore(dsn)
    log.info("store.postgres")  # never the DSN: it carries a password
    return store


STORE: Store = build(settings.database_url)
