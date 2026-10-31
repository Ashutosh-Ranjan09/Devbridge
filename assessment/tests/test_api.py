"""The HTTP surface: the CLI's rules hold over HTTP, and a candidate never sees more
than the candidate view."""

from __future__ import annotations

import datetime
import json
from collections.abc import Iterator

import jsonschema
import pytest
from fastapi.testclient import TestClient

from assess import api, junit, sessions
from assess.config import REPO
from assess.models import Outcome
from assess.sandbox import Run
from assess.store import Store
from tests.test_jd import JD
from tests.test_sandbox import rows
from tests.test_sessions import INFO

KEY = {"Authorization": f"Bearer {api.API_KEY}"}


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
    def temporary() -> Iterator[Store]:
        s = Store(tmp_path / "assess.db")
        try:
            yield s
        finally:
            s.db.close()

    api.app.dependency_overrides[api.store] = temporary
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


@pytest.fixture
def sandbox(monkeypatch: pytest.MonkeyPatch) -> dict[str, Run]:
    """No Docker: the outcome a test chooses (as in test_sessions)."""
    state = {"run": Run(Outcome.TESTS_FAILED, rows({"exact_boundary"}), INFO),
             "examples": Run(Outcome.TESTS_FAILED, [
                 junit.CaseResult("example_within_the_limit", "c", True, None),
                 junit.CaseResult("example_over_the_limit", "c", False,
                                  "AssertionError: request 11 inside the window: got 200, expected 429")], INFO)}
    monkeypatch.setattr(sessions, "run_candidate", lambda pattern, params, source, suite="hidden": state["examples" if suite == "visible" else "run"])
    return state


def confirmed_job(client: TestClient) -> str:
    job = client.post("/v1/jobs", json={"text": JD, "model": False}, headers=KEY).json()
    client.patch(f"/v1/jobs/{job['job_id']}", json={"must": {"rate_limiting": None}}, headers=KEY)
    r = client.post(f"/v1/jobs/{job['job_id']}/confirm", json={"by": "A. Recruiter"}, headers=KEY)
    assert r.status_code == 200, r.text
    return str(job["job_id"])


def task(client: TestClient) -> str:
    r = client.post("/v1/sessions", json={"candidate_ref": "subject:asha",
                                          "pattern_id": "rate_limiter"}, headers=KEY)
    assert r.status_code == 200, r.text
    return str(r.json()["tasks"][0]["session_id"])


def test_a_store_opened_on_one_thread_closes_on_another(tmp_path) -> None:
    """What FastAPI does with a request's Store: setup and teardown on different worker
    threads. sqlite3's default refuses the close, and the request became a 500."""
    import threading

    opened: list[Store] = []
    t = threading.Thread(target=lambda: opened.append(Store(tmp_path / "assess.db")))
    t.start()
    t.join()
    opened[0].jobs()
    opened[0].db.close()


