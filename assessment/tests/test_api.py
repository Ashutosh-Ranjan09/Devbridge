"""The HTTP surface: the CLI's rules hold over HTTP, and a candidate never sees more
than the candidate view."""

from __future__ import annotations

import json
from collections.abc import Iterator

import jsonschema
import pytest
from fastapi.testclient import TestClient

from assess import api, sessions
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
    state = {"run": Run(Outcome.TESTS_FAILED, rows({"exact_boundary"}), INFO)}
    monkeypatch.setattr(sessions, "run_candidate", lambda pattern, params, source: state["run"])
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
        failed = [t for t in r.json()["tests"] if not t["passed"]]
        assert [t["name"] for t in failed] == ["exact_boundary"]
        assert "detail" not in failed[0] and "broke" not in r.text   # the detail is "exact_boundary broke"
        full = client.get(f"/v1/sessions/{session_id}/result?view=full", headers=KEY).json()
        assert "exact_boundary broke" in json.dumps(full)

    def test_the_default_result_is_the_candidate_view(self, client, sandbox) -> None:
        session_id = task(client)
        client.post(f"/v1/sessions/{session_id}/submit", json={"code": "x = 1"}, headers=KEY)
        r = client.get(f"/v1/sessions/{session_id}/result", headers=KEY).json()
        assert set(r) == set(api.CandidateResult.model_fields)

    def test_one_submission_per_session(self, client, sandbox) -> None:
        session_id = task(client)
        client.post(f"/v1/sessions/{session_id}/submit", json={"code": "x = 1"}, headers=KEY)
        r = client.post(f"/v1/sessions/{session_id}/submit", json={"code": "x = 2"}, headers=KEY)
        assert r.status_code == 409

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
        doc = client.get(f"/v1/sessions/{session_id}/events", headers=KEY).json()
        schema = json.loads((REPO / "schemas" / "evidence-event.schema.json").read_text())
        jsonschema.validate(doc, schema)
        assert doc["subject_ref"] == "subject:asha"
