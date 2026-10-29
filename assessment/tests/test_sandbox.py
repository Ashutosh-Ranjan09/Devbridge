"""Scoring from a run, and — with Docker — real runs of every kind of submission.

The scoring tests need no daemon. The `docker` tests run real containers; they are
excluded by default and run with `pytest -m docker` once `assess sandbox build` has
built the image.
"""

from __future__ import annotations

import datetime

import pytest

from assess import junit, scoring
from assess.models import Outcome, SandboxInfo, Session
from assess.patterns import load
from assess.sandbox import Run, docker_error, run_candidate
from assess.scoring import build_result, render, score
from assess.variants import generate

NOW = datetime.datetime(2026, 10, 26, 12, 0, tzinfo=datetime.UTC)
INFO = SandboxInfo(image="assess-python:3.12", wall_seconds=0.5, exit_code=1)


@pytest.fixture
def pattern():
    return load("rate_limiter")


@pytest.fixture
def session():
    return Session(session_id="as_t", variant_id="v_t", candidate_ref="subject:t",
                   started_at=NOW - datetime.timedelta(minutes=31), deadline=NOW)


def rows(failed: set[str] = frozenset()) -> list[junit.CaseResult]:
    names = ["allows_up_to_limit", "rejects_one_over", "keys_independent", "exact_boundary",
             "window_slides", "twist_behaviour"]
    return [junit.CaseResult(n, "c", n not in failed, f"AssertionError: {n} broke\nassert 1 == 2" if n in failed else None)
            for n in names]


class TestScoring:
    def test_every_declared_test_appears_once_with_its_group(self, pattern) -> None:
        tests = scoring.tests_for(pattern, Run(Outcome.TESTS_FAILED, rows({"exact_boundary"}), INFO))
        assert [t.name for t in tests][:5] == pattern.tests.core
        assert {t.group for t in tests if t.name == "twist_behaviour"} == {"twist"}
        failed = next(t for t in tests if not t.passed)
        assert failed.name == "exact_boundary" and failed.detail == "exact_boundary broke"

    def test_the_count_is_split_core_and_twist(self, pattern) -> None:
        s = score(scoring.tests_for(pattern, Run(Outcome.TESTS_FAILED, rows({"exact_boundary"}), INFO)))
        assert (s.passed, s.total, s.core_passed, s.twist_passed) == (5, 6, 4, 1)

    def test_a_submission_that_does_not_import_scores_zero_with_the_reason(self, pattern, session) -> None:
        v = generate(pattern, 1)
        r = build_result(pattern, v, session, Run(Outcome.IMPORT_ERROR, [], INFO, "SyntaxError"), NOW)
        assert r.scored and r.score is not None and r.score.passed == 0
        assert all(t.detail and "does not import" in t.detail for t in r.tests)

    def test_an_unavailable_sandbox_is_not_a_score(self, pattern, session) -> None:
        """A run that could not happen is not the candidate's zero."""
        v = generate(pattern, 1)
        r = build_result(pattern, v, session, Run(Outcome.SANDBOX_UNAVAILABLE, [], INFO, "no daemon"), NOW)
        assert not r.scored and r.score is None and r.tests == []
        assert "Not scored" in render(r)

    def test_time_used_is_from_session_start(self, pattern, session) -> None:
        v = generate(pattern, 1)
        r = build_result(pattern, v, session, Run(Outcome.PASSED, rows(), INFO), NOW)
        assert r.time_used_seconds == 31 * 60

    def test_an_unavailable_sandbox_says_docker_s_reason_not_its_usage_hint(self) -> None:
        stderr = ("docker: Error response from daemon: No such image: assess-python:3.12\n\n"
                  "Run 'docker run --help' for more information\n")
        assert docker_error(stderr) == "docker: Error response from daemon: No such image: assess-python:3.12"
        assert docker_error("") == "docker could not start the run"

    def test_the_report_has_no_verdict(self, pattern, session) -> None:
        v = generate(pattern, 1)
        text = render(build_result(pattern, v, session, Run(Outcome.PASSED, rows(), INFO), NOW))
        assert "6/6" in text
        for word in ("pass/fail", "hire", "recommend", "grade", "verdict"):
            assert word not in text.lower()


@pytest.mark.docker
class TestRealSandbox:
    """Needs Docker and the image. `pytest -m docker`."""

    @pytest.fixture
    def variant(self, pattern):
        return generate(pattern, 1)

    def test_the_reference_passes(self, pattern, variant) -> None:
        run = run_candidate(pattern, variant.params, (pattern.directory / "reference.py").read_text())
        assert run.outcome is Outcome.PASSED and len(run.rows) == 6

    def test_a_mutant_fails_the_test_meant_to_catch_it(self, pattern, variant) -> None:
        run = run_candidate(pattern, variant.params, (pattern.directory / "mutants/fixed_window.py").read_text())
        assert run.outcome is Outcome.TESTS_FAILED
        assert {r.test for r in run.rows if not r.passed} == {"exact_boundary"}

    def test_a_missing_image_is_unavailable_and_says_so(self, pattern, variant, monkeypatch) -> None:
        from assess.config import settings

        monkeypatch.setattr(settings, "sandbox_image", "assess-no-such-image:0")
        run = run_candidate(pattern, variant.params, "x = 1")
        assert run.outcome is Outcome.SANDBOX_UNAVAILABLE and "No such image" in (run.note or "")

    def test_code_that_does_not_import(self, pattern, variant) -> None:
        assert run_candidate(pattern, variant.params, "class RateLimiter(:\n").outcome is Outcome.IMPORT_ERROR

    def test_the_network_is_unreachable(self, pattern, variant) -> None:
        src = "import socket\nsocket.create_connection(('1.1.1.1', 53), timeout=2)\n"
        assert run_candidate(pattern, variant.params, src).outcome is Outcome.IMPORT_ERROR

    def test_memory_is_limited(self, pattern, variant) -> None:
        src = "x = bytearray(1024 * 1024 * 1024)\n"
        assert run_candidate(pattern, variant.params, src).outcome is Outcome.RESOURCE_LIMIT

    def test_an_infinite_loop_fails_tests_not_the_run(self, pattern, variant) -> None:
        src = (pattern.directory / "reference.py").read_text().replace(
            "        times = self.accepted[key]\n", "        while True: pass\n")
        run = run_candidate(pattern, variant.params, src)
        assert run.outcome is Outcome.TESTS_FAILED and not any(r.passed for r in run.rows)

    def test_the_code_cannot_write_its_mount(self, pattern, variant) -> None:
        src = "open('/work/tests_hidden.py', 'w').write('')\n"
        assert run_candidate(pattern, variant.params, src).outcome is Outcome.IMPORT_ERROR

    def test_the_dsa_reference_passes_inside_the_limits(self) -> None:
        """The large input must fit 2 s on half a CPU — validation ran on the full one."""
        p = load("top_k_frequent")
        params = {"item_kind": "search_query", "k": 10, "twist": "ignore_case"}
        run = run_candidate(p, params, (p.directory / "reference.py").read_text())
        assert run.outcome is Outcome.PASSED and len(run.rows) == 8

    def test_a_quadratic_solution_fails_only_the_large_input(self) -> None:
        p = load("top_k_frequent")
        params = {"item_kind": "product_id", "k": 3, "twist": "excluding"}
        run = run_candidate(p, params, (p.directory / "mutants/rescans_per_item.py").read_text())
        assert run.outcome is Outcome.TESTS_FAILED
        assert {r.test for r in run.rows if not r.passed} == {"large_input"}
