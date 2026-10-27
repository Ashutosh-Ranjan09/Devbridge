"""Sessions and storage: one task per candidate, deadlines, and results that never change."""

from __future__ import annotations

import datetime
import sqlite3

import pytest

from assess import sessions
from assess.models import Outcome, SandboxInfo, SessionStatus
from assess.patterns import load
from assess.sandbox import Run
from assess.sessions import SessionError, start, submit
from assess.store import Store
from tests.test_sandbox import rows

T = datetime.datetime(2026, 10, 26, 10, 0, tzinfo=datetime.UTC)
INFO = SandboxInfo(image="assess-python:3.12", wall_seconds=0.4, exit_code=0)


@pytest.fixture
def store(tmp_path) -> Store:
    return Store(tmp_path / "assess.db")


@pytest.fixture
def sandbox(monkeypatch: pytest.MonkeyPatch):
    """A stand-in sandbox: no Docker, and the outcome a test chooses."""
    state = {"run": Run(Outcome.PASSED, rows(), INFO)}
    monkeypatch.setattr(sessions, "run_candidate", lambda pattern, params, source: state["run"])
    return state


class TestStarting:
    def test_starting_again_returns_the_task_already_issued(self, store) -> None:
        """Otherwise a candidate could refresh until an easier-looking variant appeared."""
        a, va = start(store, "rate_limiter", "subject:asha", seed=1, now=T)
        b, vb = start(store, "rate_limiter", "subject:asha", seed=99, now=T)
        assert a.session_id == b.session_id and va.variant_id == vb.variant_id

    def test_two_candidates_for_one_job_never_get_the_same_task(self, store) -> None:
        _, va = start(store, "rate_limiter", "subject:asha", job_id="job_1", seed=1, now=T)
        _, vb = start(store, "rate_limiter", "subject:ravi", job_id="job_1", seed=1, now=T)
        assert va.variant_id != vb.variant_id

    def test_the_deadline_is_the_pattern_s_time_limit(self, store) -> None:
        s, v = start(store, "rate_limiter", "subject:asha", seed=1, now=T)
        assert s.deadline - s.started_at == datetime.timedelta(minutes=v.time_limit_minutes)


class TestSubmitting:
    def test_a_scored_result_is_stored_with_the_code_it_scored(self, store, sandbox) -> None:
        s, _ = start(store, "rate_limiter", "subject:asha", seed=1, now=T)
        result = submit(store, s.session_id, "print('mine')", now=T + datetime.timedelta(minutes=20))
        assert result.scored and store.result(s.session_id) == result
        assert store.submission(s.session_id) == "print('mine')"
        assert store.session(s.session_id).status is SessionStatus.SUBMITTED

    def test_one_submission_per_session(self, store, sandbox) -> None:
        s, _ = start(store, "rate_limiter", "subject:asha", seed=1, now=T)
        submit(store, s.session_id, "x", now=T)
        with pytest.raises(SessionError, match="one submission"):
            submit(store, s.session_id, "x", now=T)

    def test_late_is_refused_not_scored(self, store, sandbox) -> None:
        s, _ = start(store, "rate_limiter", "subject:asha", seed=1, now=T)
        with pytest.raises(SessionError, match="refused, not scored"):
            submit(store, s.session_id, "x", now=s.deadline + datetime.timedelta(minutes=5))
        assert store.result(s.session_id) is None
        assert store.session(s.session_id).status is SessionStatus.EXPIRED

    def test_within_the_grace_period_is_scored(self, store, sandbox) -> None:
        s, _ = start(store, "rate_limiter", "subject:asha", seed=1, now=T)
        assert submit(store, s.session_id, "x", now=s.deadline + datetime.timedelta(seconds=60)).scored

    def test_an_unavailable_sandbox_leaves_the_session_open(self, store, sandbox) -> None:
        """Nothing was measured, so the candidate may submit again."""
        sandbox["run"] = Run(Outcome.SANDBOX_UNAVAILABLE, [], INFO, "daemon down")
        s, _ = start(store, "rate_limiter", "subject:asha", seed=1, now=T)
        assert not submit(store, s.session_id, "x", now=T).scored
        assert store.result(s.session_id) is None
        assert store.session(s.session_id).status is SessionStatus.OPEN

    def test_a_changed_pattern_does_not_score_an_old_task(self, store, sandbox, monkeypatch) -> None:
        s, _ = start(store, "rate_limiter", "subject:asha", seed=1, now=T)
        bumped = load("rate_limiter").model_copy(update={"version": 2})
        monkeypatch.setattr(sessions, "load", lambda pattern_id: bumped)
        with pytest.raises(SessionError, match="not the ones on disk"):
            submit(store, s.session_id, "x", now=T)


class TestResultsNeverChange:
    def test_the_database_refuses_to_alter_a_result(self, store, sandbox) -> None:
        s, _ = start(store, "rate_limiter", "subject:asha", seed=1, now=T)
        submit(store, s.session_id, "x", now=T)
        with pytest.raises(sqlite3.IntegrityError, match="never changed"):
            store.db.execute("UPDATE results SET doc = '{}'")
        with pytest.raises(sqlite3.IntegrityError, match="never deleted"):
            store.db.execute("DELETE FROM results")


class TestStartingFromAJob:
    def _job(self, store, *, confirmed: bool = True):
        from assess.jd import confirm, edit, extract

        job = edit(extract("Strong Python is required. Protect our login endpoint.", None),
                   must={"python": 0.3, "rate_limiting": 0.2})
        job = confirm(job, "recruiter") if confirmed else job
        store.save_job(job)
        return job

    def test_one_task_per_assessable_must_have_and_the_rest_reported(self, store) -> None:
        from assess.sessions import start_for_job

        job = self._job(store)
        issued, missing = start_for_job(store, job.job_id, "subject:asha", now=T)
        assert [v.pattern_id for _, v in issued] == ["rate_limiter"]
        assert missing == ["python"], "a must-have nobody can assess is said, not skipped"
        assert issued[0][0].job_id == job.job_id

    def test_an_unconfirmed_job_issues_nothing(self, store) -> None:
        from assess.sessions import start_for_job

        job = self._job(store, confirmed=False)
        with pytest.raises(SessionError, match="not confirmed"):
            start_for_job(store, job.job_id, "subject:asha", now=T)

    def test_the_job_s_text_is_the_model_s_context(self, store) -> None:
        from assess.sessions import start_for_job
        from tests.test_variants import FakeModel

        job = self._job(store)
        model = FakeModel({"params": {"key_kind": "user_email", "limit": 5, "window": 900,
                                      "twist": "retry_after"}, "story": "A login page under attack."})
        ((_, variant),) = start_for_job(store, job.job_id, "subject:asha", provider=model, now=T)[0]
        assert variant.chosen_by == "model" and variant.params["key_kind"] == "user_email"