class TestTheKey:
    def test_every_endpoint_but_health_needs_it(self, client) -> None:
        assert client.get("/v1/patterns").status_code == 401
        assert client.get("/v1/patterns", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.get("/healthz").status_code == 200

    def test_errors_have_one_shape(self, client) -> None:
        r = client.get("/v1/patterns")
        assert set(r.json()) == {"error", "detail"}
        r = client.post("/v1/jobs", json={"text": ""}, headers=KEY)
        assert r.status_code == 422 and r.json()["error"] == "invalid_request"


class TestJobs:
    def test_propose_edit_confirm_export(self, client) -> None:
        """The CLI's walk, over HTTP; the export is what M6's shortlist reads."""
        job_id = confirmed_job(client)
        doc = client.get(f"/v1/jobs/{job_id}/requirements", headers=KEY).json()
        schema = json.loads((REPO / "schemas" / "job-requirements.schema.json").read_text())
        jsonschema.validate(doc, schema)
        assert "rate_limiting" in {m["skill_id"] for m in doc["must"]}

    def test_a_confirmed_job_is_never_edited(self, client) -> None:
        job_id = confirmed_job(client)
        r = client.patch(f"/v1/jobs/{job_id}", json={"drop": ["rate_limiting"]}, headers=KEY)
        assert r.status_code == 409 and "never edited" in r.json()["detail"]

    def test_a_bar_outside_0_to_1_is_refused(self, client) -> None:
        """Refused before jd.edit, which refuses it too (the CLI's path)."""
        job = client.post("/v1/jobs", json={"text": JD, "model": False}, headers=KEY).json()
        r = client.patch(f"/v1/jobs/{job['job_id']}", json={"must": {"rate_limiting": 5}}, headers=KEY)
        assert r.status_code == 422

    def test_an_unconfirmed_job_has_no_requirements(self, client) -> None:
        job = client.post("/v1/jobs", json={"text": JD, "model": False}, headers=KEY).json()
        assert client.get(f"/v1/jobs/{job['job_id']}/requirements", headers=KEY).status_code == 409

    def test_an_unknown_job_is_404(self, client) -> None:
        assert client.get("/v1/jobs/job_nope", headers=KEY).status_code == 404


class TestTasks:
    def test_a_task_shows_nothing_a_candidate_could_fit_to(self, client) -> None:
        """No hidden tests, no seed, no parameters — only what the task says."""
        r = client.get(f"/v1/sessions/{task(client)}", headers=KEY).json()
        assert set(r) == set(api.Task.model_fields)
        assert "seed" not in r and "params" not in r and "tests_hidden" not in json.dumps(r)

    def test_asking_again_returns_the_same_task(self, client) -> None:
        assert task(client) == task(client)

    def test_a_job_issues_one_task_per_assessable_must_have(self, client) -> None:
        job_id = confirmed_job(client)
        r = client.post("/v1/sessions", json={"candidate_ref": "subject:asha", "job_id": job_id,
                                              "model": False}, headers=KEY).json()
        assert [t["skill"] for t in r["tasks"]] == ["rate_limiting"]

    def test_a_job_s_task_is_withheld_until_the_candidate_starts_it(self, client) -> None:
        job_id = confirmed_job(client)
        t = client.post("/v1/sessions", json={"candidate_ref": "subject:asha", "job_id": job_id,
                                              "model": False}, headers=KEY).json()["tasks"][0]
        assert t["status"] == "issued" and t["start_by"] and t["deadline"] is None
        assert t["story"] is None and t["requirements"] is None and t["starter"] is None
        b = client.post(f"/v1/sessions/{t['session_id']}/begin", headers=KEY).json()
        assert b["status"] == "open" and b["deadline"] and b["story"] and b["starter"]

    def test_a_chosen_start_by_is_kept_and_a_past_one_refused(self, client) -> None:
        job_id = confirmed_job(client)
        when = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=3)).isoformat()
        t = client.post("/v1/sessions", json={"candidate_ref": "subject:asha", "job_id": job_id, "model": False,
                                              "start_by": when}, headers=KEY).json()["tasks"][0]
        assert datetime.datetime.fromisoformat(t["start_by"]) == datetime.datetime.fromisoformat(when)
        r = client.post("/v1/sessions", json={"candidate_ref": "subject:ravi", "job_id": job_id, "model": False,
                                              "start_by": "2020-01-01T00:00:00Z"}, headers=KEY)
        assert r.status_code == 409 and "already passed" in r.json()["detail"]

    def test_start_by_is_for_a_job_s_tasks_only(self, client) -> None:
        r = client.post("/v1/sessions", json={"candidate_ref": "s", "pattern_id": "rate_limiter",
                                              "start_by": "2030-01-01T00:00:00Z"}, headers=KEY)
        assert r.status_code == 422

    def test_job_or_pattern_not_both(self, client) -> None:
        r = client.post("/v1/sessions", json={"candidate_ref": "s", "job_id": "j",
                                              "pattern_id": "rate_limiter"}, headers=KEY)
        assert r.status_code == 422

    def test_an_unknown_pattern_is_404(self, client) -> None:
        r = client.post("/v1/sessions", json={"candidate_ref": "s", "pattern_id": "nope"}, headers=KEY)
        assert r.status_code == 404


