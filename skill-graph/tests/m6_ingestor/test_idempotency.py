"""Replay is a no-op; a changed replay is a conflict.

event_id is sha256(verification_id, kind, discriminator) — identity derived from
what the evidence is ABOUT, not from what it says. That is what makes
at-least-once delivery safe, and it is also what makes a changed value under a
known id a real problem rather than a delivery artefact.
"""
import copy

from fixtures import batch, ids, ingestor, mutate_event, raises, seeded_ingestor
from m6_ingestor import ConflictingEvent


def test_the_same_batch_twice_stores_one_copy():
    ing = ingestor()
    first = ing.ingest(batch())
    second = ing.ingest(batch())
    assert first.stored == 8 and second.stored == 0
    assert second.replayed is True
    assert ing.log.count() == 8


def test_replay_reports_every_event_as_a_duplicate():
    ing = seeded_ingestor()
    receipt = ing.ingest(batch())
    assert set(receipt.duplicates) == set(ids(batch()))
    assert receipt.accepted == ()


def test_ten_replays_change_nothing():
    """At-least-once delivery means this happens for real, not hypothetically."""
    ing = ingestor()
    for _ in range(10):
        ing.ingest(batch())
    assert ing.log.count() == 8
    assert len(ing.log.batches()) == 1


def test_key_order_does_not_defeat_deduplication():
    """The hash is over the document's VALUE. A proxy that reserialises JSON with
    different key order must not look like a different batch."""
    doc = batch()
    shuffled = {k: doc[k] for k in reversed(list(doc))}
    shuffled["events"] = [{k: e[k] for k in reversed(list(e))} for e in doc["events"]]
    ing = ingestor()
    ing.ingest(doc)
    assert ing.ingest(shuffled).replayed is True
    assert ing.log.count() == 8


def test_a_changed_event_under_a_known_batch_id_is_a_conflict():
    """The projection is deterministic, so this means it changed its mind about
    the same evidence. History is not rewritten to accommodate that."""
    ing = seeded_ingestor()
    exc = raises(ConflictingEvent, ing.ingest, mutate_event(batch(), strength=0.99))
    assert batch()["batch_id"] in str(exc)


def test_a_conflicting_batch_writes_nothing():
    ing = seeded_ingestor()
    raises(ConflictingEvent, ing.ingest, mutate_event(batch(), strength=0.99))
    assert ing.log.count() == 8
    stored = {e.event_id: e.document["strength"] for e in ing.log.events()}
    assert 0.99 not in stored.values(), "the conflicting value leaked into the log"


def test_a_known_event_inside_a_new_batch_is_a_duplicate_not_an_error():
    """Re-verification that reached the same conclusion. The event is already
    known; the new batch is recorded, the event is not stored twice."""
    ing = seeded_ingestor()
    doc = batch()
    doc["batch_id"] = "evb_second_run"
    receipt = ing.ingest(doc)
    assert receipt.replayed is False
    assert receipt.accepted == ()
    assert set(receipt.duplicates) == set(ids(doc))
    assert ing.log.count() == 8
    assert len(ing.log.batches()) == 2


def test_a_known_event_with_new_content_in_a_new_batch_conflicts():
    """The dangerous case: a projection bug fix produces the same event_id with a
    different strength. Silently accepting it would corrupt the fold."""
    ing = seeded_ingestor()
    doc = mutate_event(batch(), strength=0.99)
    doc["batch_id"] = "evb_after_a_bugfix"
    exc = raises(ConflictingEvent, ing.ingest, doc)
    assert exc.event_id == ids(doc)[0]


def test_a_partly_new_batch_stores_only_what_is_new():
    ing = seeded_ingestor()
    doc = batch()
    doc["batch_id"] = "evb_mixed"
    fresh = copy.deepcopy(doc["events"][0])
    fresh["event_id"] = "ev_brandnew0001"
    doc["events"] = doc["events"][:3] + [fresh]
    receipt = ing.ingest(doc)
    assert receipt.accepted == ("ev_brandnew0001",)
    assert len(receipt.duplicates) == 3
    assert ing.log.count() == 9


def test_event_ids_are_stable_across_projections():
    """The premise the whole scheme rests on. If the projection stopped being
    deterministic, deduplication would silently become double-counting."""
    from fixtures import batch
    assert ids(batch()) == ids(batch())
