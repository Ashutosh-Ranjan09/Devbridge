"""Are a pattern's tests right? Proven by running them, before any candidate sees them.

Two directions, both required:

  - the REFERENCE, a correct solution a person wrote, must pass every test — a test it
    fails is wrong, and would fail a candidate for the test's own mistake;
  - every MUTANT, a realistic wrong answer, must fail at least one test in every
    combination it applies to — a suite a mutant passes is too weak to tell a wrong
    answer from a right one.

Only trusted code runs here, so it runs locally with the same test file the sandbox
uses. Candidate code never comes through this module.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from assess import junit
from assess.models import Pattern, Scalar
from assess.patterns import combinations, mutant_applies, mutants
from assess.sandbox import PER_TEST_SECONDS


def _case_id(pattern: Pattern, params: dict[str, Scalar]) -> str:
    """The id pytest shows inside [...]: the parameter values in pattern.yaml's order,
    then the twist, joined by "-". A pattern's tests_hidden.py must build the same."""
    return "-".join(str(params[name]) for name in [*pattern.parameters, "twist"])


def run_trusted(
    pattern: Pattern, solution: Path, params: list[dict[str, Scalar]]
) -> list[junit.CaseResult]:
    """The hidden tests against a TRUSTED solution, over a list of parameter sets, in
    one pytest run. Never call this with candidate code — that is the sandbox's job.

    Each test gets the sandbox's own limit. Here it runs on the full CPU, so a
    solution too slow for this would be too slow for the sandbox too."""
    with tempfile.TemporaryDirectory(prefix="assess-validate-") as tmp:
        work = Path(tmp)
        shutil.copy(solution, work / "solution.py")
        shutil.copy(pattern.directory / "tests_hidden.py", work / "tests_hidden.py")
        (work / "params.json").write_text(json.dumps(params))
        subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--timeout={PER_TEST_SECONDS}",
             "--junitxml", str(work / "out.xml"), str(work / "tests_hidden.py")],
            cwd=work, capture_output=True, text=True, timeout=600, check=False,
        )
        return junit.read(work / "out.xml")


@dataclass
class ValidationReport:
    pattern: str
    version: int
    combinations: int
    expected_cases: int
    reference_cases: int = 0
    reference_failures: list[str] = field(default_factory=list)
    # mutant -> combinations in which it failed NO test, i.e. escaped
    escapes: dict[str, list[str]] = field(default_factory=dict)
    caught_by: dict[str, set[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return (
            self.reference_cases == self.expected_cases
            and not self.reference_failures
            and not any(self.escapes.values())
        )


def validate(pattern: Pattern, params: list[dict[str, Scalar]] | None = None) -> ValidationReport:
    """Every combination by default; one variant's parameters when generating."""
    cases = params if params is not None else combinations(pattern)
    tests = [*pattern.tests.core, *pattern.tests.twist]
    report = ValidationReport(
        pattern=pattern.id, version=pattern.version, combinations=len(cases),
        expected_cases=len(cases) * len(tests),
    )

    ref = run_trusted(pattern, pattern.directory / "reference.py", cases)
    report.reference_cases = len(ref)
    report.reference_failures = [f"{r.test}[{r.case}]: {r.message}" for r in ref if not r.passed]

    for name, path in mutants(pattern).items():
        applicable = [c for c in cases if mutant_applies(name, c)]
        if not applicable:
            continue
        rows = run_trusted(pattern, path, applicable)
        failed_in: dict[str, set[str]] = defaultdict(set)
        for r in rows:
            if not r.passed:
                failed_in[r.case].add(r.test)
        report.escapes[name] = [_case_id(pattern, c) for c in applicable if not failed_in.get(_case_id(pattern, c))]
        report.caught_by[name] = set().union(*failed_in.values()) if failed_in else set()
    return report
