"""6.5 reads. It does not write, and it does not move a number.

This is the whole reason integrity analytics is a separate submodule rather than
a reliability adjustment inside 6.3. A signal that silently changed a score
would be an unexplainable penalty, and there is no overall trust number here to
absorb it — so the guarantee is asserted directly rather than assumed.
"""
from datetime import date

from integrity_fixtures import AS_OF, SUBJECT, analyse, event, loaded, report


def test_running_the_analyser_changes_no_score():
    with loaded() as m6:
        before = {v.skill_id: (v.lower, v.upper, v.mean)
                  for v in m6.skills(SUBJECT, AS_OF)}
        for _ in range(3):
            m6.integrity(SUBJECT, AS_OF)
        after = {v.skill_id: (v.lower, v.upper, v.mean)
                 for v in m6.skills(SUBJECT, AS_OF)}
    assert before == after


def test_running_the_analyser_writes_nothing_to_the_log():
    with loaded() as m6:
        before = [e["event_id"] for e in m6.events()]
        count = m6.log.count()
        m6.integrity(SUBJECT, AS_OF)
        assert m6.log.count() == count
        assert [e["event_id"] for e in m6.events()] == before


def test_the_analyser_does_not_mutate_the_events_it_reads():
    import copy
    events = [event(event_id="ev_1"), event(event_id="ev_2", kind="cv_claim")]
    snapshot = copy.deepcopy(events)
    analyse(events)
    assert events == snapshot


def test_findings_are_attached_beside_the_skills_never_folded_in():
    """In a profile the two sit side by side. If integrity were ever folded into
    a score, this is where it would show up."""
    with loaded() as m6:
        profile = m6.profile(SUBJECT, AS_OF)
        standalone = {v.skill_id: v.to_dict()["interval"]
                      for v in m6.skills(SUBJECT, AS_OF)}
    assert {s["skill_id"]: s["interval"] for s in profile["skills"]} == standalone
    assert "integrity" in profile and profile["integrity"]["findings"]


def test_no_finding_carries_a_score_or_a_penalty():
    """A number in a finding would be read as an adjustment. Metrics describe the
    evidence — counts, shares, ages — never a correction to apply."""
    banned = {"penalty", "adjustment", "score", "multiplier", "weight",
              "trust", "deduction"}
    with loaded() as m6:
        for finding in m6.integrity(SUBJECT, AS_OF).findings:
            assert not (set(finding.metrics) & banned), finding.metrics


def test_every_finding_states_an_innocent_explanation():
    """A pattern presented without one reads as an accusation. The contract
    requires it and this asserts none is empty."""
    with loaded() as m6:
        for finding in m6.integrity(SUBJECT, AS_OF).findings:
            assert len(finding.innocent_explanation) > 30, finding.check_id


def test_every_finding_names_the_evidence_it_is_about():
    """A reader has to be able to go and look."""
    with loaded() as m6:
        for finding in m6.integrity(SUBJECT, AS_OF).findings:
            assert finding.skills or finding.event_ids, finding.check_id


def test_severities_stay_within_the_declared_two():
    from m6_integrity import SEVERITIES
    with loaded() as m6:
        for finding in m6.integrity(SUBJECT, AS_OF).findings:
            assert finding.severity in SEVERITIES


def test_there_is_no_fail_severity():
    """Nothing here is certain enough to condemn a candidate, and a third tier
    would invite thresholding on it."""
    from m6_integrity import SEVERITIES
    assert set(SEVERITIES) == {"notice", "attention"}


def test_attention_findings_are_ordered_before_notices():
    with loaded() as m6:
        order = [f.severity for f in m6.integrity(SUBJECT, AS_OF).findings]
    assert order == sorted(order, key=lambda s: 0 if s == "attention" else 1)


def test_the_report_is_deterministic():
    with loaded() as m6:
        a = m6.integrity(SUBJECT, AS_OF).to_dict()
        b = m6.integrity(SUBJECT, AS_OF).to_dict()
    assert a == b


def test_the_report_says_plainly_that_it_changes_nothing():
    with loaded() as m6:
        note = m6.integrity(SUBJECT, AS_OF).to_dict()["note"]
    assert "No score below is changed" in note


def test_findings_are_capped_and_the_truncation_is_declared():
    """A report nobody finishes is the same as no report — but silently dropping
    findings would be exactly the silence this system forbids."""
    wide = [event(event_id=f"ev_{i}", kind="cv_claim", skills=(f"skill_{i}",))
            for i in range(60)]
    got = analyse(wide)
    assert len(got.findings) <= 40
    if got.truncated:
        assert got.to_dict()["truncated"] == got.truncated
