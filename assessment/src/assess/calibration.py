"""Is every variant of a pattern really equally hard? Measured, after the fact.

Twists are declared equal; candidates' results show whether they are. Pass rates are
taken per named test and per twist, over every scored result for ONE pattern version —
versions are never mixed, because a re-rated pattern is a different test.

It only reports. A flagged twist is a person's decision: move it out of the pattern
(which bumps the version), or keep it with a reason. Nothing here adjusts a score.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from assess.models import Pattern, Result

DRIFT_POINTS = 20       # a twist this far from the others' mean is flagged …
MIN_ATTEMPTS = 15       # … once it, and every other twist, has this many results


@dataclass
class Calibration:
    pattern: str
    version: int
    results: int
    by_test: dict[str, tuple[int, int]] = field(default_factory=dict)     # name -> (passed, attempts)
    by_twist: dict[str, tuple[int, int]] = field(default_factory=dict)    # twist -> (passed, attempts)
    flagged: list[str] = field(default_factory=list)
    note: str = ""


def rate(passed: int, attempts: int) -> float:
    return 100.0 * passed / attempts if attempts else 0.0


def calibrate(pattern: Pattern, results: list[Result]) -> Calibration:
    scored = [r for r in results if r.scored and r.pattern_version == pattern.version
              and r.pattern_id == pattern.id]
    report = Calibration(pattern=pattern.id, version=pattern.version, results=len(scored))
    tests: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    twists: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in scored:
        for t in r.tests:
            tests[t.name][0] += t.passed
            tests[t.name][1] += 1
            if t.group == "twist":
                twist = str(r.params["twist"])
                twists[twist][0] += t.passed
                twists[twist][1] += 1
    report.by_test = {n: (tests[n][0], tests[n][1]) for n in [*pattern.tests.core, *pattern.tests.twist]}
    report.by_twist = {tw: (twists[tw][0], twists[tw][1]) for tw in sorted(pattern.twists)}

    if any(a < MIN_ATTEMPTS for _, a in report.by_twist.values()):
        report.note = (f"too few results to judge drift: every twist needs {MIN_ATTEMPTS} "
                       "attempts before its pass rate means anything")
        return report
    for twist, (p, a) in report.by_twist.items():
        others = [rate(op, oa) for tw, (op, oa) in report.by_twist.items() if tw != twist]
        if others and abs(rate(p, a) - sum(others) / len(others)) > DRIFT_POINTS:
            report.flagged.append(twist)
    report.note = ("twists within range of each other" if not report.flagged else
                   "flagged twists differ from the others by more than "
                   f"{DRIFT_POINTS} points: candidates given them were not given an equal task")
    return report


def render(c: Calibration) -> str:
    lines = [f"{c.pattern} v{c.version} — {c.results} scored result(s)", "", "  per test"]
    for name, (p, a) in c.by_test.items():
        lines.append(f"    {name:22} {rate(p, a):5.0f}%   ({p}/{a})")
    lines += ["", "  per twist"]
    for name, (p, a) in c.by_twist.items():
        mark = "  ← FLAGGED" if name in c.flagged else ""
        lines.append(f"    {name:22} {rate(p, a):5.0f}%   ({p}/{a}){mark}")
    lines += ["", f"  {c.note}"]
    return "\n".join(lines)
