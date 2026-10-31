"""Sessions and storage: one task per candidate, deadlines, and results that never change."""

from __future__ import annotations

import datetime
import json
import sqlite3

import pytest

from assess import sessions
from assess.models import Outcome, SandboxInfo, Session, SessionStatus
from assess.patterns import load
from assess.sandbox import Run
from assess.scoring import standings, task_points, totals
from assess.sessions import (
    NotPythonError,
    SessionError,
    begin,
    current,
    finish,
    run_examples,
    start,
    submit,
)
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
    state = {"run": Run(Outcome.PASSED, rows(), INFO), "examples": Run(Outcome.PASSED, [], INFO)}
    monkeypatch.setattr(sessions, "run_candidate", lambda pattern, params, source, suite="hidden": state["examples" if suite == "visible" else "run"])
    return state


class TestStarting:
    def test_starting_again_returns_the_task_already_issued(self, store) -> None:
        """Otherwise a candidate could refresh until an easier-looking variant appeared."""
        a, va = start(store, "rate_limiter", "subject:asha", seed=1, now=T)
        b, vb = start(store, "rate_limiter", "subject:asha", seed=99, now=T)
        assert a.session_id == b.session_id and va.variant_id == vb.variant_id

    def test_two_requests_at_once_get_one_task(self, store, monkeypatch) -> None:
        """A double click, or two tabs: both find no task and both make one. The second
        is handed the first's session, not a server error, and leaves no variant behind."""
        a, va = start(store, "rate_limiter", "subject:asha", job_id="job_1", seed=1, now=T)
        real, calls = store.existing_session, []

        def raced(*args):  # the check ran before the first request had saved its task
            calls.append(args)
            return None if len(calls) == 1 else real(*args)

        monkeypatch.setattr(store, "existing_session", raced)
        variants = store.db.execute("SELECT COUNT(*) FROM variants").fetchone()[0]
        b, vb = start(store, "rate_limiter", "subject:asha", job_id="job_1", seed=2, now=T)
        assert (b.session_id, vb.variant_id) == (a.session_id, va.variant_id)
        assert store.db.execute("SELECT COUNT(*) FROM variants").fetchone()[0] == variants

    def test_two_candidates_for_one_job_never_get_the_same_task(self, store) -> None:
        _, va = start(store, "rate_limiter", "subject:asha", job_id="job_1", seed=1, now=T)
        _, vb = start(store, "rate_limiter", "subject:ravi", job_id="job_1", seed=1, now=T)
        assert va.variant_id != vb.variant_id

    def test_the_deadline_is_the_pattern_s_time_limit(self, store) -> None:
        s, v = start(store, "rate_limiter", "subject:asha", seed=1, now=T)
        assert s.deadline - s.started_at == datetime.timedelta(minutes=v.time_limit_minutes)


