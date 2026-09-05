"""CV date text to a FuzzyDate, deterministically.

The model returns the date exactly as written; this parses it. Never the other way
round — asked about `2022-26` a model will confidently return June 2022, and nothing
downstream can tell that it guessed.

**Precision is the output that matters.** It drives the interval algebra: a date parsed
one level too fine manufactures a DEFINITE overlap where the document supports only a
POSSIBLE one, which is the exact failure hard constraint 2 exists to prevent. When in
doubt this parser is *less* precise, never more.

No `dateutil`. It is permissive by design and will happily read `2022-26` as June 2022
— a confidently wrong precision, which is worse than a failure. Here an unrecognised
format returns None and the caller keeps the claim without an interval.
"""

from __future__ import annotations

import calendar
import re

from cvv.models import FuzzyDate, Interval, Precision

MONTHS: dict[str, int] = {
    name.lower(): number
    for number in range(1, 13)
    for name in (calendar.month_name[number], calendar.month_abbr[number])
}
MONTHS |= {"sept": 9}

# "Present" and its synonyms. `end=None, ongoing=True` — the interval reaches today.
ONGOING = frozenset(
    {"present", "current", "currently", "ongoing", "now", "till date", "to date", "date"}
)

# Seasons parse to YEAR precision, never to months. The mapping is culturally
# specific — an Indian summer internship is May-July, a Southern-hemisphere one is
# not — and inventing months fabricates a core span the document does not support.
# Losing precision costs a check; inventing it produces a false finding.
SEASONS = frozenset({"summer", "winter", "spring", "autumn", "fall", "monsoon"})

# En dash and em dash are what a PDF actually contains; ruff flags them as
# ambiguous, which is true for identifiers and beside the point in a pattern
# whose whole job is matching them.
RANGE_SEPARATORS = re.compile("\\s*(?:--|\u2013|\u2014|-|to|until|till)\\s*", re.I)

_YEAR = r"(?:19|20)\d{2}"
_MON = "|".join(sorted(MONTHS, key=len, reverse=True))

# Ordered most specific first. The first match wins, so a pattern that could swallow
# a more precise one must come after it.
_ISO_EXACT = re.compile(rf"^({_YEAR})[-/](\d{{1,2}})[-/](\d{{1,2}})$")
_DMY_EXACT = re.compile(rf"^(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MON})\.?,?\s+'?(\d{{2,4}})$", re.I)
_MDY_EXACT = re.compile(rf"^({_MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+'?(\d{{2,4}})$", re.I)
_MON_YEAR = re.compile(rf"^({_MON})\.?,?\s*'?(\d{{2,4}})$", re.I)
_YEAR_MON = re.compile(rf"^({_YEAR})[-/](\d{{1,2}})$")
_NUM_MON_YEAR = re.compile(rf"^(\d{{1,2}})[-/]({_YEAR})$")
_SEASON_YEAR = re.compile(r"^(\w+)\s+'?(\d{2,4})$")
# A two-digit year must carry its apostrophe. Bare "13" is not a year: it is the
# tail of something that failed to parse, and reading it as 2013 turns a
# malformed "2025-13" into a confident 2025..2013.
_BARE_YEAR = re.compile(rf"^(?:({_YEAR})|'(\d{{2}}))$")

# "2022-26" — a compressed range, extremely common for a degree on an Indian CV, and
# NOT a date. A permissive parser reads it as a month and the claim silently acquires
# the wrong precision. Matched before anything else, and only when the second number
# reads as a plausible later year: a four-year degree ending in month 26 is not a
# thing, whereas 2022-06 genuinely is ambiguous and is left to the month reading.
DASHES = "-\u2013\u2014"  # hyphen, en dash, em dash \u2014 all three occur in real PDFs
_COMPRESSED_RANGE = re.compile("^(" + _YEAR + r")\s*[" + DASHES + r"]\s*(\d{2})$")


