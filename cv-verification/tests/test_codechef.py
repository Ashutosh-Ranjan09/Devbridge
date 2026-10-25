"""The CodeChef scraper, against a synthetic page with the real one's structure.

No network, and no real profile in the repository: the page below copies the shape
of codechef.com/users/<handle> — two rating blocks, the star spans, the embedded
`date_versus_rating` JSON — under a handle that belongs to nobody. The shapes that are
easy to get wrong are all here: the DSA rating block sitting beside the CodeChef one,
"NA" where an unrated account has no number, and a missing user arriving as a 200
redirect to the homepage rather than as a 404.
"""

from __future__ import annotations

import json

import httpx
import respx

from cvv.codechef import PROFILE, gather_codechef, parse_profile
from cvv.models import Gap, GapReason, Platform, PlatformEvidence, SourceQuality

HANDLE = "chef_test"
URL = PROFILE.format(handle=HANDLE)
HOME = "https://www.codechef.com/"

HISTORY = {
    "all": [
        {"code": "START101D", "getyear": "2025", "getmonth": "6", "getday": "4",
         "rating": "1393", "rank": "532", "name": "Starters 101 (Rated)"},
        {"code": "START102D", "getyear": "2025", "getmonth": "6", "getday": "11",
         "rating": "1612", "rank": "418", "name": "Starters 102 (Rated)"},
        {"code": "START103D", "getyear": "2025", "getmonth": "6", "getday": "18",
         "rating": "1580", "rank": "0", "name": "Starters 103 (Rated)"},
    ],
    "all_old": [],
}


def page(*, rating: str = "1580", highest: str = "1612", stars: int = 2,
         solved: str | None = "57", history: dict | None = HISTORY) -> str:
    star_spans = "".join('<span style="background-color:#666">&#9733;</span>'
                         for _ in range(stars))
    solved_h3 = f"<h3>Total Problems Solved: {solved}</h3>" if solved is not None else ""
    script = (f"<script>var userDailySubmissionsStats = {{}};"
              f'var all_rating = {{"date_versus_rating":{json.dumps(history)}}};</script>'
              if history is not None else "")
    return f"""<html><head><title>{HANDLE} | CodeChef User Profile</title></head><body>
<div id="rating-block-all"><div class="rating-header text-center">
  <div class="rating-number"> {rating} </div><div>(Div 3)</div>
  <div class="rating-star">{star_spans}</div>
  <a href="/ratings"><strong>CodeChef Rating</strong></a>
  <small>(Highest Rating {highest})</small>
</div></div>
<div id="rating-block-dsa"><div class="rating-header text-center">
  <div class="rating-number">NA</div><small>(Highest Rating 0)</small>
</div></div>
<section>{solved_h3}</section>{script}</body></html>"""


class TestParseProfile:
    def test_reads_every_field(self) -> None:
        evidence = parse_profile(HANDLE, page())
        assert isinstance(evidence, PlatformEvidence)
        assert evidence.platform is Platform.CODECHEF and evidence.found
        assert evidence.current_rating == 1580
        assert evidence.max_rating == 1612
        assert evidence.rank_title == "2★"
        assert evidence.problems_solved == 57
        assert evidence.source_quality is SourceQuality.SCRAPE, (
            "a scraped number must say so; P5 is attention-only because of it"
        )

    def test_the_dsa_block_is_not_the_codechef_rating(self) -> None:
        """The page carries two rating headers. Reading the second would record an
        unrated DSA block as the candidate's CodeChef rating."""
        evidence = parse_profile(HANDLE, page(rating="1580"))
        assert evidence is not None and evidence.current_rating == 1580

    def test_contest_history_is_decoded_from_the_embedded_json(self) -> None:
        evidence = parse_profile(HANDLE, page())
        assert evidence is not None
        assert [(c.name, c.rank) for c in evidence.contests] == [
            ("Starters 101 (Rated)", 532), ("Starters 102 (Rated)", 418),
        ], "a row with rank 0 carries no rank and is dropped, not recorded as rank 0"
        assert evidence.contests[0].rating_after == 1393
        assert evidence.contests[0].date is not None
        assert evidence.contests[0].date.isoformat() == "2025-06-04"

    def test_a_missing_field_is_none_never_zero(self) -> None:
        """None is "the page did not say"; 0 is "solved nothing". A rule must be able
        to tell those apart, or a redesign reads as a candidate who lied."""
        evidence = parse_profile(HANDLE, page(solved=None, rating="NA", stars=0))
        assert evidence is not None
        assert evidence.problems_solved is None
        assert evidence.current_rating is None
        assert evidence.rank_title is None

    def test_the_history_is_the_fallback_for_an_unstated_peak(self) -> None:
        evidence = parse_profile(HANDLE, page(highest="0"))
        assert evidence is not None and evidence.max_rating == 1612

    def test_a_page_that_is_not_a_profile_is_none(self) -> None:
        assert parse_profile(HANDLE, "<html><body><h1>Practice</h1></body></html>") is None

    def test_broken_embedded_json_leaves_the_header_readable(self) -> None:
        html = page(history=None) + '<script>"date_versus_rating":{"all":[{broken</script>'
        evidence = parse_profile(HANDLE, html)
        assert evidence is not None
        assert evidence.max_rating == 1612 and evidence.contests == []


