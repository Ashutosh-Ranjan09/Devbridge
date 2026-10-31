"""The only place candidate code runs: a Docker container with no network.

  --network none        nothing in, nothing out
  --read-only           the code and tests are mounted read-only; /tmp is a small tmpfs
  --memory/--cpus/--pids-limit, a non-root user, a wall clock, --pull never

Each test also has its own 2 s limit inside the run, so one infinite loop fails one
test instead of the whole submission.

Every way a run can end is a typed outcome. Only `sandbox_unavailable` — Docker
missing, the image missing, the daemon refusing — is not the candidate's doing, and
it is never scored: re-running may succeed.

Known limit, stated rather than hidden: the candidate's code is imported by the same
pytest process that writes the result file. A deliberately malicious solution could
try to forge that file. The path is random and the number of test cases is checked,
which raises the bar without closing it; the submitted code is stored with the result
so a person can always read what was run.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from assess import junit
from assess.config import settings
from assess.models import Outcome, Pattern, SandboxInfo, Scalar

DOCKER_FAILED = {125, 126, 127}   # docker run itself, or the command in it, never started
PER_TEST_SECONDS = 2              # validation uses the same limit: see validation.run_trusted


@dataclass(frozen=True)
class Run:
    outcome: Outcome
    rows: list[junit.CaseResult]
    info: SandboxInfo
    note: str | None = None


def docker_error(stderr: str) -> str:
    """Docker's own reason a run did not start. Its last line is a usage hint ("Run
    'docker run --help' for more information"); the reason is the line before it."""
    lines = [ln.strip() for ln in stderr.splitlines()
             if ln.strip() and not ln.strip().startswith("Run 'docker")]
    return (lines[-1] if lines else "docker could not start the run")[:300]


def run_candidate(pattern: Pattern, params: dict[str, Scalar], solution_source: str,
                  suite: Literal["hidden", "visible"] = "hidden") -> Run:
    """`hidden` scores a submission; `visible` is the Run button's examples, in the same
    sandbox under the same limits, because it is the same candidate code."""
    image = settings.sandbox_image
    if shutil.which("docker") is None:
        return Run(Outcome.SANDBOX_UNAVAILABLE, [], SandboxInfo(image=image, wall_seconds=0.0, exit_code=None),
                   "docker is not installed")

    tests_file = f"tests_{suite}.py"
    expected = (len(pattern.tests.core) + len(pattern.tests.twist) if suite == "hidden"
                else len(pattern.tests.visible))
    with tempfile.TemporaryDirectory(prefix="assess-run-") as tmp:
        work, out = Path(tmp) / "work", Path(tmp) / "out"
        work.mkdir()
        out.mkdir()
        os.chmod(work, 0o755)
        os.chmod(out, 0o777)                         # the container's user writes the result here
        (work / "solution.py").write_text(solution_source)
        shutil.copy(pattern.directory / tests_file, work / tests_file)
        (work / "params.json").write_text(json.dumps(params))
        for f in work.iterdir():
            os.chmod(f, 0o644)

        result_name = f"{uuid.uuid4().hex}.xml"
        name = f"assess-{uuid.uuid4().hex[:12]}"
        command = [
            "docker", "run", "--rm", "--name", name, "--pull", "never",
            "--network", "none", "--read-only", "--tmpfs", "/tmp:rw,size=16m",
            "--memory", "256m", "--memory-swap", "256m", "--cpus", "0.5", "--pids-limit", "64",
            "--user", "10001", "--security-opt", "no-new-privileges",
            "-v", f"{work}:/work:ro", "-v", f"{out}:/out:rw",
            image,
            "python", "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--timeout={PER_TEST_SECONDS}",
            f"--junitxml=/out/{result_name}", f"/work/{tests_file}",
        ]
        started = time.monotonic()
        try:
            proc = subprocess.run(command, capture_output=True, text=True,
                                  timeout=settings.sandbox_wall_seconds, check=False)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "kill", name], capture_output=True, check=False)
            return Run(Outcome.TIMEOUT, [], SandboxInfo(image=image, wall_seconds=round(time.monotonic() - started, 2),
                                                        exit_code=None),
                       f"the whole run exceeded {settings.sandbox_wall_seconds:.0f} s")
        wall = round(time.monotonic() - started, 2)
        info = SandboxInfo(image=image, wall_seconds=wall, exit_code=proc.returncode)
        rows = junit.read(out / result_name)

    if proc.returncode in DOCKER_FAILED:
        return Run(Outcome.SANDBOX_UNAVAILABLE, [], info, docker_error(proc.stderr))
    if proc.returncode == 137:
        return Run(Outcome.RESOURCE_LIMIT, rows, info, "killed: memory limit (256 MB)")
    if not rows:
        # pytest could not even collect the tests: the solution does not import.
        detail = next((ln for ln in reversed(proc.stdout.splitlines()) if "Error" in ln), "")
        return Run(Outcome.IMPORT_ERROR, [], info, detail.strip()[:300] or "the solution does not import")
    if len(rows) != expected:
        return Run(Outcome.SANDBOX_UNAVAILABLE, [], info,
                   f"expected {expected} test results, found {len(rows)} — the result is not trusted")
    outcome = Outcome.PASSED if all(r.passed for r in rows) else Outcome.TESTS_FAILED
    return Run(outcome, rows, info)
