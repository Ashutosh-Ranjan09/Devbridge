"""Properties of the three-valued interval algebra.

Hand-written examples will not find the off-by-one at a year boundary, so the core
guarantees are stated as properties over generated intervals. The generators
deliberately produce inverted intervals — a real CV contains typos and the algebra
must degrade, not raise.

`today` is fixed. Nothing in intervals.py may read the clock.
"""

from __future__ import annotations

import calendar
import datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cvv.dates import parse_interval
from cvv.intervals import (
    Rel,
    bounds,
    contains,
    core_span,
    gap_between,
    intersect,
    length_days,
    max_span,
    merge_non_overlapping,
    overlap,
)
from cvv.models import FuzzyDate, Interval, Precision

TODAY = datetime.date(2026, 9, 5)


@st.composite
def fuzzy_dates(draw: st.DrawFn, precision: Precision | None = None) -> FuzzyDate:
    year = draw(st.integers(min_value=1990, max_value=2035))
    prec = precision or draw(st.sampled_from(list(Precision)))
    if prec is Precision.YEAR:
        return FuzzyDate(year=year, precision=prec)
    month = draw(st.integers(min_value=1, max_value=12))
    if prec is Precision.MONTH:
        return FuzzyDate(year=year, month=month, precision=prec)
    day = draw(st.integers(min_value=1, max_value=calendar.monthrange(year, month)[1]))
    return FuzzyDate(year=year, month=month, day=day, precision=prec)


@st.composite
def intervals(draw: st.DrawFn, precision: Precision | None = None) -> Interval:
    """Closed, single-point and ongoing. End may precede start — CVs contain typos and
    the algebra must return NONE rather than raise."""
    start = draw(fuzzy_dates(precision))
    shape = draw(st.sampled_from(["closed", "point", "ongoing"]))
    if shape == "point":
        return Interval(start=start)
    if shape == "ongoing":
        return Interval(start=start, ongoing=True)
    return Interval(start=start, end=draw(fuzzy_dates(precision)))


class TestBounds:
    @pytest.mark.parametrize(
        ("fd", "expected"),
        [
            (
                FuzzyDate(year=2021, precision=Precision.YEAR),
                (datetime.date(2021, 1, 1), datetime.date(2021, 12, 31)),
            ),
            (
                FuzzyDate(year=2021, month=2, precision=Precision.MONTH),
                (datetime.date(2021, 2, 1), datetime.date(2021, 2, 28)),
            ),
            (
                FuzzyDate(year=2020, month=2, precision=Precision.MONTH),
                (datetime.date(2020, 2, 1), datetime.date(2020, 2, 29)),  # leap years
            ),
            (
                FuzzyDate(year=2021, month=2, day=15, precision=Precision.EXACT),
                (datetime.date(2021, 2, 15), datetime.date(2021, 2, 15)),
            ),
        ],
    )
    def test_expands_by_precision(self, fd: FuzzyDate, expected: tuple[datetime.date, ...]) -> None:
        assert bounds(fd) == expected

    @given(fuzzy_dates())
    def test_bounds_are_ordered(self, fd: FuzzyDate) -> None:
        lo, hi = bounds(fd)
        assert lo <= hi


class TestProperties:
    @given(intervals(), intervals())
    def test_overlap_is_symmetric(self, a: Interval, b: Interval) -> None:
        assert overlap(a, b, today=TODAY) == overlap(b, a, today=TODAY)

    @given(intervals(), intervals())
    def test_definite_implies_possible(self, a: Interval, b: Interval) -> None:
        """DEFINITE is the strictly stronger claim: if the cores meet, the max spans
        must."""
        rel, _ = overlap(a, b, today=TODAY)
        if rel is Rel.DEFINITE:
            assert length_days(intersect(max_span(a, today=TODAY), max_span(b, today=TODAY))) > 0

    @given(intervals())
    def test_self_overlap_is_definite_exactly_when_the_core_is_non_empty(
        self, a: Interval
    ) -> None:
        """A single-year interval overlaps ITSELF only possibly. Its core is empty, and
        that emptiness is the mechanism behind the hard constraint, not a defect."""
        rel, _ = overlap(a, a, today=TODAY)
        assert (rel is Rel.DEFINITE) == (length_days(core_span(a, today=TODAY)) > 0)

    @given(intervals(precision=Precision.EXACT), intervals(precision=Precision.EXACT))
    def test_exact_precision_reduces_to_naive_intersection(
        self, a: Interval, b: Interval
    ) -> None:
        """With no fuzziness there is nothing to be uncertain about: DEFINITE or NONE,
        agreeing with a plain date-range intersection. POSSIBLE cannot occur."""
        rel, _ = overlap(a, b, today=TODAY)
        assert rel is not Rel.POSSIBLE
        naive = length_days(intersect(max_span(a, today=TODAY), max_span(b, today=TODAY))) > 0
        assert (rel is Rel.DEFINITE) == naive

    @given(intervals())
    def test_a_single_year_interval_never_scores(self, other: Interval) -> None:
        """THE HARD-CONSTRAINT REGRESSION.

        "2021" against anything at all can never be DEFINITE, so it can never raise a
        scoring discrepancy. Most Indian CVs give year precision only; if this fails,
        every clean CV in the corpus has started producing contradictions.
        """
        year_only = Interval(
            start=FuzzyDate(year=2021, precision=Precision.YEAR),
            end=FuzzyDate(year=2021, precision=Precision.YEAR),
        )
        rel, _ = overlap(year_only, other, today=TODAY)
        assert rel is not Rel.DEFINITE

    @given(intervals(), intervals())
    def test_fraction_is_bounded_and_non_zero_only_when_definite(
        self, a: Interval, b: Interval
    ) -> None:
        rel, fraction = overlap(a, b, today=TODAY)
        assert 0.0 <= fraction <= 1.0
        assert (fraction > 0.0) == (rel is Rel.DEFINITE)

    @given(intervals(), intervals())
    def test_never_raises_on_inverted_intervals(self, a: Interval, b: Interval) -> None:
        """A CV reading "2023 - 2021" is a typo, not a crash."""
        overlap(a, b, today=TODAY)
        contains(a, TODAY, today=TODAY)
        gap_between(a, b, today=TODAY)
        merge_non_overlapping([a, b], today=TODAY)
        assert length_days(core_span(a, today=TODAY)) >= 0


