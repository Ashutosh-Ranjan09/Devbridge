"""Three-valued interval algebra over fuzzy CV dates.

A CV date denotes a SET of dates, so an interval has two spans:

  core span   [start.latest, end.earliest]   covered under EVERY reading
  max span    [start.earliest, end.latest]   covered under SOME reading

Cores intersect -> DEFINITE.  Only max spans intersect -> POSSIBLE.  Neither -> NONE.

**Only DEFINITE may raise a scoring discrepancy.** Most Indian CVs give year precision
only; scoring POSSIBLE overlaps turns every clean CV into six contradictions. A
single-year or single-month interval has an EMPTY core and can never be DEFINITE — that
emptiness is the mechanism, not a defect. Live example from a real CV: CF-Connect
[May '25 - Jun '25] against Dijkstra Visualizer [Jun '25]. Both cover June, so a naive
comparison reports a contradiction; the two projects could equally have run Jun 1-10 and
Jun 20-30, and the document does not say.

`today` is injected everywhere it is needed. Nothing here reads the clock — a
verification must reproduce when re-run, and a report stored in March must still explain
itself in September.
"""

from __future__ import annotations

import calendar
import datetime
from collections.abc import Iterable
from enum import StrEnum

from cvv.models import FuzzyDate, Interval, Precision

Span = tuple[datetime.date, datetime.date]


class Rel(StrEnum):
    DEFINITE = "definite"  # under every consistent reading — scorable
    POSSIBLE = "possible"  # under some reading — context, never scored
    NONE = "none"


def bounds(d: FuzzyDate) -> Span:
    """Expand a fuzzy date to (earliest, latest).

    2021       -> 2021-01-01 .. 2021-12-31
    2021-02    -> 2021-02-01 .. 2021-02-28   (2020-02 -> the 29th; leap years are real)
    2021-02-15 -> 2021-02-15 .. 2021-02-15
    """
    if d.precision is Precision.EXACT:
        assert d.month is not None and d.day is not None
        exact = datetime.date(d.year, d.month, d.day)
        return exact, exact
    if d.precision is Precision.MONTH:
        assert d.month is not None
        last = calendar.monthrange(d.year, d.month)[1]
        return datetime.date(d.year, d.month, 1), datetime.date(d.year, d.month, last)
    return datetime.date(d.year, 1, 1), datetime.date(d.year, 12, 31)


def _end_bounds(iv: Interval, *, today: datetime.date) -> Span:
    if iv.ongoing:
        # Still running, so it definitely reaches today; nothing is asserted beyond.
        return today, today
    if iv.end is None:
        # A single point — a graduation year is a year, not "2027 onwards".
        return bounds(iv.start)
    return bounds(iv.end)


def core_span(iv: Interval, *, today: datetime.date) -> Span:
    """Dates covered under every reading. MAY BE INVERTED: "2021" has start.latest
    2021-12-31 after end.earliest 2021-01-01, and that empty core is exactly why a
    year-precision interval can never be DEFINITE."""
    return bounds(iv.start)[1], _end_bounds(iv, today=today)[0]


def max_span(iv: Interval, *, today: datetime.date) -> Span:
    """Dates the interval could cover under some reading."""
    return bounds(iv.start)[0], _end_bounds(iv, today=today)[1]


def length_days(span: Span) -> int:
    """Inclusive day count, never negative. An inverted span has length 0."""
    lo, hi = span
    return max(0, (hi - lo).days + 1)


def intersect(a: Span, b: Span) -> Span:
    """May be inverted, in which case length_days() is 0."""
    return max(a[0], b[0]), min(a[1], b[1])


def overlap(a: Interval, b: Interval, *, today: datetime.date) -> tuple[Rel, float]:
    """Three-valued overlap, with the fraction of the SHORTER core consumed.

    The fraction is 0.0 unless DEFINITE. A POSSIBLE overlap has no honest magnitude,
    and quoting one invites it into an explanation where it reads as a measurement.
    """
    ca, cb = core_span(a, today=today), core_span(b, today=today)
    hit = length_days(intersect(ca, cb))
    if hit > 0:
        shorter = min(length_days(ca), length_days(cb))
        return Rel.DEFINITE, hit / shorter if shorter else 0.0

    ma, mb = max_span(a, today=today), max_span(b, today=today)
    if length_days(intersect(ma, mb)) > 0:
        return Rel.POSSIBLE, 0.0
    return Rel.NONE, 0.0


def contains(iv: Interval, day: datetime.date, *, today: datetime.date) -> Rel:
    """Three-valued membership — G5 (a commit inside the claimed window), G10."""
    lo, hi = core_span(iv, today=today)
    if lo <= day <= hi:
        return Rel.DEFINITE
    lo, hi = max_span(iv, today=today)
    return Rel.POSSIBLE if lo <= day <= hi else Rel.NONE


def merge_non_overlapping(
    intervals: Iterable[Interval], *, today: datetime.date
) -> list[Span]:
    """Union of MAX spans, for D6 aggregate-duration arithmetic.

    Max spans rather than cores, deliberately. D6 compares a stated total against what
    the CV supports, and the generous reading is the one that avoids accusing a
    candidate of overstating when the dates merely round in their favour.
    """
    spans = sorted(
        (max_span(iv, today=today) for iv in intervals), key=lambda s: (s[0], s[1])
    )
    merged: list[Span] = []
    for lo, hi in spans:
        if merged and lo <= merged[-1][1] + datetime.timedelta(days=1):
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


def gap_between(a: Interval, b: Interval, *, today: datetime.date) -> int | None:
    """Days strictly between two intervals, or None if they might touch — D11.

    Max spans, so a gap is reported only when one exists under every reading. D11 is
    declared scoring=false: this measures career shape, which is not evidence of
    anything. A gap can be illness, caregiving or a visa. It is displayed; it never
    moves a number.
    """
    first, second = sorted(
        (max_span(a, today=today), max_span(b, today=today)), key=lambda s: s[0]
    )
    days = (second[0] - first[1]).days - 1
    return days if days > 0 else None
