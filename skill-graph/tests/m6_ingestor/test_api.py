"""The HTTP surface, exercised over a real socket.

A handler tested by calling its methods directly proves very little; these start
the actual server and speak HTTP to it, so routing, status codes and body
handling are all in scope.
"""
import json
import threading
import urllib.error
import urllib.request

from fixtures import batch, ingestor, mutate_event
from m6_ingestor import EventLog, Ingestor, serve
from m6_ontology import AcceptAll, default_ontology


class Server:
    """Starts the ingestor on an ephemeral port for the duration of a `with`."""

    def __init__(self, ing=None):
        self.ingestor = ing or Ingestor(EventLog(":memory:"), ontology=AcceptAll())

    def __enter__(self):
        self.httpd = serve(self.ingestor, "127.0.0.1", 0)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def request(self, method, path, body=None):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())


def test_health_reports_liveness_and_the_ontology_in_force():
    with Server() as s:
        status, body = s.request("GET", "/health")
    assert status == 200
    assert body["status"] == "ok" and body["events"] == 0
    assert body["ontology_version"] == "accept-all"


def test_posting_a_batch_returns_202_and_a_receipt():
    with Server() as s:
        status, body = s.request("POST", "/evidence/batch", batch())
    assert status == 202
    assert len(body["accepted"]) == 8
    assert body["replayed"] is False


def test_replaying_over_http_is_a_no_op():
    with Server() as s:
        s.request("POST", "/evidence/batch", batch())
        status, body = s.request("POST", "/evidence/batch", batch())
        _, health = s.request("GET", "/health")
    assert status == 202, "a replay is a success, not an error"
    assert body["replayed"] is True and body["accepted"] == []
    assert health["events"] == 8


def test_a_schema_failure_is_400():
    with Server() as s:
        status, body = s.request("POST", "/evidence/batch", mutate_event(batch(), kind="x"))
    assert status == 400
    assert body["error"] == "SchemaInvalid"


def test_a_content_conflict_is_409():
    with Server() as s:
        s.request("POST", "/evidence/batch", batch())
        status, body = s.request("POST", "/evidence/batch",
                                 mutate_event(batch(), strength=0.99))
    assert status == 409
    assert body["error"] == "ConflictingEvent"


def test_malformed_json_is_400_not_a_crash():
    with Server() as s:
        url = f"http://127.0.0.1:{s.port}/evidence/batch"
        req = urllib.request.Request(url, data=b"{not json", method="POST")
        try:
            urllib.request.urlopen(req, timeout=10)
            raise AssertionError("malformed JSON was accepted")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            assert json.loads(exc.read())["error"] == "malformed_json"


def test_an_empty_body_is_400():
    with Server() as s:
        url = f"http://127.0.0.1:{s.port}/evidence/batch"
        req = urllib.request.Request(url, data=b"", method="POST")
        try:
            urllib.request.urlopen(req, timeout=10)
            raise AssertionError("an empty body was accepted")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400


def test_an_unknown_route_is_404():
    with Server() as s:
        status, body = s.request("GET", "/nope")
    assert status == 404 and body["error"] == "not_found"


def test_events_are_served_in_fold_order():
    with Server() as s:
        s.request("POST", "/evidence/batch", batch())
        status, body = s.request("GET", "/events")
    assert status == 200 and body["count"] == 8
    keys = [(e["occurred_at"], e["event_id"]) for e in body["events"]]
    assert keys == sorted(keys)


def test_events_can_be_filtered_by_skill_and_subject():
    with Server() as s:
        s.request("POST", "/evidence/batch", batch())
        _, by_skill = s.request("GET", "/events?skill=typescript")
        _, by_subject = s.request("GET", f"/events?subject={batch()['subject_ref']}")
        _, nobody = s.request("GET", "/events?subject=subj_nobody")
    assert 0 < by_skill["count"] < 8
    assert by_subject["count"] == 8
    assert nobody["count"] == 0


def test_the_quarantine_endpoint_reports_held_skills():
    ing = Ingestor(EventLog(":memory:"), ontology=default_ontology())
    doc = batch()
    doc["events"][0]["skill_refs"] = [{"skill_id": "quantum_telepathy", "relevance": 0.9}]
    with Server(ing) as s:
        s.request("POST", "/evidence/batch", doc)
        status, body = s.request("GET", "/quarantine")
    assert status == 200 and body["count"] == 1
    assert list(body["quarantined"].values())[0] == ["quantum_telepathy"]


def test_batches_are_listed_with_their_suppressions():
    with Server() as s:
        s.request("POST", "/evidence/batch", batch())
        status, body = s.request("GET", "/batches")
    assert status == 200 and body["count"] == 1
    assert json.loads(body["batches"][0]["not_emitted"]) == batch()["not_emitted"]


def test_a_trailing_slash_routes_the_same():
    with Server() as s:
        assert s.request("GET", "/health/")[0] == 200


def test_concurrent_posts_of_the_same_batch_store_one_copy():
    """The server is threaded, so this is the real race: eight clients POST the
    same batch at once. Without a lock around the transaction, two of them
    interleave and the log ends up with a partial or doubled batch."""
    with Server() as s:
        results, errors = [], []
        start = threading.Barrier(8)

        def post():
            start.wait()
            try:
                results.append(s.request("POST", "/evidence/batch", batch()))
            except Exception as exc:  # noqa: BLE001 - the test is what it means
                errors.append(exc)

        threads = [threading.Thread(target=post) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        _, health = s.request("GET", "/health")

    assert not errors, f"concurrent posts raised: {errors}"
    assert health["events"] == 8, f"expected 8 events, log holds {health['events']}"
    accepted = sum(len(body["accepted"]) for _, body in results)
    assert accepted == 8, f"{accepted} events accepted across 8 racing clients"
    assert all(status == 202 for status, _ in results)


def test_concurrent_posts_of_different_batches_all_land():
    """The lock must serialise writers, not lose them."""
    with Server() as s:
        start = threading.Barrier(4)

        def post(n):
            doc = batch()
            doc["batch_id"] = f"evb_parallel_{n}"
            for i, event in enumerate(doc["events"]):
                event["event_id"] = f"ev_p{n}_{i:03d}"
            start.wait()
            s.request("POST", "/evidence/batch", doc)

        threads = [threading.Thread(target=post, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        _, health = s.request("GET", "/health")
        _, batches = s.request("GET", "/batches")

    assert health["events"] == 32
    assert batches["count"] == 4
