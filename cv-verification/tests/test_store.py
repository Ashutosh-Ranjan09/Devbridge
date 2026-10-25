"""One suite, both stores.

The Protocol makes mypy check that `MemoryStore` and `PostgresStore` have the same
SHAPE. Only this file checks they have the same BEHAVIOUR, and the difference is not
academic: before it existed, a duplicate idempotency key made MemoryStore quietly
rebind the key to a second verification and made PostgresStore raise a UniqueViolation
that reached the client as a 500. Same shape, opposite answers.

Every test here runs against both. The Postgres half is skipped unless
CVV_DATABASE_URL points at a database — a test run must need no server.
"""

from __future__ import annotations

import datetime
import os
from collections.abc import Iterator

import pytest

from cvv.models import (
    ReportStatus,
    VerificationReport,
    Webhook,
)
from cvv.store import Duplicate, MemoryStore, Store
from tests.cvdata import contract_report

NOW = datetime.datetime(2026, 9, 4, tzinfo=datetime.UTC)
DSN = os.environ.get("CVV_DATABASE_URL")


def report(verification_id: str, status: ReportStatus = ReportStatus.COMPLETED) -> VerificationReport:
    return contract_report(verification_id, status)


@pytest.fixture(params=["memory", "postgres"])
def store(request: pytest.FixtureRequest) -> Iterator[Store]:
    if request.param == "memory":
        yield MemoryStore()
        return

    if not DSN:
        pytest.skip("set CVV_DATABASE_URL to run the Postgres half")
    from cvv.store import PostgresStore

    backing = PostgresStore(DSN)
    # A schema per test, dropped after. Sharing one would make these order-dependent
    # through the database exactly as the API tests were through the response cache.
    with backing.pool.connection() as conn:
        conn.execute("TRUNCATE verifications, webhooks")
    yield backing
    backing.close()


class TestTheContractBothMustKeep:
    def test_an_accepted_verification_is_pending_and_has_no_report(self, store: Store) -> None:
        job = store.accept("vr_1")
        assert job.verification_id == "vr_1"
        assert job.created_at.tzinfo is not None, "timestamps are timezone-aware everywhere"
        assert store.pending("vr_1") is not None
        assert store.report("vr_1") is None

    def test_completing_moves_it_from_pending_to_report(self, store: Store) -> None:
        store.accept("vr_2")
        store.complete(report("vr_2"))
        assert store.pending("vr_2") is None
        assert store.report("vr_2") is not None

    def test_the_report_survives_the_round_trip_unchanged(self, store: Store) -> None:
        """A VerificationReport is a deep pydantic tree carrying dates, datetimes and
        enums. JSONB stores what `model_dump_json` renders, which is what the contract
        says the report IS — so what comes back has to be equal, not merely similar."""
        original = report("vr_3")
        store.accept("vr_3")
        store.complete(original)
        assert store.report("vr_3") == original

    def test_an_unknown_id_is_none_in_both_directions(self, store: Store) -> None:
        assert store.report("vr_nope") is None
        assert store.pending("vr_nope") is None

    def test_a_duplicate_idempotency_key_raises_with_the_first_id(self, store: Store) -> None:
        """The behaviour that differed. MemoryStore rebound the key to the second
        verification; PostgresStore raised a UniqueViolation that became a 500."""
        store.accept("vr_first", idempotency_key="k")
        with pytest.raises(Duplicate) as clash:
            store.accept("vr_second", idempotency_key="k")
        assert clash.value.verification_id == "vr_first"
        assert store.pending("vr_second") is None, "the loser must start nothing"

    def test_a_key_that_started_nothing_is_none(self, store: Store) -> None:
        assert store.existing("never-seen") is None

    def test_accepting_without_a_key_is_never_a_duplicate(self, store: Store) -> None:
        store.accept("vr_a")
        store.accept("vr_b")
        assert store.counts()[0] == 2

    def test_counts_separate_completed_from_failed(self, store: Store) -> None:
        for vid, status in (
            ("vr_ok", ReportStatus.COMPLETED),
            ("vr_deg", ReportStatus.COMPLETED_DEGRADED),
            ("vr_bad", ReportStatus.FAILED),
        ):
            store.accept(vid)
            store.complete(report(vid, status))
        store.accept("vr_running")
        total, completed, failed = store.counts()
        assert (total, completed, failed) == (4, 2, 1)

    def test_webhooks_round_trip(self, store: Store) -> None:
        hook = Webhook(webhook_id="wh_1", url="https://example.com/hook", created_at=NOW)
        store.register(hook)
        assert [h.webhook_id for h in store.webhooks()] == ["wh_1"]

    def test_registering_the_same_webhook_twice_is_idempotent(self, store: Store) -> None:
        hook = Webhook(webhook_id="wh_1", url="https://example.com/hook", created_at=NOW)
        store.register(hook)
        store.register(hook)
        assert len(store.webhooks()) == 1


class TestChoosingOne:
    def test_no_dsn_gives_memory(self) -> None:
        from cvv.store import build

        assert build(None).name == "memory"
        assert build("").name == "memory"

    def test_an_unreachable_dsn_raises_rather_than_falling_back(self) -> None:
        """Silently serving from memory when someone asked for a database is how a
        service comes back from a restart having lost everything while reporting
        itself healthy."""
        from cvv.store import build

        with pytest.raises(Exception, match=r"(?i)connect|timeout|refused|pool"):
            build("postgresql://nobody:nobody@127.0.0.1:1/nothing")