class TestTheClock:
    """A job's task waits for Start; the time limit runs from there, never from Send."""

    def job_task(self, store, **kw):
        return start(store, "rate_limiter", "subject:asha", job_id="job_1", seed=1, now=T, begin=False, **kw)

    def test_a_job_s_task_has_no_clock_until_it_is_started(self, store) -> None:
        s, _ = self.job_task(store)
        assert (s.status, s.started_at, s.deadline) == (SessionStatus.ISSUED, None, None)
        assert s.start_by == T + datetime.timedelta(days=7)

    def test_start_runs_the_time_limit_from_then_and_only_once(self, store) -> None:
        s, v = self.job_task(store)
        later = T + datetime.timedelta(days=2)
        b = begin(store, s.session_id, now=later)
        assert b.status is SessionStatus.OPEN and b.started_at == later
        assert b.deadline == later + datetime.timedelta(minutes=v.time_limit_minutes)
        again = begin(store, s.session_id, now=later + datetime.timedelta(minutes=10))
        assert again.started_at == later, "pressing Start again must not reset the clock"

    def test_submitting_before_start_is_refused(self, store, sandbox) -> None:
        s, _ = self.job_task(store)
        with pytest.raises(SessionError, match="not been started"):
            submit(store, s.session_id, "x", now=T)

    def test_not_started_by_the_date_it_expires_and_cannot_be_started(self, store) -> None:
        s, _ = self.job_task(store)
        assert s.start_by is not None
        after = s.start_by + datetime.timedelta(seconds=1)
        assert current(store, s.session_id, now=after).status is SessionStatus.EXPIRED
        with pytest.raises(SessionError, match="start-by date passed"):
            begin(store, s.session_id, now=after)

    def test_the_recruiter_s_date_is_used_and_checked(self, store) -> None:
        chosen = T + datetime.timedelta(days=3)
        s, _ = self.job_task(store, start_by=chosen)
        assert s.start_by == chosen
        for bad, why in ((T - datetime.timedelta(hours=1), "already passed"),
                         (T + datetime.timedelta(days=61), "more than 60 days")):
            with pytest.raises(SessionError, match=why):
                start(store, "rate_limiter", "subject:ravi", job_id="job_1", now=T, begin=False, start_by=bad)

    def test_an_open_task_past_its_deadline_reads_expired_without_a_submission(self, store) -> None:
        """Before, only a late submission wrote "expired": an abandoned task said "open" forever."""
        s, _ = start(store, "rate_limiter", "subject:asha", seed=1, now=T)
        assert s.deadline is not None
        assert current(store, s.session_id, now=s.deadline + datetime.timedelta(seconds=60)).status is SessionStatus.OPEN
        assert current(store, s.session_id, now=s.deadline + datetime.timedelta(minutes=5)).status is SessionStatus.EXPIRED
        assert store.session(s.session_id).status is SessionStatus.EXPIRED  # written down

    def test_a_session_stored_before_issuing_and_starting_were_split_still_loads(self) -> None:
        old = {"session_id": "as_1", "variant_id": "v", "candidate_ref": "s",
               "started_at": T.isoformat(), "deadline": T.isoformat(), "status": "open"}
        assert Session.model_validate(old).issued_at == T


