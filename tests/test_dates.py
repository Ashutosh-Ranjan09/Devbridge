"""The date parser, and the traps it exists for.

Precision is the output that matters: it drives the interval algebra, and a date
parsed one level too fine manufactures a DEFINITE overlap the document does not
support. Every case here asserts the precision, not just the numbers.
"""

from __future__ import annotations

import pytest

from cvv.dates import expand_two_digit_year, parse_date, parse_interval
from cvv.models import Precision


def summarise(text: str) -> str:
    """`start[precision] .. end[precision]`, or None."""
    iv = parse_interval(text)
    if iv is None:
        return "None"

    def part(d: object) -> str:
        if d is None:
            return "-"
        y, m, day, p = d.year, d.month, d.day, d.precision  # type: ignore[attr-defined]
        stamp = f"{y}" + (f"-{m:02}" if m else "") + (f"-{day:02}" if day else "")
        return f"{stamp}[{p.value}]"

    return f"{part(iv.start)} .. {'ongoing' if iv.ongoing else part(iv.end)}"


class TestTheRealCV:
    """Formats taken verbatim from a CDC-template CV."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("[Mar '25 - Apr '25]", "2025-03[month] .. 2025-04[month]"),
            ("[May '25 - Jun '25]", "2025-05[month] .. 2025-06[month]"),
            ("[Jun '25]", "2025-06[month] .. -"),
            ("[Jun '24]", "2024-06[month] .. -"),
            ("2027", "2027[year] .. -"),
        ],
    )
    def test_parses(self, text: str, expected: str) -> None:
        assert summarise(text) == expected


class TestCompressedRange:
    """`2022-26` is a compressed range and NOT a date — extremely common for a degree
    on an Indian CV. A permissive parser reads it as June 2022 and the claim silently
    acquires the wrong precision, which is worse than failing."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("2022-26", "2022[year] .. 2026[year]"),
            ("2020-24", "2020[year] .. 2024[year]"),
            ("2019–23", "2019[year] .. 2023[year]"),
            ("2022-2026", "2022[year] .. 2026[year]"),
        ],
    )
    def test_reads_as_a_year_range(self, text: str, expected: str) -> None:
        assert summarise(text) == expected

    def test_a_plausible_month_still_wins(self) -> None:
        """`2025-06` matches the same shape, but 2006 lands before 2025, so the
        compressed reading is implausible and the month reading takes it."""
        assert summarise("2025-06") == "2025-06[month] .. -"

    def test_an_impossible_month_fails_rather_than_guessing(self) -> None:
        assert parse_interval("2025-13") is None


class TestSeasons:
    """A season parses to YEAR precision, never to months. The mapping is culturally
    specific — an Indian summer internship is May-July, a Southern-hemisphere one is
    not — and inventing months fabricates a core span the document never supported."""

    @pytest.mark.parametrize("text", ["Summer 2025", "Winter '24", "Fall 2023", "Monsoon 2024"])
    def test_year_precision_only(self, text: str) -> None:
        parsed = parse_date(text)
        assert parsed is not None
        assert parsed.precision is Precision.YEAR
        assert parsed.month is None


class TestOngoing:
    @pytest.mark.parametrize(
        "text",
        ["Jan 2020 - Present", "2021 – present", "Mar 2024 to date", "2022 - Current"],
    )
    def test_reaches_today(self, text: str) -> None:
        iv = parse_interval(text)
        assert iv is not None
        assert iv.ongoing is True
        assert iv.end is None


class TestTwoDigitYears:
    def test_expands_to_this_century(self) -> None:
        """`'25` is 2025, never 1925. "Not in the future" cannot be the rule — a degree
        reading 2022-2026 on a 2026 CV is valid, and education ending in the future is
        normal."""
        assert expand_two_digit_year(25) == 2025
        assert expand_two_digit_year(99) == 2099
        assert expand_two_digit_year(2025) == 2025

    def test_a_bare_two_digit_number_is_not_a_year(self) -> None:
        """Without the apostrophe, "13" is the tail of something that failed to parse.
        Reading it as 2013 turned a malformed "2025-13" into a confident 2025..2013."""
        assert parse_date("13") is None
        assert parse_date("'13") is not None


class TestPrecisionIsNeverInvented:
    @pytest.mark.parametrize(
        ("text", "precision"),
        [
            ("2025-03-15", Precision.EXACT),
            ("15 Mar 2025", Precision.EXACT),
            ("March 15, 2025", Precision.EXACT),
            ("Mar 2025", Precision.MONTH),
            ("06/2025", Precision.MONTH),
            ("2025", Precision.YEAR),
            ("Summer 2025", Precision.YEAR),
        ],
    )
    def test_precision_matches_what_the_document_committed_to(
        self, text: str, precision: Precision
    ) -> None:
        parsed = parse_date(text)
        assert parsed is not None
        assert parsed.precision is precision


class TestFailsVisibly:
    """An unrecognised format returns None. The caller drops the interval, keeps the
    claim, and the date-dependent rules abstain with that reason — rather than a
    confidently wrong date reaching the interval algebra."""

    @pytest.mark.parametrize(
        "text",
        [
            "sometime last year",
            "Q3",
            "1823",  # outside the contract's 1950-2100
            "Feb 30 2025",  # not a real day
            "2023 - 2021",  # inverted: a misparse, not a date
            "",
            "N/A",
        ],
    )
    def test_returns_none(self, text: str) -> None:
        assert parse_interval(text) is None


def test_a_single_date_is_a_point_not_an_open_range() -> None:
    """A graduation year is a year, not "2027 onwards"."""
    iv = parse_interval("2027")
    assert iv is not None
    assert iv.end is None
    assert iv.ongoing is False
