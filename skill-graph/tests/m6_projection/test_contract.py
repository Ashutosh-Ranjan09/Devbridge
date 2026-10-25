"""Conformance to the committed JSON Schema, and the six invariants the
projection promises. These are the tests that must never be relaxed."""
import json

from helpers import SCHEMA, by_kind, degraded, full, ids, validate
from m6_projection import ContractViolation, project
from m6_projection.models import SUPPRESSION_REASONS


def test_full_report_output_validates_against_committed_schema():
    validate(project(full(), module_version="0.4.1"))


def test_degraded_report_output_validates_against_committed_schema():
    validate(project(degraded(), module_version="0.4.1"))


def test_schema_rejects_an_undeclared_field():
    """Guards the guard: if additionalProperties were ever relaxed, the
    conformance tests above would stop meaning anything."""
    import jsonschema
    doc = project(full()).to_dict()
    doc["events"][0]["observed"] = 0.74  # the field the projection must NOT emit
    try:
        jsonschema.validate(instance=doc, schema=json.loads(SCHEMA.read_text()))
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted an undeclared field; additionalProperties is not set")


def test_no_event_carries_an_observation_value():
    """The observation model belongs to the scoring engine — O1. The projection
    emits facts in payload and lets m6-parameters.yaml decide what they are worth."""
    for event in project(full()).to_dict()["events"]:
        assert "observed" not in event
        assert "observed_value" not in event


def test_reliability_equals_base_times_factors():
    for e in project(full()).events:
        expected = e.reliability_base or 0.0
        for f in e.reliability_factors:
            expected *= f.value
        assert abs(expected - e.reliability) < 1e-6, e.event_id


def test_every_factor_is_named_with_a_reason():
    for e in project(full()).events:
        for f in e.reliability_factors:
            assert f.factor and f.reason, f"{e.event_id}: unnamed reliability factor"


def test_event_ids_are_unique():
    got = ids(project(full()))
    assert len(got) == len(set(got))


def test_events_are_sorted_by_occurred_at():
    events = project(full()).events
    keys = [(str(e.occurred_at), e.event_id) for e in events]
    assert keys == sorted(keys), "O4 folds in occurred_at order; emit them that way"


def test_no_event_occurs_after_the_batch():
    batch = project(full())
    for e in batch.events:
        assert str(e.occurred_at)[:10] <= str(batch.emitted_at)[:10]


def test_every_suppression_uses_a_schema_reason():
    for s in project(full()).not_emitted + project(degraded()).not_emitted:
        assert s.reason in SUPPRESSION_REASONS
        assert s.what.strip(), "a suppression with no description is not auditable"


def test_skill_refs_are_never_empty():
    for e in project(full()).events:
        assert e.skill_refs, f"{e.event_id} would fail schema minItems:1"


def test_projection_is_deterministic():
    """Same report in, byte-identical batch out. Ingestion is idempotent on
    event_id, so a re-run must not produce new ids."""
    a = json.dumps(project(full(), module_version="0.4.1").to_dict(), sort_keys=True)
    b = json.dumps(project(full(), module_version="0.4.1").to_dict(), sort_keys=True)
    assert a == b


def test_invariant_check_actually_fires():
    """A deliberately corrupted event must be rejected, not passed through."""
    report = full()
    report["evidence_bundle"]["github"]["repos"][0]["last_commit"] = "2099-01-01"
    try:
        project(report)
    except ContractViolation as exc:
        assert "future" in str(exc)
        return
    raise AssertionError("an event dated in the future was accepted")


def test_platform_events_are_never_capped():
    """The handle resolved and the platform is the authority on its own ratings.
    Capping here would understate the strongest source in the system."""
    for e in by_kind(project(full()), "platform_rating"):
        assert e.reliability_factors == ()
        assert e.reliability == 0.90


def test_every_claim_is_accounted_for():
    """Silence is never an option, as a structural property rather than a habit:
    every claim M5 extracted is either carried by an event or named in
    not_emitted. A claim kind nobody wrote a branch for used to vanish here."""
    from helpers import full as _full
    report = _full()
    batch = project(report)
    referenced = {r for e in batch.events for r in e.source.claim_refs}
    explained = " ".join(s.what for s in batch.not_emitted)
    for claim in report["claim_graph"]["claims"]:
        cid = claim["claim_id"]
        assert cid in referenced or cid in explained, f"{cid} ({claim['kind']}) vanished"


def test_an_unhandled_claim_kind_fails_loudly():
    """The invariant is what makes the guarantee above hold for kinds that do
    not exist yet."""
    report = full()
    report["claim_graph"]["claims"].append(
        {"claim_id": "c_novel", "kind": "certification", "issuer": "Nobody",
         "provenance": {"char_start": 0, "char_end": 1, "verbatim": "x",
                        "recovery": "exact"}})
    batch = project(report)
    assert any("c_novel" in s.what for s in batch.not_emitted), \
        "an unconfirmable certification naming no skill must be recorded"


def test_a_verified_credential_carries_the_claim_it_confirms():
    report = full()
    report["claim_graph"]["claims"].append(
        {"claim_id": "c_aws", "kind": "certification", "issuer": "Amazon Web Services",
         "credential_id": "AWS-SAA-1", "skill_refs": ["aws"],
         "provenance": {"char_start": 0, "char_end": 1, "verbatim": "AWS",
                        "recovery": "exact"}})
    report["evidence_bundle"]["credentials"] = [
        {"credential_id": "AWS-SAA-1", "issuer": "Amazon Web Services",
         "status": "verified", "issued_at": "2025-02-11"}]
    event = by_kind(project(report), "credential_verified")[0]
    assert event.source.claim_refs == ("c_aws",)
    assert {r.skill_id for r in event.skill_refs} == {"aws"}


def test_an_unconfirmed_certification_becomes_a_weak_claim():
    report = full()
    report["claim_graph"]["claims"].append(
        {"claim_id": "c_gcp", "kind": "certification", "issuer": "Google Cloud",
         "skill_refs": ["docker"],
         "provenance": {"char_start": 0, "char_end": 1, "verbatim": "GCP",
                        "recovery": "exact"}})
    event = next(e for e in by_kind(project(report), "cv_claim")
                 if "c_gcp" in e.source.claim_refs)
    assert event.reliability == 0.20
    assert event.payload["issuer_confirmed"] is False
