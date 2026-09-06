"""Curated reference data.

Tables the checks compare against — not libraries, and not derivable from the CV.
`data/roll-schemes.json` says what a roll number encodes at a given institution and
how long its programmes run; D9 and D8 both read it.

Every table here is institution- or region-specific and is loaded rather than
hard-coded, so adding a second institution is a data change and not a code change.
"""

from __future__ import annotations

import datetime
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


@functools.cache
def tech_releases() -> dict[str, datetime.date]:
    """Technology -> first public availability, keyed by normalised name.

    Every date in the file is biased EARLY on purpose: a date that is too early makes
    D7 miss a real anachronism, and a date that is too late makes it accuse an honest
    candidate. Only the first error is acceptable.
    """
    path = DATA_DIR / "tech-releases.json"
    if not path.is_file():
        return {}
    raw: dict[str, Any] = json.loads(path.read_text())
    return {
        normalise_tech(name): datetime.date.fromisoformat(released)
        for name, released in raw.get("releases", {}).items()
    }


def normalise_tech(name: str) -> str:
    """A technology name reduced to what is comparable across sources.

    `+` and `#` survive: dropping them collapses C, C++ and C# onto each other, and
    those are three different claims.
    """
    return re.sub(r"[^a-z0-9+#]", "", name.lower())


@functools.cache
def institution_contact(org: str) -> str | None:
    """A verification contact the OPERATOR supplied, or None.

    Never guessed and never derived. A wrong address for a registrar sends a
    candidate's details to a stranger, so an institution absent from the file
    produces no contact and the worksheet names the office by role instead.
    """
    path = DATA_DIR / "institutions.json"
    if not path.is_file():
        return None
    raw: dict[str, Any] = json.loads(path.read_text())
    lowered = org.lower()
    for entry in raw.get("institutions", []):
        if any(name.lower() in lowered for name in entry.get("names", [])):
            contact: str | None = entry.get("verification_contact")
            return contact
    return None


@functools.cache
def roll_patterns() -> list[tuple[str, re.Pattern[str]]]:
    r"""Every institution's roll-number shape, compiled, as (scheme key, pattern).

    Extraction reads these rather than carrying a pattern of its own. A hardcoded
    `\d{2}[A-Z]{2}\d{5}` finds IIT Kharagpur's roll numbers and nobody else's, so a
    VIT `19BCE1234` produced no identifier claim at all and D9 never ran — and adding
    VIT to this file would not have fixed it, because the finder never consulted the
    file. Recognition and interpretation now read the same table.

    The anchors are relaxed to word boundaries: the scheme patterns are anchored for
    `fullmatch` against a candidate token, and the same shape has to be findable
    inside a line of prose.
    """
    out: list[tuple[str, re.Pattern[str]]] = []
    for key, scheme in roll_schemes().items():
        pattern = str(scheme["pattern"])
        body = pattern.removeprefix("^").removesuffix("$")
        out.append((key, re.compile(rf"\b(?:{body})\b")))
    return out


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
