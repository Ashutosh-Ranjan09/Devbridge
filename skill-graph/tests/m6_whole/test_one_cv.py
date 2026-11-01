"""One CV per developer.

Each completed CV report M6 receives is recorded as one of that developer's; whichever
was checked last (by M5's own clock, not by arrival) is their CV, and every older one is
replaced: its evidence stays in the log and is skipped. Assessment results never come
from a CV report, so no replacement can touch them. A skill is then whatever a fresh
replay of the surviving evidence says — the old CV leaves no trace in the number.
"""
import copy
import hashlib
import sqlite3

from whole_fixtures import GOLDEN_AS_OF, GOLDEN_SUBJECT, M6, report
from m6_ingestor.store import utc_instant


def cv(vid: str, checked: str, *, subject: str = GOLDEN_SUBJECT, status: str = "completed",
       without_codeforces: bool = False) -> dict:
    """The golden report as another check of a CV: its own id and time."""
    r = copy.deepcopy(report())
    r["verification_id"], r["valid_as_of"], r["status"] = vid, checked, status
    r["subject"]["subject_ref"] = subject
    if without_codeforces:
        r["evidence_bundle"]["platforms"] = []
    if status == "failed":
        # As M5 sends one: still a report, with nothing read from the document.
        r["claim_graph"]["claims"] = []
        r["findings"]["discrepancies"], r["findings"]["rule_outcomes"] = [], []
        r["evidence_bundle"].update(github=None, platforms=[], deployments=[], credentials=[])
    return r


def assessment_batch(session: str, when: str, *, skill: str = "algorithms", passed: int = 6, total: int = 6,
                subject: str = GOLDEN_SUBJECT) -> dict:
    """An assessment_result batch, shaped as the assessment module sends it."""
    return {
        "schema_version": "1.0.0", "batch_id": "evb_" + hashlib.sha256(session.encode()).hexdigest()[:12],
        "verification_id": session, "subject_ref": subject, "emitted_at": when, "not_emitted": [],
        "events": [{
            "event_id": "ev_" + hashlib.sha256(f"{session}|assessment_result|{skill}".encode()).hexdigest()[:12],
            "kind": "assessment_result", "occurred_at": when, "observed_at": when,
            "skill_refs": [{"skill_id": skill, "relevance": 1.0}],
            "strength": 0.75, "reliability": 0.85, "reliability_base": 0.85, "reliability_factors": [],
            "direction": "positive",
            "source": {"module": "assessment", "module_version": "0.1.0", "origin": "sandbox",
                       "verification_id": session, "evidence_ref": "top_k_frequent@v1:x"},
            "payload": {"pattern": "top_k_frequent", "pattern_version": 1, "variant_id": "x", "level": "medium",
                        "passed": passed, "total": total, "core": f"{passed}/{total}", "twist": "0/0",
                        "outcome": "passed" if passed == total else "tests_failed", "attempt": 1,
                        "time_used_seconds": 600},
        }],
    }


def graph(*inputs) -> dict:
    """skill -> (lower, mean, upper), from a fresh M6 fed these reports and batches in order."""
    m6 = M6(":memory:")
    for doc in inputs:
        (m6.ingest_report if "claim_graph" in doc else m6.ingest_batch)(doc)
    return {v.skill_id: (round(v.lower, 9), round(v.mean, 9), round(v.upper, 9))
            for v in m6.skills(GOLDEN_SUBJECT, GOLDEN_AS_OF)}


V1 = cv("ver_cv_one", "2026-08-24T09:13:58Z")
V2 = cv("ver_cv_two", "2026-08-24T18:00:00Z")
V2_THIN = cv("ver_cv_two", "2026-08-24T18:00:00Z", without_codeforces=True)


def test_the_same_cv_checked_twice_counts_once():
    """The bug this fixes: every upload of one CV added its evidence again, so the
    ranges narrowed with nothing new learnt."""
    assert graph(V1, V2) == graph(V2) == graph(V1)