class TestTheRealCV:
    """Dates taken from a real CV, parsed by the real parser."""

    def test_a_single_month_project_never_scores_against_an_overlapping_range(self) -> None:
        """CF-Connect [May '25 - Jun '25] against Dijkstra Visualizer [Jun '25].

        Both cover June, so a naive comparison reports a contradiction. The single
        month has an empty core, so the honest answer is POSSIBLE — the two could have
        run Jun 1-10 and Jun 20-30, and the document does not say.
        """
        cf = parse_interval("[May '25 - Jun '25]")
        dijkstra = parse_interval("[Jun '25]")
        assert cf is not None and dijkstra is not None
        rel, _ = overlap(cf, dijkstra, today=TODAY)
        assert rel is Rel.POSSIBLE

    def test_consecutive_projects_do_not_overlap(self) -> None:
        atma = parse_interval("[Mar '25 - Apr '25]")
        rsa = parse_interval("[Jun '24]")
        assert atma is not None and rsa is not None
        assert overlap(atma, rsa, today=TODAY)[0] is Rel.NONE

    def test_multi_year_degrees_that_genuinely_overlap_do_score(self) -> None:
        """Year precision does not mean unscorable. A 2022-2026 degree and a 2023-2027
        one overlap under EVERY reading — their cores are years wide — so DEFINITE is
        both correct and useful.

        The guardrail is narrower than "year precision never scores": it is that a
        SINGLE-point interval has an empty core. That is the case a real CV produces
        constantly, and it is the one that must not fire.
        """
        a = parse_interval("2022-26")
        b = parse_interval("2023-27")
        assert a is not None and b is not None
        assert overlap(a, b, today=TODAY)[0] is Rel.DEFINITE

    def test_two_single_year_claims_never_score(self) -> None:
        """"2023" and "2023" — the shape most Indian CVs actually produce."""
        a = parse_interval("2023")
        b = parse_interval("2023")
        assert a is not None and b is not None
        assert overlap(a, b, today=TODAY)[0] is Rel.POSSIBLE


class TestWorkedCases:
    _M = staticmethod(lambda y, m: FuzzyDate(year=y, month=m, precision=Precision.MONTH))
    _Y = staticmethod(lambda y: FuzzyDate(year=y, precision=Precision.YEAR))

    def test_two_internships_with_real_overlap_are_definite(self) -> None:
        a = Interval(start=self._M(2025, 6), end=self._M(2025, 8))
        b = Interval(start=self._M(2025, 7), end=self._M(2025, 9))
        assert overlap(a, b, today=TODAY)[0] is Rel.DEFINITE

    def test_two_ongoing_roles_both_reach_today(self) -> None:
        a = Interval(start=self._Y(2024), ongoing=True)
        b = Interval(start=self._M(2025, 3), ongoing=True)
        assert overlap(a, b, today=TODAY)[0] is Rel.DEFINITE

    def test_contains_is_three_valued(self) -> None:
        iv = Interval(start=self._M(2025, 6), end=self._M(2025, 8))
        assert contains(iv, datetime.date(2025, 7, 15), today=TODAY) is Rel.DEFINITE
        # August 20 is past the earliest possible end, inside the max span only
        assert contains(iv, datetime.date(2025, 8, 20), today=TODAY) is Rel.POSSIBLE
        assert contains(iv, datetime.date(2026, 1, 1), today=TODAY) is Rel.NONE

    def test_merge_unions_adjacent_spans(self) -> None:
        """D6: 2021-2022 and 2022-2023 are one three-year run, not six years."""
        merged = merge_non_overlapping(
            [
                Interval(start=self._Y(2021), end=self._Y(2022)),
                Interval(start=self._Y(2022), end=self._Y(2023)),
            ],
            today=TODAY,
        )
        assert merged == [(datetime.date(2021, 1, 1), datetime.date(2023, 12, 31))]

    def test_gap_between_reports_only_certain_gaps(self) -> None:
        far = gap_between(
            Interval(start=self._Y(2019), end=self._Y(2020)),
            Interval(start=self._Y(2023), end=self._Y(2024)),
            today=TODAY,
        )
        assert far == 730
        touching = gap_between(
            Interval(start=self._Y(2021), end=self._Y(2022)),
            Interval(start=self._Y(2022), end=self._Y(2023)),
            today=TODAY,
        )
        assert touching is None