class TestSubmitting:
    def test_a_scored_result_is_stored_with_the_code_it_scored(self, store, sandbox) -> None:
        s, _ = start(store, "rate_limiter", "subject:asha", seed=1, now=T)
        result = submit(store, s.session_id, "print('mine')", now=T + datetime.timedelta(minutes=20))
        assert result.scored and store.result(s.session_id) == result
        assert store.submission(s.session_id) == "print('mine')"
        assert store.session(s.session_id).status is SessionStatus.SUBMITTED

    def test_three_attempts_the_last_counts_and_a_fourth_is_refused(self, store, sandbox) -> None:
        sandbox["run"] = Run(Outcome.TESTS_FAILED, rows({"exact_boundary"}), INFO)
        s, _ = start(store, "rate_limiter", "subject:asha", seed=1, now=T)
        for n in (1, 2):
            assert submit(store, s.session_id, f"x = {n}", now=T).attempt == n
            assert store.result(s.session_id) is None, "not final while attempts are left"
        sandbox["run"] = Run(Outcome.TESTS_FAILED, rows({"exact_boundary", "window_slides"}), INFO)
        third = submit(store, s.session_id, "x = 3", now=T)
        assert store.result(s.session_id) == third and third.score.passed == 4, "the last counts, worse or not"
        assert store.submission(s.session_id) == "x = 3"
        assert [r.attempt for r, _ in store.attempts(s.session_id)] == [1, 2, 3]
        with pytest.raises(SessionError, match="final"):
            submit(store, s.session_id, "x = 4", now=T)

    def test_an_attempt_passing_every_test_is_final_at_once(self, store, sandbox) -> None:
        s, _ = start(store, "rate_limiter", "subject:asha", seed=1, now=T)
        submit(store, s.session_id, "x", now=T)
        assert store.session(s.session_id).status is SessionStatus.SUBMITTED

    def test_code_that_does_not_parse_is_refused_and_costs_nothing(self, store, sandbox) -> None:
        """The cut-off paste: refused with its line, before the sandbox; no attempt used."""
        s, _ = start(store, "rate_limiter", "subject:asha", seed=1, now=T)
        with pytest.raises(NotPythonError, match="line 2"):
            submit(store, s.session_id, 'x = 1\ny = {"wind\n', now=T)
        with pytest.raises(NotPythonError):
            run_examples(store, s.session_id, "def f(:\n", now=T)
        assert store.attempts(s.session_id) == [] and store.session(s.session_id).status is SessionStatus.OPEN

    def test_finish_counts_the_last_attempt_and_needs_one(self, store, sandbox) -> None:
        sandbox["run"] = Run(Outcome.TESTS_FAILED, rows({"exact_boundary"}), INFO)
        s, _ = start(store, "rate_limiter", "subject:asha", seed=1, now=T)
        with pytest.raises(SessionError, match="nothing submitted"):
            finish(store, s.session_id, now=T)
        first = submit(store, s.session_id, "x", now=T)
        assert finish(store, s.session_id, now=T) == first == store.result(s.session_id)
        assert finish(store, s.session_id, now=T) == first, "finishing again changes nothing"

    def test_the_deadline_counts_the_last_attempt_or_expires_a_task_with_none(self, store, sandbox) -> None:
        sandbox["run"] = Run(Outcome.TESTS_FAILED, rows({"exact_boundary"}), INFO)
        a, _ = start(store, "rate_limiter", "subject:asha", seed=1, now=T)
        b, _ = start(store, "rate_limiter", "subject:ravi", seed=2, now=T)
        tried = submit(store, a.session_id, "x", now=T)
        late = T + datetime.timedelta(hours=2)
        assert current(store, a.session_id, now=late).status is SessionStatus.SUBMITTED
        assert store.result(a.session_id) == tried
        assert current(store, b.session_id, now=late).status is SessionStatus.EXPIRED

    def test_run_tries_the_examples_and_stores_nothing(self, store, sandbox) -> None:
        s, _ = start(store, "rate_limiter", "subject:asha", seed=1, now=T)
        for _ in range(5):
            assert run_examples(store, s.session_id, "x = 1", now=T).outcome is Outcome.PASSED
        assert store.attempts(s.session_id) == [] and store.result(s.session_id) is None

    def test_run_is_refused_once_the_result_is_final(self, store, sandbox) -> None:
        s, _ = start(store, "rate_limiter", "subject:asha", seed=1, now=T)
        submit(store, s.session_id, "x", now=T)                 # passes every test: final
        with pytest.raises(SessionError, match="only while it is open"):
            run_examples(store, s.session_id, "x", now=T)

    def test_a_result_stored_before_attempts_existed_becomes_attempt_one(self, store, tmp_path, sandbox) -> None:
        s, _ = start(store, "rate_limiter", "subject:asha", seed=1, now=T)
        doc = submit(store, s.session_id, "x", now=T).model_dump(mode="json")
        doc.pop("attempt")                                      # the old shape had no attempt
        older = Store(tmp_path / "older.db")                    # rows as the old code wrote them
        with older.tx() as db:
            db.execute("INSERT INTO submissions VALUES (?, ?)", ("as_old", "print(1)"))
            db.execute("INSERT INTO results VALUES (?, ?, ?, ?)", ("as_old", "rate_limiter", 1, json.dumps(doc)))
        reopened = Store(tmp_path / "older.db")
        [(attempt, source)] = reopened.attempts("as_old")
        assert attempt.attempt == 1 and source == "print(1)"

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


