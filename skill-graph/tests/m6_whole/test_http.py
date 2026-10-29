"""The composed HTTP surface, over real sockets.

6.2 and 6.4 each serve their own in deployment; this proves the combined process
routes both without either surface losing a guarantee.
"""
import json
import threading
import urllib.error
import urllib.request

from whole_fixtures import (DEMO_AS_OF, DEMO_SUBJECT, GOLDEN_AS_OF, GOLDEN_SUBJECT,
                            demo_report, loaded, report)
from m6 import serve

AS = GOLDEN_AS_OF.isoformat()


class Server:
    def __init__(self, m6=None):
        self.m6 = m6 or loaded()

    def __enter__(self):
        self.httpd = serve(self.m6, "127.0.0.1", 0)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.m6.close()

    def call(self, method, path, body=None):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())


def test_health_and_versions():
    with Server() as s:
        assert s.call("GET", "/health")[0] == 200
        status, versions = s.call("GET", "/versions")
    assert status == 200 and versions["m6"] == "1.0.0"


def test_a_raw_m5_report_can_be_posted_directly():
    """The seam in one call: project and ingest without the caller running 6.0."""
    with Server(loaded(report())) as s:
        status, body = s.call("POST", "/evidence/report", demo_report())
        assert status == 202 and len(body["accepted"]) > 10
        _, skills = s.call("GET", f"/developers/{DEMO_SUBJECT}/skills"
                                  f"?as_of={DEMO_AS_OF.isoformat()}")
    assert skills["count"] > 8


def test_posting_the_same_report_twice_is_a_no_op():
    with Server() as s:
        status, body = s.call("POST", "/evidence/report", report())
    assert status == 202 and body["replayed"] is True and body["accepted"] == []


def test_a_malformed_report_is_400():
    with Server() as s:
        status, _ = s.call("POST", "/evidence/report", {"not": "a report"})
    assert status == 400


def test_the_query_endpoints_still_work_in_the_combined_process():
    with Server() as s:
        for path in (f"/developers/{GOLDEN_SUBJECT}/skills?as_of={AS}",
                     f"/developers/{GOLDEN_SUBJECT}/skills/typescript/explain?as_of={AS}",
                     f"/search?skill=typescript&as_of={AS}",
                     "/skills"):
            assert s.call("GET", path)[0] == 200, path


def test_the_quarantine_is_visible_in_the_combined_process():
    """What the ontology is missing, for the operator who grows it."""
    with Server(loaded(report())) as s:
        status, body = s.call("GET", "/quarantine")
    assert status == 200
    assert body["count"] == len(body["quarantined"]) and body["ontology_version"]
    assert all(isinstance(skills, list) for skills in body["quarantined"].values())


def test_the_integrity_endpoint_reports_findings():
    with Server() as s:
        status, body = s.call("GET", f"/developers/{GOLDEN_SUBJECT}/integrity?as_of={AS}")
    assert status == 200
    assert body["counts"]["attention"] + body["counts"]["notice"] == len(body["findings"])
    assert "No score below is changed" in body["note"]


def test_the_profile_endpoint_returns_skills_and_integrity_together():
    with Server() as s:
        status, body = s.call("GET", f"/developers/{GOLDEN_SUBJECT}/profile?as_of={AS}")
    assert status == 200 and body["skills"] and body["integrity"]


def test_the_aggregate_refusal_survives_composition():
    """A guarantee made by 6.4 must not be lost by wiring it into a bigger app."""
    with Server() as s:
        for name in ("score", "trust", "overall", "rating"):
            status, body = s.call("GET", f"/developers/{GOLDEN_SUBJECT}/{name}")
            assert status == 400 and body["error"] == "AggregateRefused", name


def test_an_unknown_route_is_404():
    with Server() as s:
        assert s.call("GET", "/nope")[0] == 404


def test_posting_to_a_get_only_route_is_404_not_a_crash():
    with Server() as s:
        assert s.call("POST", "/health", {})[0] == 404


def test_concurrent_readers_and_one_writer_do_not_collide():
    with Server(loaded(report())) as s:
        errors, results = [], []
        start = threading.Barrier(9)

        def read():
            start.wait()
            try:
                results.append(s.call("GET", f"/developers/{GOLDEN_SUBJECT}/profile?as_of={AS}"))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def write():
            start.wait()
            try:
                results.append(s.call("POST", "/evidence/report", demo_report()))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=read) for _ in range(8)]
        threads.append(threading.Thread(target=write))
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

    assert not errors, f"concurrent access raised: {errors}"
    assert all(status in (200, 202) for status, _ in results)


def test_a_confirmed_job_shortlists_over_http():
    """POST a job's confirmed requirements, get who clears every must-have."""
    req = {"schema_version": "1.0.0", "job_id": "job_h", "confirmed_at": "2026-08-24T00:00:00+00:00",
           "confirmed_by": "recruiter", "skill_list_version": "0.3.0",
           "must": [{"skill_id": "typescript", "bar": 0.0}], "nice": ["cpp"]}
    with Server(loaded(report())) as s:
        status, body = s.call("POST", f"/shortlist?as_of={AS}", req)
        assert status == 200 and body["qualified"] == 1
        assert body["candidates"][0]["subject_ref"] == GOLDEN_SUBJECT
        bad_status, bad = s.call("POST", "/shortlist", {"job_id": "x"})
        _, applicants = s.call("POST", f"/shortlist?as_of={AS}&subject={GOLDEN_SUBJECT}&subject=subj_nobody", req)
    assert bad_status == 400 and bad["error"] == "BadRequirements"
    assert [c["subject_ref"] for c in applicants["candidates"]] == [GOLDEN_SUBJECT]
    assert applicants["no_evidence"] == ["subj_nobody"] and applicants["others"] == []
