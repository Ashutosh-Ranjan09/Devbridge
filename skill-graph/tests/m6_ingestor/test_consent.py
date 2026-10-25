"""Consent refusal.

Checked here as well as in the projection, on purpose. This is the one rule
where trusting the upstream service is not good enough: the cost of being wrong
is someone in a searchable talent pool who never agreed to be, and the log is
append-only, so there is no taking it back.
"""
from fixtures import batch, consented, ingestor, raises, unconsented
from m6_ingestor import ConsentRefused


def test_a_consented_batch_is_accepted():
    assert "skill_graph_inclusion" in consented()["consent_scope"]
    assert ingestor().ingest(consented()).stored == 8


def test_an_empty_consent_scope_is_refused():
    raises(ConsentRefused, ingestor().ingest, unconsented())


def test_a_missing_consent_scope_is_refused():
    """Absent is not permission. The schema makes consent_scope optional, so the
    ingestor must not read its absence as consent."""
    doc = consented()
    del doc["consent_scope"]
    raises(ConsentRefused, ingestor().ingest, doc)


def test_an_unrelated_scope_is_refused():
    """Consent to be verified is not consent to be listed."""
    doc = consented(consent_scope=["recruiter_visibility", "verification"])
    raises(ConsentRefused, ingestor().ingest, doc)


def test_refusal_writes_nothing():
    ing = ingestor()
    raises(ConsentRefused, ing.ingest, unconsented())
    assert ing.log.count() == 0
    assert ing.log.batches() == []


def test_refusal_survives_a_retry():
    """A refusal is a decision, not a transient failure. Retrying must not
    eventually succeed — that is exactly how consent controls get worn down."""
    ing = ingestor()
    for _ in range(5):
        raises(ConsentRefused, ing.ingest, unconsented())
    assert ing.log.count() == 0


def test_the_degraded_report_is_refused_end_to_end():
    """report-degraded.json has consent_ref: null. The projection emits nothing;
    independently, the ingestor refuses what it does emit."""
    doc = batch("report-degraded.json")
    assert doc["events"] == []
    assert doc["consent_scope"] == []
    raises(ConsentRefused, ingestor().ingest, doc)


def test_consent_is_checked_before_content():
    """An unconsented batch must be refused for that reason, not accidentally
    rescued or masked by some other property of its contents."""
    doc = unconsented()
    doc["events"] = []
    raises(ConsentRefused, ingestor().ingest, doc)


def test_the_refusal_names_the_batch_and_the_missing_scope():
    exc = raises(ConsentRefused, ingestor().ingest, unconsented())
    assert "skill_graph_inclusion" in str(exc)
    assert consented()["batch_id"] in str(exc)
