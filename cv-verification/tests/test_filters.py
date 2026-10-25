"""Every test here reproduces a failure a real model actually produced.

These are not hypotheticals. `qwen3:1.7b` and `qwen3:4b` generated each of these
outputs from the CV in conftest, and each one would have put a false decisive finding
in front of a reviewer.
"""

from __future__ import annotations

import pytest

from cvv import filters
from cvv.models import ClaimKind, Proficiency
from tests.cvdata import (
    AGGREGATE,
    CC_RATING,
    CF_RANK,
    CF_RATING,
    JEE,
    SKILLS_LINE,
    make_claim,
)


class TestExcludedExams:
    """X1 — entrance-rank comparison is excluded on fairness grounds: JEE cutoffs vary
    by reservation category, so a category-blind check flags valid ranks."""

    def test_jee_is_dropped_even_when_labelled_as_a_platform(self, document: str) -> None:
        """The failure exactly as observed: the model returned the JEE rank with
        `platform: "codeforces"`. A label-based filter cannot catch this — the model
        controls the label. Reading the verbatim can, because it cannot alter text it
        copied from the document."""
        claim = make_claim(JEE, document, platform="codeforces", metric="contest_rank", value=873)
        kept, dropped = filters.apply([claim])
        assert kept == []
        assert dropped["excluded_exam"] == 1

    def test_a_real_platform_claim_survives(self, document: str) -> None:
        claim = make_claim(
            CF_RATING, document, platform="codeforces", metric="max_rating", value=1495
        )
        kept, _ = filters.apply([claim])
        assert len(kept) == 1


class TestValueCorroboration:
    """THE failure. Given the whole document, qwen3:1.7b found one achievement and
    stamped its field values onto fourteen unrelated sentences.

    Grounding is structurally blind to this: every verbatim was genuine and 1495 was a
    genuine rating. Only the pairing was invented.
    """

    def test_a_value_absent_from_its_own_span_is_rejected(self, document: str) -> None:
        """1495 IS in the document — on a different line. That is not enough."""
        claim = make_claim(
            CF_RANK, document, platform="codeforces", metric="max_rating", value=1495
        )
        kept, dropped = filters.apply([claim])
        assert kept == []
        assert dropped["value_not_in_span"] == 1

    @pytest.mark.parametrize("truncated", [10, 110, 106])
    def test_a_number_inside_a_longer_one_is_not_in_the_span(
        self, document: str, truncated: int
    ) -> None:
        """10 is a substring of "1106" and is not in the sentence. As a contest rank,
        10 against a recorded 1109 would have been a decisive P2 contradiction."""
        claim = make_claim(
            CF_RANK, document, platform="codeforces", metric="contest_rank", value=truncated
        )
        kept, dropped = filters.apply([claim])
        assert kept == []
        assert dropped["value_not_in_span"] == 1

    def test_digit_grouping_is_read_as_one_number(self, document: str) -> None:
        """"38,000+" is 38000 — the comma groups digits, it does not split a number."""
        sentence = (
            "Ranked 1106 globally in Codeforces Round 998 (Div. 3), placing in the top 3% "
            "among 38,000+ competitve programmers worldwide"
        )
        claim = make_claim(
            sentence, document, platform="codeforces", metric="contest_rank", value=38000
        )
        kept, _ = filters.apply([claim])
        assert [c.value for c in kept] == [38000]

    def test_a_value_present_in_its_own_span_survives(self, document: str) -> None:
        claim = make_claim(
            CF_RANK, document, platform="codeforces", metric="contest_rank", value=1106
        )
        kept, _ = filters.apply([claim])
        assert len(kept) == 1
        assert kept[0].value == 1106


class TestPlatformCorrection:
    """The model labelled a CodeChef rating as `codeforces`. Left uncorrected, P1 would
    compare 1733 against the Codeforces API's 1495 and fire a decisive contradiction
    against an honest candidate."""

    def test_the_platform_is_read_from_the_span_not_the_label(self, document: str) -> None:
        claim = make_claim(
            CC_RATING, document, platform="codeforces", metric="max_rating", value=1733
        )
        kept, dropped = filters.apply([claim])
        assert len(kept) == 1
        assert kept[0].platform == "codechef"
        assert dropped["platform_corrected"] == 1

    def test_a_claim_naming_no_platform_is_unattributable(self, document: str) -> None:
        claim = make_claim(
            "top 0.5% among 1,80,000+ eligible candidates",
            document,
            platform="codeforces",
            metric="max_rating",
            # The number the span really holds, so the claim reaches the platform
            # check. It used to be 1, which passed the value check only because "1"
            # is a substring of "1,80,000".
            value=180000,
        )
        kept, dropped = filters.apply([claim])
        assert kept == []
        assert dropped["unattributable"] == 1