class TestStandings:
    """One task's results, best first: hidden tests passed, then time taken."""

    def take(self, store, sandbox, ref, seed, run, minutes):
        s, _ = start(store, "rate_limiter", ref, job_id="job_1", seed=seed, now=T)
        sandbox["run"] = run
        submit(store, s.session_id, "x", now=T + datetime.timedelta(minutes=minutes))
        finish(store, s.session_id, now=T + datetime.timedelta(minutes=minutes))
        return store.result(s.session_id)

    def test_tests_passed_then_time_and_an_exact_tie_shares_its_place(self, store, sandbox) -> None:
        passed = Run(Outcome.PASSED, rows(), INFO)
        one_failed = Run(Outcome.TESTS_FAILED, rows({"exact_boundary"}), INFO)
        results = [
            self.take(store, sandbox, "slow", 1, passed, 20),
            self.take(store, sandbox, "fast", 2, passed, 10),
            self.take(store, sandbox, "quick_but_wrong", 3, one_failed, 5),
            self.take(store, sandbox, "fast_too", 4, passed, 10),
            self.take(store, sandbox, "no_import", 5, Run(Outcome.IMPORT_ERROR, [], INFO, "SyntaxError"), 2),
        ]
        ranks = {r.candidate_ref: rank for rank, r in standings(results)}
        assert ranks == {"fast": 1, "fast_too": 1, "slow": 3, "quick_but_wrong": 4, "no_import": 5}

    def test_time_never_outranks_a_test(self, store, sandbox) -> None:
        a = self.take(store, sandbox, "a", 1, Run(Outcome.PASSED, rows(), INFO), 39)
        b = self.take(store, sandbox, "b", 2, Run(Outcome.TESTS_FAILED, rows({"window_slides"}), INFO), 1)
        assert [r.candidate_ref for _, r in standings([b, a])] == ["a", "b"]


class TestTotals:
    """An assessment's total: each task worth 100 points, summed, then less time."""

    def result(self, store, sandbox, ref, seed, failed, minutes):
        return TestStandings().take(store, sandbox, ref, seed,
                                    Run(Outcome.TESTS_FAILED if failed else Outcome.PASSED, rows(failed), INFO), minutes)

    def test_each_task_is_worth_100_whatever_its_number_of_tests(self, store, sandbox) -> None:
        five_of_six = self.result(store, sandbox, "a", 1, {"exact_boundary"}, 10)
        assert task_points(five_of_six, 100) == pytest.approx(500 / 6)
        assert task_points(None, 100) == 0, "expired with nothing submitted is worth nothing"

    def test_points_then_time_and_only_finished_candidates_are_ranked(self, store, sandbox) -> None:
        full_slow = self.result(store, sandbox, "full_slow", 1, set(), 30)
        full_fast = self.result(store, sandbox, "full_fast", 2, set(), 10)
        part = self.result(store, sandbox, "part", 3, {"exact_boundary", "window_slides"}, 5)
        counted = {
            "full_slow": {"a": full_slow, "b": full_slow},      # 200 points, 60 min
            "full_fast": {"a": full_fast, "b": None},           # 100 + 0 (expired), 10 min
            "part": {"a": part, "b": part},                     # 2 x 66.7, 10 min
            "busy": {"a": full_fast},                           # task b still to finish
        }
        ranked, waiting = totals(["a", "b"], counted, 100)
        assert [(rank, t.candidate_ref, round(float(t.points), 1)) for rank, t in ranked] == [
            (1, "full_slow", 200.0), (2, "part", 133.3), (3, "full_fast", 100.0)]
        assert waiting == {"busy": ["b"]}

    def test_equal_totals_share_a_place_unless_time_differs(self, store, sandbox) -> None:
        x = self.result(store, sandbox, "x", 1, set(), 10)
        y = self.result(store, sandbox, "y", 2, set(), 10)
        z = self.result(store, sandbox, "z", 3, set(), 11)
        ranked, _ = totals(["a"], {"x": {"a": x}, "y": {"a": y}, "z": {"a": z}}, 100)
        assert {t.candidate_ref: rank for rank, t in ranked} == {"x": 1, "y": 1, "z": 3}
