"""Quarantine for unknown skills.

The invariant is "an unknown skill_id is emitted and quarantined by M6, never
silently dropped". Both halves matter: dropping loses evidence the ontology has
merely not caught up with, and scoring it invents a node nobody defined.
"""
from fixtures import consented, ingestor, mutate_event
from m6_ingestor import EventLog, Ingestor
from m6_ontology import AcceptAll, SeedOntology, default_ontology


def _with_unknown_skill(skill="quantum_telepathy"):
    doc = consented()
    doc["events"][0]["skill_refs"] = [{"skill_id": skill, "relevance": 0.9}]
    return doc


def seeded():
    return Ingestor(EventLog(":memory:"), ontology=default_ontology())


def test_the_seed_ontology_knows_the_worked_examples_skills():
    """If it did not, every event in the fixture would be quarantined and the
    tests below would pass for the wrong reason."""
    ontology = default_ontology()
    for skill in ("algorithms", "cpp", "typescript", "nextjs", "python", "mongodb",
                  "problem_solving", "javascript", "react", "deployment"):
        assert ontology.knows(skill), skill


def test_a_fully_known_batch_quarantines_nothing():
    receipt = seeded().ingest(consented())
    assert receipt.stored == 8
    assert receipt.quarantined == {}


def test_an_unknown_skill_is_quarantined_not_rejected():
    ing = seeded()
    receipt = ing.ingest(_with_unknown_skill())
    assert receipt.stored == 8, "the batch must still be accepted"
    assert len(receipt.quarantined) == 1
    assert list(receipt.quarantined.values())[0] == ("quantum_telepathy",)


def test_a_quarantined_event_is_still_stored():
    """It is evidence. The ontology being incomplete is our problem, not the
    candidate's, and the event must be there when 6.1 adds the node."""
    ing = seeded()
    doc = _with_unknown_skill()
    ing.ingest(doc)
    assert ing.log.count() == 8
    stored = {e.event_id: e for e in ing.log.events()}
    held = stored[doc["events"][0]["event_id"]]
    assert held.quarantined_skills == ("quantum_telepathy",)
    assert held.document == doc["events"][0], "stored verbatim, quarantine or not"


def test_a_quarantined_skill_is_held_out_of_scoring_reads():
    """6.3 must not fold it. The default read excludes it; asking explicitly
    returns it, so nothing is hidden."""
    ing = seeded()
    ing.ingest(_with_unknown_skill())
    assert ing.log.events_for_skill("quantum_telepathy") == []
    assert len(ing.log.events_for_skill("quantum_telepathy", include_quarantined=True)) == 1


def test_known_skills_on_the_same_event_are_not_quarantined():
    """An event naming three skills where one is unknown must still contribute
    to the two that are. Quarantine is per skill, not per event."""
    ing = seeded()
    doc = consented()
    doc["events"][0]["skill_refs"] = [{"skill_id": "python", "relevance": 0.9},
                                      {"skill_id": "quantum_telepathy", "relevance": 0.5}]
    ing.ingest(doc)
    assert len(ing.log.events_for_skill("python")) >= 1
    assert ing.log.events_for_skill("quantum_telepathy") == []


def test_the_quarantine_is_reportable():
    """Silence is never an option — an operator has to be able to see what is
    being held and go add it to the ontology."""
    ing = seeded()
    doc = _with_unknown_skill()
    ing.ingest(doc)
    held = ing.log.quarantined()
    assert held == {doc["events"][0]["event_id"]: ["quantum_telepathy"]}


def test_accept_all_quarantines_nothing():
    """The escape hatch for a deployment that wants the ontology to grow from
    evidence rather than gate it."""
    receipt = ingestor(ontology=AcceptAll()).ingest(_with_unknown_skill())
    assert receipt.quarantined == {}


def test_the_ontology_is_swappable():
    """6.1 replaces this by substitution, so the seam has to be real."""
    tiny = SeedOntology({"python": {"tier": "ecosystem"}}, "test-0.1")
    ing = Ingestor(EventLog(":memory:"), ontology=tiny)
    receipt = ing.ingest(consented())
    assert receipt.ontology_version == "test-0.1"
    assert len(receipt.quarantined) >= 7, "only python should have resolved"


def test_the_receipt_records_which_ontology_judged_it():
    """A quarantine decision is only interpretable against a version — the same
    event is quarantined under 0.1.0 and admitted under 0.2.0."""
    assert seeded().ingest(consented()).ontology_version == default_ontology().ontology_version
    assert ingestor(ontology=AcceptAll()).ingest(consented()).ontology_version == "accept-all"


def test_quarantine_does_not_change_the_stored_document():
    """Whatever the ontology thinks, the event is recorded as it arrived."""
    ing = seeded()
    doc = mutate_event(_with_unknown_skill(), 1, kind="cv_claim")
    ing.ingest(doc)
    by_id = {e.event_id: e.document for e in ing.log.events()}
    for original in doc["events"]:
        assert by_id[original["event_id"]] == original
