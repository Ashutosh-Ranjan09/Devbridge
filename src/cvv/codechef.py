"""CodeChef, read from the public profile page — the one SCRAPED source in the system.

CodeChef publishes no API. The profile page at /users/<handle> carries what P5 needs:
the highest rating in its header, the rated-contest history as JSON embedded in the
page (`date_versus_rating`), and a problems-solved total. robots.txt permits /users/
and disallows /recent/user, so only the profile page is read: one request, cached.

A scraper fails by answering WRONGLY, silently, after a redesign. Three guards:
  - a field the page does not carry is None, never a default;
  - the page must be recognisably a profile, or the result is a Gap saying the layout
    was not recognised — never an empty profile that reads as "solved nothing";
  - every result says source_quality=SCRAPE, and P5 is attention-only because of it.
"""

from __future__ import annotations

import datetime
import json
import re
from typing import Any

import httpx
from selectolax.lexbor import LexborHTMLParser

from cvv import cache
from cvv.models import (
    ContestResult,
    Gap,
    GapReason,
    Platform,
    PlatformEvidence,
    SourceQuality,
)

PROFILE = "https://www.codechef.com/users/{handle}"
SOURCE = Platform.CODECHEF.value
USER_AGENT = "cvv/0.1 (CV verification research; contact via repository)"

# The page carries two rating blocks — the CodeChef rating and a separate DSA rating.
# Only the first is the rating a CV means by "CodeChef rating".
RATING_BLOCK = "#rating-block-all .rating-header"


def _number(text: str) -> int | None:
    """The first whole number in the text; None for "NA", "Inactive" and the like."""
    found = re.search(r"\d+", text.replace(",", ""))
    return int(found.group()) if found else None


def _history(html: str) -> list[dict[str, Any]] | None:
    """The rated-contest history CodeChef embeds as JSON, decoded as JSON."""
    marker = '"date_versus_rating":'
    at = html.find(marker)
    if at == -1:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(html, at + len(marker))
    except ValueError:
        return None
    rows = data.get("all") if isinstance(data, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else None


def _contest(row: dict[str, Any]) -> ContestResult | None:
    """One history row, or None if it does not carry a usable rank."""
    try:
        rank = int(row["rank"])
        name = str(row["name"])
    except (KeyError, TypeError, ValueError):
        return None
    if rank < 1:
        return None
    try:
        date = datetime.date(int(row["getyear"]), int(row["getmonth"]), int(row["getday"]))
    except (KeyError, TypeError, ValueError):
        date = None
    try:
        rating = int(row["rating"])
    except (KeyError, TypeError, ValueError):
        rating = None
    return ContestResult(name=name, rank=rank, date=date, rating_after=rating)


def parse_profile(handle: str, html: str) -> PlatformEvidence | None:
    """The page to evidence. Pure — no network. None when it is not a profile page."""
    tree = LexborHTMLParser(html)
    header = tree.css_first(RATING_BLOCK) or tree.css_first(".rating-header")
    history = _history(html)
    if header is None and history is None:
        return None

    rating = header.css_first(".rating-number") if header else None
    highest = header.css_first("small") if header else None
    stars = len(header.css(".rating-star span")) if header else 0
    solved = next((h.text() for h in tree.css("h3") if "Problems Solved" in h.text()), None)

    contests = [c for c in (_contest(r) for r in history or []) if c is not None]
    # The header states the peak; the history is the fallback, never a guess. A
    # stated peak of 0 is an unrated account, not a rating.
    peak = _number(highest.text()) if highest else None
    if not peak:
        peak = max((c.rating_after for c in contests if c.rating_after), default=None)

    return PlatformEvidence(
        platform=Platform.CODECHEF,
        handle=handle,
        found=True,
        current_rating=_number(rating.text()) if rating else None,
        max_rating=peak,
        rank_title=f"{stars}★" if stars else None,
        problems_solved=_number(solved) if solved else None,
        contests=contests,
        source_quality=SourceQuality.SCRAPE,
    )


def _fetch(handle: str) -> str | Gap:
    """The cached page, or one request. Failures and missing users are never cached."""
    key = f"profile:{handle}"
    if isinstance(hit := cache.get(SOURCE, key), str):
        return hit

    try:
        response = httpx.get(
            PROFILE.format(handle=handle),
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
    except httpx.HTTPError as exc:
        return Gap(source=SOURCE, reason=GapReason.UNREACHABLE, detail=str(exc))
    if response.status_code == 429:
        return Gap(source=SOURCE, reason=GapReason.RATE_LIMITED, detail="CodeChef returned 429.")
    if response.status_code >= 400:
        return Gap(
            source=SOURCE,
            reason=GapReason.UNREACHABLE,
            detail=f"CodeChef returned {response.status_code}.",
        )

    # An unknown user is HTTP 200 and a redirect to the homepage, not a 404. Only
    # that redirect means "no such user": landing anywhere else means CodeChef moved
    # its pages, and calling that NOT_FOUND would tell every candidate their account
    # does not exist.
    path = response.url.path.rstrip("/").lower()
    if path == "":
        return Gap(
            source=SOURCE,
            reason=GapReason.NOT_FOUND,
            detail=f"CodeChef has no user {handle!r}: its profile URL redirects to the "
            "homepage.",
        )
    if not path.endswith(f"/users/{handle.lower()}"):
        return Gap(
            source=SOURCE,
            reason=GapReason.NOT_SUPPLIED,
            detail=f"CodeChef redirected the profile for {handle!r} to "
            f"{response.url.path!r}, which this scraper does not recognise. CodeChef "
            "may have changed its URLs.",
        )

    cache.put(SOURCE, key, response.text)
    return response.text


def gather_codechef(handle: str) -> PlatformEvidence | Gap:
    """One GET, cached for seven days like every other platform here."""
    html = _fetch(handle)
    if isinstance(html, Gap):
        return html
    evidence = parse_profile(handle, html)
    if evidence is None:
        return Gap(
            source=SOURCE,
            reason=GapReason.NOT_SUPPLIED,
            detail=f"The CodeChef page for {handle!r} did not have the layout this "
            "scraper reads, so nothing was taken from it. CodeChef may have "
            "redesigned it.",
        )
    return evidence