class TestGatherCodeChef:
    @respx.mock
    def test_a_resolved_profile(self) -> None:
        respx.get(URL).mock(return_value=httpx.Response(200, text=page()))
        result = gather_codechef(HANDLE)
        assert isinstance(result, PlatformEvidence)
        assert result.max_rating == 1612

    @respx.mock
    def test_a_redirect_to_the_homepage_is_a_missing_user(self) -> None:
        """CodeChef answers an unknown handle with a 200 on its homepage, not a 404."""
        respx.get(URL).mock(return_value=httpx.Response(302, headers={"Location": HOME}))
        respx.get(HOME).mock(return_value=httpx.Response(200, text="<html>home</html>"))
        result = gather_codechef(HANDLE)
        assert isinstance(result, Gap)
        assert result.reason is GapReason.NOT_FOUND
        assert HANDLE in (result.detail or "")

    @respx.mock
    def test_a_redirect_anywhere_else_is_a_changed_site_not_a_missing_user(self) -> None:
        """If CodeChef moved its profiles, NOT_FOUND would tell every candidate their
        account does not exist. Only the homepage redirect means that."""
        moved = f"https://www.codechef.com/profile/{HANDLE}"
        respx.get(URL).mock(return_value=httpx.Response(301, headers={"Location": moved}))
        respx.get(moved).mock(return_value=httpx.Response(200, text=page()))
        result = gather_codechef(HANDLE)
        assert isinstance(result, Gap)
        assert result.reason is GapReason.NOT_SUPPLIED
        assert "changed its URLs" in (result.detail or "")

    @respx.mock
    def test_an_unrecognised_layout_is_a_gap_not_an_empty_profile(self) -> None:
        respx.get(URL).mock(return_value=httpx.Response(200, text="<html><body/></html>"))
        result = gather_codechef(HANDLE)
        assert isinstance(result, Gap)
        assert result.reason is GapReason.NOT_SUPPLIED
        assert "layout" in (result.detail or "")

    @respx.mock
    def test_a_throttle_is_rate_limited(self) -> None:
        respx.get(URL).mock(return_value=httpx.Response(429))
        result = gather_codechef(HANDLE)
        assert isinstance(result, Gap) and result.reason is GapReason.RATE_LIMITED

    @respx.mock
    def test_a_transport_failure_is_unreachable(self) -> None:
        respx.get(URL).mock(side_effect=httpx.ConnectError("no route to host"))
        result = gather_codechef(HANDLE)
        assert isinstance(result, Gap) and result.reason is GapReason.UNREACHABLE

    @respx.mock
    def test_a_page_is_cached_and_a_failure_is_not(self) -> None:
        route = respx.get(URL).mock(
            side_effect=[httpx.Response(503), httpx.Response(200, text=page())]
        )
        assert isinstance(gather_codechef(HANDLE), Gap)
        assert isinstance(gather_codechef(HANDLE), PlatformEvidence)
        assert isinstance(gather_codechef(HANDLE), PlatformEvidence)
        assert route.call_count == 2, "the 503 is retried; the page is served from disk"
