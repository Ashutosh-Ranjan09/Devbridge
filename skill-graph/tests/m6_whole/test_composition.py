"""Module 6 as one thing.

The submodule suites test each piece against fixtures. These test the wiring:
that the pieces compose in the right order, that a guarantee made by one is not
undone by another, and that the facade is a convenience rather than a second
implementation.
"""
from datetime import date, timedelta

from whole_fixtures import (DEMO_AS_OF, DEMO_SUBJECT, GOLDEN_AS_OF, GOLDEN_SUBJECT,
                            demo_report, loaded, raises, report)


def test_a_report_becomes_a_graph_in_one_call():
    with loaded() as m6:
        assert m6.ingest_report(report()).replayed is True   # already loaded
        assert len(m6.skills(GOLDEN_SUBJECT, GOLDEN_AS_OF)) > 5


def test_the_facade_reproduces_the_published_graph():
    """The composition must not change any number the submodules produce."""
    published = {"algorithms": 0.533, "cpp": 0.514, "typescript": 0.381,
                 "nextjs": 0.316, "python": 0.189, "mongodb": 0.173}
    with loaded() as m6:
        got = {v.skill_id: v.lower for v in m6.skills(GOLDEN_SUBJECT, GOLDEN_AS_OF)}
    for skill, value in published.items():
        assert abs(got[skill] - value) < 0.01, skill


def test_every_contract_version_is_reportable():
    """A score without the contracts behind it cannot be reproduced or disputed."""
    with loaded() as m6:
        versions = m6.versions()
    for key in ("m6", "m6_projection", "m6_ontology", "m6_ingestor", "m6_scoring",
                "m6_query", "m6_integrity", "projection_rules", "parameters",
                "integrity_rules", "ontology"):
        assert versions.get(key), key


def test_ingesting_twice_changes_nothing_anywhere():
    """Idempotency stated where it matters: the graph after a redelivery is
    identical, not merely the event count."""
    with loaded() as m6:
        before = m6.profile(GOLDEN_SUBJECT, GOLDEN_AS_OF)
        for _ in range(3):
            m6.ingest_report(report())
        assert m6.profile(GOLDEN_SUBJECT, GOLDEN_AS_OF) == before


def test_consent_refusal_propagates_through_the_facade():
    from m6_ingestor import ConsentRefused
    with loaded() as m6:
        raises(ConsentRefused, m6.ingest_report, report("report-degraded.json"))
        assert "subj_2c1d77e0" not in m6.subjects()


def test_two_subjects_stay_separate():
    with loaded(report(), demo_report()) as m6:
        assert set(m6.subjects()) == {GOLDEN_SUBJECT, DEMO_SUBJECT}
        golden = {v.skill_id for v in m6.skills(GOLDEN_SUBJECT, GOLDEN_AS_OF)}
        demo = {v.skill_id for v in m6.skills(DEMO_SUBJECT, DEMO_AS_OF)}
        assert "go" in demo and "go" not in golden
        assert "mongodb" in golden and "mongodb" not in demo


def test_the_profile_carries_skills_and_integrity_without_mixing_them():
    with loaded() as m6:
        profile = m6.profile(GOLDEN_SUBJECT, GOLDEN_AS_OF)
    assert set(profile) >= {"skills", "integrity", "parameter_version", "ontology_version"}
    assert "no overall score" in profile["note"]


def test_the_profile_publishes_no_aggregate_anywhere():
    banned = {"overall", "overall_score", "trust", "trust_score", "rating",
              "composite", "aggregate", "total_score", "grade"}

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                yield k
                yield from walk(v)
        elif isinstance(node, list):
            for item in node:
                yield from walk(item)

    with loaded() as m6:
        for key in walk(m6.profile(GOLDEN_SUBJECT, GOLDEN_AS_OF)):
            assert key not in banned, key


def test_a_quarantined_skill_is_absent_from_the_graph_but_present_in_integrity():
    """The two halves of "never silently dropped": no score, and a finding that
    says why."""
    with loaded(demo_report()) as m6:
        skills = {v.skill_id for v in m6.skills(DEMO_SUBJECT, DEMO_AS_OF)}
        assert "haskell" not in skills
        held = {s for f in m6.integrity(DEMO_SUBJECT, DEMO_AS_OF).findings
                if f.check_id == "QUARANTINED_EVIDENCE" for s in f.skills}
        assert "haskell" in held


def test_as_of_flows_through_every_layer():
    with loaded() as m6:
        early = m6.profile(GOLDEN_SUBJECT, date(2025, 1, 1))
        late = m6.profile(GOLDEN_SUBJECT, GOLDEN_AS_OF)
    assert len(early["skills"]) < len(late["skills"])
    assert early["as_of"] == "2025-01-01"


def test_the_graph_only_loses_confidence_as_time_passes():
    with loaded() as m6:
        now = {v.skill_id: v.upper - v.lower
               for v in m6.skills(GOLDEN_SUBJECT, GOLDEN_AS_OF)}
        later = {v.skill_id: v.upper - v.lower
                 for v in m6.skills(GOLDEN_SUBJECT, GOLDEN_AS_OF + timedelta(days=900))}
    for skill, width in now.items():
        assert later[skill] > width, skill


def test_project_alone_does_not_store_anything():
    """6.0 is usable on its own — seeing the events before committing to them is
    the whole point of keeping projection separate from ingestion."""
    with loaded() as m6:
        count = m6.log.count()
        batch = m6.project(demo_report())
        assert batch["events"] and m6.log.count() == count


def test_the_facade_and_the_submodules_agree():
    """The facade must be a convenience, not a second implementation."""
    from m6_projection import project
    from m6_query import QueryService
    with loaded() as m6:
        assert m6.project(report()) == project(report(), module_version="1.0.0").to_dict()
        direct = QueryService(m6.log, m6.engine, ontology=m6.ontology)
        assert ([v.to_dict() for v in direct.skills(GOLDEN_SUBJECT, GOLDEN_AS_OF)]
                == [v.to_dict() for v in m6.skills(GOLDEN_SUBJECT, GOLDEN_AS_OF)])


def test_closing_releases_the_log():
    import sqlite3
    m6 = loaded()
    m6.close()
    raises(sqlite3.ProgrammingError, m6.log.count)
