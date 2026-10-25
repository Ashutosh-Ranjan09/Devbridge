"""The schema is re-checked at the boundary.

M5 and M6 are separate services. That the producer validated on its way out is
not evidence that what arrived is valid, and a malformed event in an append-only
log cannot be taken back out again.
"""
from fixtures import batch, consented, ids, ingestor, mutate_event, raises
from m6_ingestor import SchemaInvalid


def test_a_valid_batch_is_accepted():
    receipt = ingestor().ingest(consented())
    assert receipt.stored == 8


def test_a_non_object_is_rejected():
    for junk in ([], "a batch", 7, None):
        raises(SchemaInvalid, ingestor().ingest, junk)


def test_a_batch_missing_a_required_field_is_rejected():
    for field in ("batch_id", "verification_id", "subject_ref", "emitted_at", "events"):
        doc = consented()
        del doc[field]
        exc = raises(SchemaInvalid, ingestor().ingest, doc)
        assert field in str(exc), f"{field} removed but not named in {exc}"


def test_an_undeclared_field_is_rejected():
    """additionalProperties:false is what stops a producer from smuggling an
    `observed` value past the contract."""
    doc = mutate_event(consented(), observed=0.74)
    raises(SchemaInvalid, ingestor().ingest, doc)


def test_an_unknown_event_kind_is_rejected():
    doc = mutate_event(consented(), kind="vibes")
    exc = raises(SchemaInvalid, ingestor().ingest, doc)
    assert "kind" in str(exc)


def test_out_of_range_values_are_rejected():
    for field, value in (("strength", 1.5), ("reliability", -0.2)):
        raises(SchemaInvalid, ingestor().ingest, mutate_event(consented(), **{field: value}))


def test_an_event_with_no_skill_refs_is_rejected():
    """minItems:1 — an event that names no skill cannot be folded into anything."""
    raises(SchemaInvalid, ingestor().ingest, mutate_event(consented(), skill_refs=[]))


def test_a_duplicate_event_id_within_one_batch_is_rejected():
    """The schema cannot express this — uniqueness is a property of the batch,
    not of any single event — so the ingestor checks it. Left unchecked, the
    accepted/duplicate counts in the receipt would be a lie."""
    doc = consented()
    doc["events"][1]["event_id"] = doc["events"][0]["event_id"]
    exc = raises(SchemaInvalid, ingestor().ingest, doc)
    assert "repeated within the batch" in str(exc)


def test_a_rejected_batch_writes_nothing():
    """Validation runs before any insert, so a bad batch leaves no trace."""
    ing = ingestor()
    raises(SchemaInvalid, ing.ingest, mutate_event(consented(), kind="vibes"))
    assert ing.log.count() == 0
    assert ing.log.batches() == []


def test_the_error_names_where_the_failure_was():
    """A producer that has drifted needs to be told where, not merely that."""
    exc = raises(SchemaInvalid, ingestor().ingest, mutate_event(consented(), strength=9.9))
    assert exc.path, "a schema failure with no path is not actionable"
    assert "events/0" in exc.path


def test_an_empty_event_list_is_valid():
    """A report that projected to nothing is a legitimate outcome — the
    suppressions in not_emitted[] are still worth recording."""
    doc = consented()
    doc["events"] = []
    receipt = ingestor().ingest(doc)
    assert receipt.stored == 0
    assert len(ingestor().log.batches()) == 0  # a different, clean ingestor


def test_the_batch_that_the_projection_actually_produces_validates():
    """Guards the seam: if the projection's output stops satisfying the schema,
    this suite fails rather than the integration."""
    doc = batch()
    assert len(ids(doc)) == 8
    ingestor().ingest(doc)
