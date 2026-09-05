"""The LeetCode connector, against recorded responses.

No network: respx intercepts the transport, so a test run needs no account, hits no
rate limit, and does not fail when LeetCode is down. The response shapes below are
the ones the real endpoint returns, including the two that are easy to get wrong —
"All" sitting alongside the per-difficulty rows, and a missing user arriving as
`matchedUser: null` with a 200 rather than as a 404.
"""

from __future__ import annotations

import httpx
import respx

from cvv.leetcode import ENDPOINT, _accepted, gather_leetcode
from cvv.models import Gap, GapReason, Platform, PlatformEvidence


def body(matched: dict | None, contest: dict | None = None) -> dict:
    return {"data": {"matchedUser": matched, "userContestRanking": contest}}


USER = {
    "username": "AR009",
    "profile": {"ranking": 184203},
    "submitStatsGlobal": {
        "acSubmissionNum": [
            {"difficulty": "All", "count": 412},
            {"difficulty": "Easy", "count": 190},
            {"difficulty": "Medium", "count": 190},
            {"difficulty": "Hard", "count": 32},
        ]
    },
}


class TestAcceptedCount:
    def test_reads_the_all_bucket_rather_than_summing(self) -> None:
        """LeetCode returns the total AND the per-difficulty rows. Summing the rows
        double-counts it, which inflates the observed number and makes an honest
        claim look understated — the one direction this system must never invent."""
        assert _accepted(USER) == 412

    def test_missing_statistics_are_none_not_zero(self) -> None:
        """None means not gathered; 0 means an account that has solved nothing.
        A rule must be able to tell those apart."""
        assert _accepted({"username": "x"}) is None
        assert _accepted({"submitStatsGlobal": {"acSubmissionNum": []}}) is None


class TestGatherLeetCode:
    @respx.mock
    def test_a_resolved_account(self) -> None:
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200, json=body(USER, {"attendedContestsCount": 12, "rating": 1687.42})
            )
        )
        result = gather_leetcode("ar009")
        assert isinstance(result, PlatformEvidence)
        assert result.platform is Platform.LEETCODE
        assert result.found and result.problems_solved == 412
        assert result.handle == "AR009", "the platform's casing, not the CV's"
        assert result.current_rating == 1687
        assert result.max_rating is None, (
            "LeetCode publishes a live rating and no peak; storing it as a peak would "
            "let a rule call a candidate an overstater for a rating that has fallen"
        )

    @respx.mock
    def test_a_missing_user_arrives_as_a_200_with_a_null(self) -> None:
        respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=body(None)))
        result = gather_leetcode("nobody-at-all")
        assert isinstance(result, Gap)
        assert result.reason is GapReason.NOT_FOUND
        assert "nobody-at-all" in (result.detail or "")

    @respx.mock
    def test_an_account_with_no_contest_history(self) -> None:
        respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=body(USER, None)))
        result = gather_leetcode("ar009")
        assert isinstance(result, PlatformEvidence)
        assert result.current_rating is None
        assert result.problems_solved == 412

    @respx.mock
    def test_a_block_is_a_typed_gap_and_never_an_exception(self) -> None:
        """One dead source must never fail the bundle. LeetCode answers a bare POST
        with 403, which is a throttle rather than a missing account."""
        respx.post(ENDPOINT).mock(return_value=httpx.Response(403, text="forbidden"))
        result = gather_leetcode("ar009")
        assert isinstance(result, Gap)
        assert result.reason is GapReason.RATE_LIMITED

    @respx.mock
    def test_a_transport_failure_is_a_typed_gap(self) -> None:
        respx.post(ENDPOINT).mock(side_effect=httpx.ConnectError("no route to host"))
        result = gather_leetcode("ar009")
        assert isinstance(result, Gap)
        assert result.reason is GapReason.UNREACHABLE