class TestSubmitting:
    def test_the_candidate_sees_which_tests_failed_not_why(self, client, sandbox) -> None:
        session_id = task(client)
        r = client.post(f"/v1/sessions/{session_id}/submit", json={"code": "x = 1"}, headers=KEY)
        assert r.status_code == 200
        assert (r.json()["attempt"], r.json()["final"], r.json()["attempts_left"]) == (1, False, 2)
        failed = [t for t in r.json()["tests"] if not t["passed"]]
        assert [t["name"] for t in failed] == ["exact_boundary"]
        assert "detail" not in failed[0] and "broke" not in r.text   # the detail is "exact_boundary broke"
        mine = client.get(f"/v1/sessions/{session_id}/attempts", headers=KEY).json()
        assert "broke" not in json.dumps(mine) and mine["counted"] is None
        full = client.get(f"/v1/sessions/{session_id}/attempts?view=full", headers=KEY).json()
        assert "exact_boundary broke" in json.dumps(full)

    def test_the_result_waits_for_the_session_to_be_final(self, client, sandbox) -> None:
        session_id = task(client)
        client.post(f"/v1/sessions/{session_id}/submit", json={"code": "x = 1"}, headers=KEY)
        assert client.get(f"/v1/sessions/{session_id}/result", headers=KEY).status_code == 404
        assert client.get(f"/v1/sessions/{session_id}/events", headers=KEY).status_code == 404
        assert client.post(f"/v1/sessions/{session_id}/finish", headers=KEY).status_code == 200
        r = client.get(f"/v1/sessions/{session_id}/result", headers=KEY).json()
        assert set(r) == set(api.CandidateResult.model_fields) and r["attempt"] == 1
        assert client.get(f"/v1/sessions/{session_id}/attempts", headers=KEY).json()["counted"] == 1

    def test_three_attempts_then_final(self, client, sandbox) -> None:
        session_id = task(client)
        answers = [client.post(f"/v1/sessions/{session_id}/submit", json={"code": f"x = {n}"}, headers=KEY).json()
                   for n in (1, 2, 3)]
        assert [(a["attempt"], a["final"], a["attempts_left"]) for a in answers] == [(1, False, 2), (2, False, 1), (3, True, 0)]
        r = client.post(f"/v1/sessions/{session_id}/submit", json={"code": "x = 4"}, headers=KEY)
        assert r.status_code == 409
        assert client.get(f"/v1/sessions/{session_id}", headers=KEY).json()["attempts_used"] == 3

    def test_code_that_does_not_parse_is_422_and_uses_no_attempt(self, client, sandbox) -> None:
        session_id = task(client)
        r = client.post(f"/v1/sessions/{session_id}/submit", json={"code": "x = (\n"}, headers=KEY)
        assert r.status_code == 422 and r.json()["error"] == "syntax_error" and "line" in r.json()["detail"]
        assert client.get(f"/v1/sessions/{session_id}", headers=KEY).json()["attempts_used"] == 0

    def test_run_shows_each_example_with_what_it_expected(self, client, sandbox) -> None:
        session_id = task(client)
        r = client.post(f"/v1/sessions/{session_id}/run", json={"code": "x = 1"}, headers=KEY).json()
        got = {e["name"]: (e["passed"], e["detail"]) for e in r["examples"]}
        assert got["example_within_the_limit"] == (True, None)
        assert got["example_over_the_limit"] == (False, "request 11 inside the window: got 200, expected 429")
        assert got["example_twist"][0] is False, "an example that did not run is shown, not dropped"
        assert client.get(f"/v1/sessions/{session_id}", headers=KEY).json()["attempts_used"] == 0

    def test_an_unrunnable_submission_is_not_a_score(self, client, sandbox) -> None:
        """Guardrail 4 over HTTP: 503, the session stays open, no result, no evidence."""
        sandbox["run"] = Run(Outcome.SANDBOX_UNAVAILABLE, [], INFO, "docker is not installed")
        session_id = task(client)
        r = client.post(f"/v1/sessions/{session_id}/submit", json={"code": "x = 1"}, headers=KEY)
        assert r.status_code == 503 and "docker is not installed" in r.json()["detail"]
        assert client.get(f"/v1/sessions/{session_id}", headers=KEY).json()["status"] == "open"
        assert client.get(f"/v1/sessions/{session_id}/result", headers=KEY).status_code == 404

    def test_events_are_a_valid_batch_for_m6(self, client, sandbox) -> None:
        session_id = task(client)
        client.post(f"/v1/sessions/{session_id}/submit", json={"code": "x = 1"}, headers=KEY)
        client.post(f"/v1/sessions/{session_id}/finish", headers=KEY)
        doc = client.get(f"/v1/sessions/{session_id}/events", headers=KEY).json()
        schema = json.loads((REPO / "schemas" / "evidence-event.schema.json").read_text())
        jsonschema.validate(doc, schema)
        assert doc["subject_ref"] == "subject:asha"
