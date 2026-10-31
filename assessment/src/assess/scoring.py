"""A run → a result: every declared test, whether it passed and why not, and a count.

No grade, no threshold, no pass/fail field. The count is split into core and twist
so a reader sees WHAT was missed — "failed only exact_boundary" says far more than
"6 of 7" — and a person decides what it means.
"""

from __future__ import annotations

import datetime

from assess.models import Outcome, Pattern, Result, Score, Session, TestResult, Variant
from assess.sandbox import Run

UNSCORED_DETAIL = {
    Outcome.IMPORT_ERROR: "the solution does not import, so no test could run",
    Outcome.TIMEOUT: "the whole run exceeded the time limit",
    Outcome.RESOURCE_LIMIT: "the run was killed for exceeding the memory limit",
}


def tests_for(pattern: Pattern, run: Run) -> list[TestResult]:
    by_name = {r.test: r for r in run.rows}
    out: list[TestResult] = []
    for group, names in (("core", pattern.tests.core), ("twist", pattern.tests.twist)):
        for name in names:
            row = by_name.get(name)
            if row is None:
                detail = UNSCORED_DETAIL.get(run.outcome, "did not run")
                out.append(TestResult(name=name, group=group, passed=False, detail=detail))
            else:
                out.append(TestResult(name=name, group=group, passed=row.passed,
                                      detail=None if row.passed else _clean(row.message)))
    return out


def _clean(message: str | None) -> str | None:
    if not message:
        return None
    return message.removeprefix("AssertionError: ").split("\nassert ")[0].strip()[:300]


def score(tests: list[TestResult]) -> Score:
    core = [t for t in tests if t.group == "core"]
    twist = [t for t in tests if t.group == "twist"]
    return Score(
        passed=sum(t.passed for t in tests), total=len(tests),
        core_passed=sum(t.passed for t in core), core_total=len(core),
        twist_passed=sum(t.passed for t in twist), twist_total=len(twist),
    )


def build_result(
    pattern: Pattern, variant: Variant, session: Session, run: Run, submitted_at: datetime.datetime,
    attempt: int = 1,
) -> Result:
    assert session.started_at is not None, "only a begun session is submitted"
    scored = run.outcome.scored
    tests = tests_for(pattern, run) if scored else []
    return Result(
        session_id=session.session_id,
        attempt=attempt,
        candidate_ref=session.candidate_ref,
        pattern_id=pattern.id,
        pattern_version=pattern.version,
        skill=pattern.skill,
        level=pattern.level,
        variant_id=variant.variant_id,
        params=variant.params,
        outcome=run.outcome,
        scored=scored,
        tests=tests,
        score=score(tests) if scored else None,
        time_used_seconds=int((submitted_at - session.started_at).total_seconds()),
        time_limit_minutes=variant.time_limit_minutes,
        submitted_at=submitted_at,
        sandbox=run.info,
        note=run.note,
    )


def standings(results: list[Result]) -> list[tuple[int, Result]]:
    """ONE task's final results, best first: hidden tests passed, then time taken.
    Equal on both share a place (1, 2, 2, 4). Never called across tasks: one order over
    several would need their scores added up, the overall score this system refuses.
    Comparable because every applicant to a job faced the same pattern, each variant
    equally hard (guardrail 3); a person still reads why each test failed."""
    def key(r: Result) -> tuple[int, int]:
        assert r.score is not None, "only a scored, final result is ranked"
        return (-r.score.passed, r.time_used_seconds)

    out: list[tuple[int, Result]] = []
    for i, r in enumerate(sorted(results, key=lambda r: (*key(r), r.session_id))):
        out.append((out[-1][0] if out and key(out[-1][1]) == key(r) else i + 1, r))
    return out


def render(result: Result) -> str:
    """The report a person reads."""
    p = result.params
    lines = [
        f"{result.pattern_id} v{result.pattern_version} · {result.level.value} · skill {result.skill}",
        f"variant {result.variant_id}  ({', '.join(f'{k}={v}' for k, v in p.items())})",
        f"candidate {result.candidate_ref} · attempt {result.attempt} · time used {result.time_used_seconds // 60} min "
        f"{result.time_used_seconds % 60:02d} s of {result.time_limit_minutes} min",
        f"outcome {result.outcome.value}" + (f" — {result.note}" if result.note else ""),
        "",
    ]
    if not result.scored:
        lines.append("Not scored: the sandbox could not run the submission. Re-running may succeed.")
        return "\n".join(lines)
    for t in result.tests:
        mark = "✓" if t.passed else "✗"
        lines.append(f"  {mark} {t.group:5} {t.name}" + (f"\n          {t.detail}" if t.detail else ""))
    s = result.score
    assert s is not None
    lines += ["", f"tests passed {s.passed}/{s.total}   core {s.core_passed}/{s.core_total}   "
                  f"twist {s.twist_passed}/{s.twist_total}"]
    return "\n".join(lines)