def expand_two_digit_year(value: int) -> int:
    """`'25` is 2025, never 1925.

    "Not in the future" cannot be the disambiguation rule: a degree reading 2022-2026
    on a 2026 CV is valid, and education ending in the future is normal.
    """
    return 2000 + value if value < 100 else value


def parse_date(text: str) -> FuzzyDate | None:
    """One date. Returns None when the format is not recognised — visibly, so the
    caller can drop the interval and keep the claim."""
    token = text.strip().strip(",.[]()").strip()
    if not token:
        return None

    if m := _ISO_EXACT.match(token):
        return _exact(int(m[1]), int(m[2]), int(m[3]))

    if m := _DMY_EXACT.match(token):
        return _exact(expand_two_digit_year(int(m[3])), MONTHS[m[2].lower()], int(m[1]))

    if m := _MDY_EXACT.match(token):
        return _exact(expand_two_digit_year(int(m[3])), MONTHS[m[1].lower()], int(m[2]))

    if m := _MON_YEAR.match(token):
        return _month(expand_two_digit_year(int(m[2])), MONTHS[m[1].lower()])

    if m := _YEAR_MON.match(token):
        month = int(m[2])
        return _month(int(m[1]), month) if 1 <= month <= 12 else None

    if m := _NUM_MON_YEAR.match(token):
        month = int(m[1])
        return _month(int(m[2]), month) if 1 <= month <= 12 else None

    if m := _SEASON_YEAR.match(token):
        if m[1].lower() in SEASONS:
            return _year(expand_two_digit_year(int(m[2])))
        return None

    if m := _BARE_YEAR.match(token):
        return _year(expand_two_digit_year(int(m[1] or m[2])))

    return None


def parse_interval(text: str) -> Interval | None:
    """A date range as a CV writes it. `[Mar '25 - Apr '25]`, `2022-26`, `Jan 2020 -
    Present`, or a single date, which is a point rather than an open range."""
    token = text.strip().strip("[](){}").strip()
    if not token:
        return None

    if m := _COMPRESSED_RANGE.match(token):
        start_year = int(m[1])
        end_year = expand_two_digit_year(int(m[2]))
        # A degree spans a few years. If the compressed reading is implausible — the
        # "end" lands before the start, as in "2025-06" — this is not that pattern,
        # so fall through to the month reading rather than failing here. `2022-26`
        # takes the range; `2025-06` takes June 2025.
        if 0 < end_year - start_year <= 10:
            return Interval(start=_year(start_year), end=_year(end_year))

    # The whole token as ONE date, before any splitting. "2025-06" is June 2025 and
    # "2025-03-15" is a day; splitting them on the hyphen first produced "2025 to
    # 2006" and a three-part failure respectively.
    if single := parse_date(token):
        # A single date is a POINT — a graduation year is a year, not "2027 onwards".
        return Interval(start=single)

    parts = [p for p in RANGE_SEPARATORS.split(token) if p.strip()]
    if len(parts) != 2:
        return None  # not a range this parser understands

    head, tail = parts
    start = parse_date(head)
    if start is None:
        return None

    if tail.strip().lower() in ONGOING:
        return Interval(start=start, ongoing=True)

    end = parse_date(tail)
    if end is None:
        return None
    if (end.year, end.month or 1, end.day or 1) < (start.year, start.month or 1, start.day or 1):
        return None  # an end before its start is a misparse; fail visibly
    return Interval(start=start, end=end)


def _exact(year: int, month: int, day: int) -> FuzzyDate | None:
    try:
        return FuzzyDate(year=year, month=month, day=day, precision=Precision.EXACT)
    except ValueError:
        return None  # 31 April and friends — the model validator catches it


def _month(year: int, month: int) -> FuzzyDate | None:
    try:
        return FuzzyDate(year=year, month=month, precision=Precision.MONTH)
    except ValueError:
        return None


def _year(year: int) -> FuzzyDate | None:
    try:
        return FuzzyDate(year=year, precision=Precision.YEAR)
    except ValueError:
        return None  # outside 1950-2100
