"""Curated reference data.

Tables the checks compare against — not libraries, and not derivable from the CV.
`data/roll-schemes.json` says what a roll number encodes at a given institution and
how long its programmes run; D9 and D8 both read it.

Every table here is institution- or region-specific and is loaded rather than
hard-coded, so adding a second institution is a data change and not a code change.
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@functools.cache
def roll_schemes() -> dict[str, dict[str, Any]]:
    path = DATA_DIR / "roll-schemes.json"
    if not path.is_file():
        return {}
    raw: dict[str, Any] = json.loads(path.read_text())
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def scheme_for(roll: str, org: str | None) -> dict[str, Any] | None:
    """The scheme whose pattern matches this roll number.

    Institution name is a hint, not a requirement — a CV may abbreviate it or omit
    it, and the pattern is the stronger signal. Where several schemes match the shape
    and an institution IS named, the named one wins.
    """
    matching = [s for s in roll_schemes().values() if re.match(s["pattern"], roll)]
    if not matching:
        return None
    if org and len(matching) > 1:
        lowered = org.lower()
        named = [s for s in matching if any(n in lowered for n in s.get("institutions", []))]
        if named:
            return named[0]
    return matching[0]


def department_matches(scheme: dict[str, Any], code: str, text: str) -> bool | None:
    """Does the department code agree with the degree as written?

    None means the code is not in the scheme's table — unknown, not wrong. A rule
    must abstain on that rather than treat an unlisted department as a contradiction.
    """
    names = scheme.get("departments", {}).get(code)
    if not names:
        return None
    lowered = text.lower()
    return any(name in lowered for name in names)


def programme_years(scheme: dict[str, Any], degree: str) -> int | None:
    """Standard duration for a degree as written, or None if unrecognised.

    Longest match first: "integrated m.tech" must win over "m.tech", or a five-year
    programme is read as a two-year one and every such CV looks contradictory.
    """
    lowered = degree.lower()
    table: dict[str, int | None] = scheme.get("programme_years", {})
    for name in sorted(table, key=len, reverse=True):
        if name in lowered:
            return table[name]
    return None