def test_a_newer_cv_replaces_the_older_ones_evidence():
    replaced = graph(V1, V2_THIN)
    assert replaced == graph(V2_THIN)
    assert replaced["algorithms"] != graph(V1)["algorithms"], "the Codeforces rating should no longer count"


def test_a_test_result_survives_every_replacement():
    test = assessment_batch("as_one", "2026-08-10T12:00:00Z")
    after = graph(V1, test, V2_THIN)
    assert after == graph(V2_THIN, test), "a fresh replay of what survives: the new CV and the test"
    assert after["algorithms"] != graph(V2_THIN)["algorithms"], "the test still counts"


def test_the_newest_check_wins_however_late_it_arrives():
    m6 = M6(":memory:")
    m6.ingest_report(V2)
    m6.ingest_report(V1)      # an older check, delivered late (a retry)
    assert m6.log.replaced(GOLDEN_SUBJECT) == {"ver_cv_one": {"replaced_by": "ver_cv_two",
                                                              "valid_as_of": utc_instant(V1["valid_as_of"])}}
    assert graph(V2_THIN, V1) == graph(V2_THIN)


def test_instants_compare_whatever_their_spelling():
    """04:30Z written in India's offset is older than 05:00Z, though it sorts later as text."""
    early = cv("ver_cv_early", "2026-11-05T10:00:00.900+05:30", without_codeforces=True)
    late = cv("ver_cv_late", "2026-11-05T05:00:00Z")
    assert utc_instant(early["valid_as_of"]) < utc_instant(late["valid_as_of"])
    assert graph(late, early) == graph(late)


def test_a_failed_check_never_replaces_a_cv_that_worked():
    failed = cv("ver_cv_failed", "2026-08-24T20:00:00Z", status="failed", without_codeforces=True)
    m6 = M6(":memory:")
    m6.ingest_report(V1)
    m6.ingest_report(failed)
    assert m6.log.replaced(GOLDEN_SUBJECT) == {}
    assert graph(V1, failed) == graph(V1)


def test_one_developers_cv_never_replaces_anothers():
    other = cv("ver_cv_other", "2026-08-30T10:00:00Z", subject="subj_someone_else")
    m6 = M6(":memory:")
    m6.ingest_report(V1)
    m6.ingest_report(other)
    assert m6.log.replaced() == {}
    assert graph(V1, other) == graph(V1)


def test_explain_says_what_was_replaced_and_drops_the_old_cvs_suppressions():
    m6 = M6(":memory:")
    m6.ingest_report(V1)
    m6.ingest_report(V2_THIN)
    why = m6.query.explain(GOLDEN_SUBJECT, "algorithms", GOLDEN_AS_OF)["not_counted"]
    gone = [n for n in why if n["reason"].startswith("replaced by a newer CV")]
    assert gone and all("ver_cv_two" in n["reason"] for n in gone)
    fresh = M6(":memory:")
    fresh.ingest_report(V2_THIN)
    kept = [n for n in why if not n["reason"].startswith("replaced by a newer CV")]
    assert kept == fresh.query.explain(GOLDEN_SUBJECT, "algorithms", GOLDEN_AS_OF)["not_counted"]


def test_the_record_is_idempotent_and_permanent():
    m6 = M6(":memory:")
    m6.ingest_report(V1)
    m6.ingest_report(V1)                       # a replay
    m6.log.record_cv("ver_cv_one", GOLDEN_SUBJECT, V1["valid_as_of"])
    db = m6.log._db
    assert db.execute("SELECT COUNT(*) FROM cv_report").fetchone()[0] == 1
    for sql in ("UPDATE cv_report SET valid_as_of = 'x'", "DELETE FROM cv_report"):
        try:
            with db:
                db.execute(sql)
        except sqlite3.IntegrityError as exc:
            assert "append-only" in str(exc)
        else:
            raise AssertionError(f"{sql} was allowed")
