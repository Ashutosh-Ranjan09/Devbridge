"""Immutable persistence.

O4 recomputes every score by folding this log, so a row that quietly changes
rewrites history. Immutability is enforced by database trigger, and these tests
attack the database directly rather than going through the API — a rule that
only holds when you ask nicely is not a rule.
"""
import sqlite3

from fixtures import batch, ingestor, raises, seeded_ingestor
from m6_ingestor import EventLog, content_hash


def test_events_are_stored_verbatim():
    """The document goes in unchanged. The ingestor is a gate, not an editor."""
    ing = seeded_ingestor()
    stored = {e.event_id: e.document for e in ing.log.events()}
    for original in batch()["events"]:
        assert stored[original["event_id"]] == original


# A trigger's RAISE(ABORT) reaches Python as IntegrityError, not OperationalError.
ABORTED = sqlite3.IntegrityError


def test_an_update_is_refused_by_the_database():
    ing = seeded_ingestor()
    exc = raises(ABORTED, ing.log._db.execute,
                 "UPDATE evidence_event SET strength = 0.99")
    assert "append-only" in str(exc)


def test_a_delete_is_refused_by_the_database():
    ing = seeded_ingestor()
    exc = raises(ABORTED, ing.log._db.execute, "DELETE FROM evidence_event")
    assert "append-only" in str(exc)
    assert ing.log.count() == 8


def test_skill_rows_are_immutable_too():
    """The denormalised table is what 6.3 reads. Leaving it mutable would make
    the immutability of the document column decorative."""
    ing = seeded_ingestor()
    for sql in ("UPDATE event_skill SET relevance = 0.1", "DELETE FROM event_skill"):
        exc = raises(ABORTED, ing.log._db.execute, sql)
        assert "append-only" in str(exc)


def test_a_batch_row_cannot_orphan_its_events():
    """Foreign keys are on: an event must point at a batch that exists."""
    ing = seeded_ingestor()
    raises(sqlite3.IntegrityError, ing.log._db.execute,
           "INSERT INTO evidence_event (event_id, batch_id, verification_id, subject_ref,"
           " kind, occurred_at, strength, reliability, direction, content_hash, document,"
           " ingested_at) VALUES ('ev_x','evb_nonexistent','v','s','cv_claim','2025-01-01',"
           "0.3,0.2,'positive','h','{}','2025-01-01')")


def test_a_batch_lands_atomically():
    """A half-written batch would leave the fold reading a state that never
    existed. The insert of the events and the insert of the batch row are one
    transaction, so a failure part-way through must roll the whole thing back."""
    log = EventLog(":memory:")
    ing = ingestor(log=log)
    doc = batch()
    # Corrupt the last event so the insert fails after earlier ones succeeded.
    doc["events"][-1] = dict(doc["events"][-1])
    del doc["events"][-1]["kind"]
    try:
        log.append(doc, [(e, {r["skill_id"]: True for r in e["skill_refs"]})
                         for e in doc["events"]])
    except Exception:
        pass
    assert log.count() == 0, "a partial batch survived a failed append"
    assert log.batches() == []


def test_events_come_back_in_fold_order():
    """O4 folds in (occurred_at, event_id) order, so the log returns them that
    way rather than making every caller remember to sort."""
    ing = seeded_ingestor()
    keys = [(e.occurred_at, e.event_id) for e in ing.log.events()]
    assert keys == sorted(keys)


def test_fold_order_is_stable_regardless_of_arrival_order():
    """Events arriving shuffled must still fold in the same order."""
    doc = batch()
    reversed_doc = dict(doc, events=list(reversed(doc["events"])))
    a = ingestor(); a.ingest(doc)
    b = ingestor(); b.ingest(reversed_doc)
    assert [e.event_id for e in a.log.events()] == [e.event_id for e in b.log.events()]


def test_the_log_survives_being_reopened(tmp_path=None):
    """The whole point of persistence: a restart must not lose the log."""
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as folder:
        path = str(pathlib.Path(folder) / "evidence.db")
        first = EventLog(path)
        ingestor(log=first).ingest(batch())
        first.close()

        second = EventLog(path)
        assert second.count() == 8
        # And it still deduplicates against what a previous process wrote.
        assert ingestor(log=second).ingest(batch()).replayed is True
        second.close()


def test_filtering_by_subject_returns_only_that_subject():
    ing = seeded_ingestor()
    subject = batch()["subject_ref"]
    assert len(ing.log.events(subject)) == 8
    assert ing.log.events("subj_nobody") == []


def test_the_batch_row_records_what_was_suppressed():
    """not_emitted[] is why the graph can distinguish 'considered and rejected'
    from 'never seen'. Storing the events but discarding that would lose it."""
    import json
    ing = seeded_ingestor()
    row = ing.log.batches()[0]
    assert json.loads(row["not_emitted"]) == batch()["not_emitted"]
    assert row["event_count"] == 8


def test_content_hash_ignores_key_order_but_not_values():
    a = {"x": 1, "y": [1, 2]}
    assert content_hash(a) == content_hash({"y": [1, 2], "x": 1})
    assert content_hash(a) != content_hash({"x": 1, "y": [2, 1]})
