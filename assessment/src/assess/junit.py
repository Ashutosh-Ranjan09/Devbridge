"""pytest's JUnit XML → one row per test case. Shared by validation and scoring, so
both read a run the same way."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CaseResult:
    test: str            # "exact_boundary", without the "test_" prefix
    case: str            # the parameter id inside [...], "" when unparameterised
    passed: bool
    message: str | None


def read(path: Path) -> list[CaseResult]:
    """Every <testcase>. A run that never got as far as collecting tests has none."""
    if not path.is_file():
        return []
    rows: list[CaseResult] = []
    for tc in ET.parse(path).getroot().iter("testcase"):
        m = re.fullmatch(r"test_(\w+?)(?:\[(.*)\])?", tc.get("name", ""))
        if m is None:
            continue
        problem = next((tc.find(t) for t in ("failure", "error") if tc.find(t) is not None), None)
        message = None
        if problem is not None:
            message = (problem.get("message") or problem.text or "").strip().splitlines()[0][:300] or None
        rows.append(CaseResult(m.group(1), m.group(2) or "", problem is None and tc.find("skipped") is None, message))
    return rows