class TestAggregates:
    """"500+ problems across LeetCode, Codeforces and GeeksforGeeks" belongs to no
    single source. Comparing it to one platform compares the wrong things."""

    def test_a_multi_platform_claim_is_flagged_not_dropped(self, document: str) -> None:
        claim = make_claim(
            AGGREGATE, document, platform="leetcode", metric="problems_solved", value=500
        )
        kept, _ = filters.apply([claim])
        assert len(kept) == 1, "the claim is real; only the attribution is not"
        assert "aggregate_across_sources" in kept[0].flags
        assert (kept[0].context or {})["platforms"] == [
            "codeforces",
            "geeksforgeeks",
            "leetcode",
        ]

    def test_a_single_platform_claim_is_not_flagged(self, document: str) -> None:
        claim = make_claim(
            CF_RATING, document, platform="codeforces", metric="max_rating", value=1495
        )
        kept, _ = filters.apply([claim])
        assert "aggregate_across_sources" not in kept[0].flags


class TestProficiency:
    """The model labelled four skill claims `expert` — a word appearing nowhere in the
    CV. A band is a judgement about the candidate and must be the one their own
    sentence uses."""

    def test_an_invented_band_is_stripped(self, document: str) -> None:
        claim = make_claim(
            SKILLS_LINE,
            document,
            kind=ClaimKind.SKILL,
            proficiency=Proficiency.EXPERT,
            skill_refs=["c", "c++"],
        )
        kept, _ = filters.apply([claim])
        assert kept[0].proficiency is None, "'expert' is not in the document"

    def test_an_unstated_band_stays_none(self, document: str) -> None:
        claim = make_claim(
            CF_RATING, document, kind=ClaimKind.SKILL, skill_refs=["algorithms"]
        )
        kept, _ = filters.apply([claim])
        assert kept[0].proficiency is None


class TestDeduplication:
    """The model emitted the same rating claim five times with slightly different
    verbatims, which ground to different offsets and survive a span-keyed dedup."""

    def test_same_meaning_different_span_is_one_claim(self, document: str) -> None:
        a = make_claim(
            CF_RATING, document, claim_id="c001",
            platform="codeforces", metric="max_rating", value=1495,
        )
        b = make_claim(
            "peak Codeforces rating of 1495 (Specialist)", document, claim_id="c002",
            platform="codeforces", metric="max_rating", value=1495,
        )
        kept, dropped = filters.apply([a, b])
        assert len(kept) == 1
        assert dropped["duplicate"] == 1


class TestSpanConflicts:
    """The education pass returned projects as degrees, and the skills pass invented
    bands out of project prose. Two container claims over the same text is a
    classification conflict, and the more specific kind wins."""

    def test_the_more_specific_kind_wins_an_overlapping_span(self, document: str) -> None:
        achievement = make_claim(
            CF_RATING, document, claim_id="c001",
            platform="codeforces", metric="max_rating", value=1495,
        )
        education = make_claim(
            CF_RATING, document, claim_id="c002",
            kind=ClaimKind.EDUCATION, degree="Codeforces", org="Self Project",
        )
        kept, dropped = filters.apply([achievement, education])
        assert [c.kind for c in kept] == [ClaimKind.ACHIEVEMENT]
        assert dropped["span_conflict"] == 1

    def test_non_container_kinds_may_nest_freely(self, document: str) -> None:
        """A profile handle legitimately lives inside the achievement sentence that
        mentions it — that is not a conflict."""
        achievement = make_claim(
            CF_RATING, document, claim_id="c001",
            platform="codeforces", metric="max_rating", value=1495,
        )
        profile = make_claim(
            CF_RATING, document, claim_id="c002",
            kind=ClaimKind.PROFILE, platform="codeforces", handle="AR009",
        )
        kept, _ = filters.apply([achievement, profile])
        assert len(kept) == 2


@pytest.mark.parametrize(
    ("verbatim", "expected"),
    [
        (CF_RATING, {"codeforces"}),
        (CC_RATING, {"codechef"}),
        (AGGREGATE, {"codeforces", "geeksforgeeks", "leetcode"}),
        (JEE, set()),
    ],
)
def test_platforms_named(verbatim: str, expected: set[str]) -> None:
    assert filters.platforms_named(verbatim) == expected
