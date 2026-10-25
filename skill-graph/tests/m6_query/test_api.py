"""The HTTP surface, over real sockets."""
import json
import threading
import urllib.error
import urllib.request

from query_fixtures import AS_OF, SUBJECT, population, service, walk
from m6_query import serve
from test_constraints import BANNED_KEYS

AS = AS_OF.isoformat()


class Server:
    def __init__(self, svc=None):
        self.service = svc or population()

    def __enter__(self):
        self.httpd = serve(self.service, "127.0.0.1", 0)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())


def test_health_reports_the_population_and_parameters():
    with Server() as s:
        status, body = s.get("/health")
    assert status == 200 and body["subjects"] == 4
    assert body["parameter_version"] == "1.0.0"


def test_the_skills_catalogue_lists_the_ontology_with_half_lives():
    with Server() as s:
        status, body = s.get("/skills")
    assert status == 200 and body["count"] > 10
    row = next(r for r in body["skills"] if r["skill_id"] == "typescript")
    assert row["volatility_tier"] == "ecosystem" and row["half_life_days"] == 1167


def test_a_developers_graph_comes_back_with_intervals():
    with Server() as s:
        status, body = s.get(f"/developers/{SUBJECT}/skills?as_of={AS}")
    assert status == 200 and body["count"] > 0
    assert all(len(row["interval"]) == 2 for row in body["skills"])
    assert "no overall score" in body["note"]


def test_the_graph_can_exclude_inferred_skills():
    with Server() as s:
        _, everything = s.get(f"/developers/{SUBJECT}/skills?as_of={AS}")
        _, direct = s.get(f"/developers/{SUBJECT}/skills?as_of={AS}&include_inferred=false")
    assert direct["count"] < everything["count"]
    assert all(row["evidence_count"] > 0 for row in direct["skills"])


def test_propagation_can_be_turned_off_over_http():
    with Server() as s:
        _, on = s.get(f"/developers/{SUBJECT}/skills?as_of={AS}")
        _, off = s.get(f"/developers/{SUBJECT}/skills?as_of={AS}&propagate=0")
    assert off["count"] < on["count"]


def test_explain_returns_the_full_response():
    with Server() as s:
        status, body = s.get(f"/developers/{SUBJECT}/skills/typescript/explain?as_of={AS}")
    assert status == 200
    for field in ("score", "interval", "mean", "sigma", "contributions",
                  "not_counted", "basis", "parameter_version"):
        assert field in body, field


def test_explain_for_an_unknown_skill_is_404():
    with Server() as s:
        status, body = s.get(f"/developers/{SUBJECT}/skills/haskell/explain?as_of={AS}")
    assert status == 404 and body["error"] == "UnknownSkill"


def test_an_unknown_subject_is_404():
    with Server() as s:
        status, body = s.get(f"/developers/subj_nobody/skills?as_of={AS}")
    assert status == 404 and body["error"] == "UnknownSubject"


def test_search_returns_tiers_with_an_explanatory_note():
    with Server() as s:
        status, body = s.get(f"/search?skill=typescript&min=0.0&as_of={AS}")
    assert status == 200
    assert "tiers" in body and "not a ranking" in body["note"]
    assert body["tier_count"] == len(body["tiers"])


def test_search_reports_which_matching_rule_was_used():
    with Server() as s:
        _, strict = s.get(f"/search?skill=typescript&min=0.4&as_of={AS}")
        _, loose = s.get(f"/search?skill=typescript&min=0.4&definite=false&as_of={AS}")
    assert "whole interval" in strict["match"]
    assert "reaches" in loose["match"]


def test_search_without_a_skill_is_400():
    with Server() as s:
        status, body = s.get("/search")
    assert status == 400 and "skill" in body["detail"]


def test_a_bad_as_of_is_400_not_a_crash():
    with Server() as s:
        status, body = s.get(f"/developers/{SUBJECT}/skills?as_of=last-tuesday")
    assert status == 400
    assert "YYYY-MM-DD" in body["detail"]


def test_a_bad_numeric_parameter_is_400():
    with Server() as s:
        status, _ = s.get("/search?skill=typescript&min=lots")
    assert status == 400


def test_asking_for_an_overall_score_is_400_with_a_reason():
    """The constraint, enforced at the edge. Four spellings, one answer."""
    with Server() as s:
        for name in ("score", "rating", "trust", "overall"):
            status, body = s.get(f"/developers/{SUBJECT}/{name}")
            assert status == 400, name
            assert body["error"] == "AggregateRefused"
            assert "no overall score" in body["detail"]


def test_no_endpoint_leaks_an_aggregate_field():
    paths = ["/health", "/skills", f"/developers/{SUBJECT}/skills?as_of={AS}",
             f"/developers/{SUBJECT}/skills/typescript/explain?as_of={AS}",
             f"/search?skill=typescript&as_of={AS}"]
    with Server() as s:
        for path in paths:
            _, body = s.get(path)
            for key, _ in walk(body):
                assert key not in BANNED_KEYS, f"{key!r} leaked from {path}"


def test_an_unknown_route_is_404():
    with Server() as s:
        status, body = s.get("/nope")
    assert status == 404 and body["error"] == "not_found"


def test_a_trailing_slash_routes_the_same():
    with Server() as s:
        assert s.get(f"/developers/{SUBJECT}/skills/?as_of={AS}")[0] == 200


def test_concurrent_reads_do_not_collide():
    """The scoring engine holds no state between calls and the log serialises
    its own access, but the server is threaded, so this is worth proving."""
    with Server() as s:
        results, errors = [], []
        start = threading.Barrier(8)

        def hit():
            start.wait()
            try:
                results.append(s.get(f"/developers/{SUBJECT}/skills/typescript/explain?as_of={AS}"))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=hit) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

    assert not errors, f"concurrent reads raised: {errors}"
    assert all(status == 200 for status, _ in results)
    scores = {body["score"] for _, body in results}
    assert len(scores) == 1, f"the same query returned different scores: {scores}"
