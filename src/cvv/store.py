"""Where verifications live between the POST that starts one and the GET that reads it.

In memory, behind a narrow interface, because Postgres is declared in the stack and
unbuilt and nothing yet needs it to be. What that buys is the swap: a Postgres
implementation has to satisfy these six methods and nothing in `api.py` changes.

What it costs is stated rather than hidden — a restart loses every verification, and
two processes do not share one. Both are fine for a single-process research service
and are wrong for anything else, so `GET /healthz` reports the backing store by name.
"""

from __future__ import annotations

import datetime
import threading
from dataclasses import dataclass, field

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


STORE = MemoryStore()
