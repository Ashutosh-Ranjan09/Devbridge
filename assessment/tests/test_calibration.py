"""Calibration: drift between twists is flagged, never adjusted, and needs enough data."""

from __future__ import annotations

from assess.calibration import MIN_ATTEMPTS, calibrate, render
from assess.models import Outcome, Result, Score, TestResult
from assess.patterns import load
from tests.test_events import NOW


def results(twist: str, n: int, twist_passes: int, version: int = 1) -> list[Result]:
    out = []
    for i in range(n):
        ok = i < twist_passes
        tests = [TestResult(name=c, group="core", passed=True) for c in load("rate_limiter").tests.core]
        tests.append(TestResult(name="twist_behaviour", group="twist", passed=ok))
        out.append(Result(
            session_id=f"as_{twist}_{i}", candidate_ref=f"subject:{i}", pattern_id="rate_limiter",
            pattern_version=version, skill="rate_limiting", level="medium", variant_id="v",
            params={"key_kind": "ip_address", "limit": 5, "window": 60, "twist": twist},
            outcome=Outcome.PASSED if ok else Outcome.TESTS_FAILED, scored=True, tests=tests,
            score=Score(passed=5 + ok, total=6, core_passed=5, core_total=5, twist_passed=int(ok), twist_total=1),
            time_used_seconds=600, time_limit_minutes=40, submitted_at=NOW,
            sandbox={"image": "i", "wall_seconds": 0.5, "exit_code": 0}))
    return out


def test_a_twist_much_harder_than_the_others_is_flagged() -> None:
    """The example from the design: retry_after at 62% against 85-88%."""
    data = results("retry_after", 20, 12) + results("remaining", 20, 18) + results("error_payload", 20, 17)
    c = calibrate(load("rate_limiter"), data)
    assert c.flagged == ["retry_after"]
    assert "FLAGGED" in render(c)


def test_twists_within_range_are_not_flagged() -> None:
    data = results("retry_after", 20, 16) + results("remaining", 20, 18) + results("error_payload", 20, 17)
    assert calibrate(load("rate_limiter"), data).flagged == []


def test_too_few_results_judge_nothing() -> None:
    n = MIN_ATTEMPTS - 1
    data = results("retry_after", n, 0) + results("remaining", n, n) + results("error_payload", n, n)
    c = calibrate(load("rate_limiter"), data)
    assert c.flagged == [] and "too few" in c.note


def test_versions_are_never_mixed() -> None:
    data = results("retry_after", 20, 0, version=2) + results("remaining", 20, 18)
    c = calibrate(load("rate_limiter"), data)
    assert c.results == 20 and c.by_twist["retry_after"] == (0, 0)
