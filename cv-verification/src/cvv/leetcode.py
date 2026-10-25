"""LeetCode, over its public GraphQL endpoint.

No key and no account needed — the same query the profile page itself issues. That
makes it the second source in this system that can settle a claim outright rather
than merely fail to corroborate it, which is why it is worth the connector.

What it can answer: how many problems the account has accepted, and its contest
rating and attendance. What it cannot: who owns the account. Ownership is G3's
problem and is unsolvable from public data on any platform.
"""

from __future__ import annotations

import hashlib
from typing import Any

import httpx

from cvv import cache
from cvv.models import Gap, GapReason, Platform, PlatformEvidence

ENDPOINT = "https://leetcode.com/graphql"
SOURCE = Platform.LEETCODE.value

# Both headers matter. LeetCode answers a bare POST with 403; it wants a browser-ish
# User-Agent and a Referer from its own origin.
HEADERS = {
    "User-Agent": "cvv/0.1 (CV verification research; contact via repository)",
    "Referer": "https://leetcode.com",
    "Content-Type": "application/json",
}

QUERY = """
query cvvUserProfile($username: String!) {
  matchedUser(username: $username) {
    username
    profile { ranking }
    submitStatsGlobal { acSubmissionNum { difficulty count } }
  }
  userContestRanking(username: $username) {
    attendedContestsCount
    rating
    globalRanking
  }
}
"""


def _cache_key(handle: str) -> str:
    """The handle, and a fingerprint of the query that produced the body.

    Without the fingerprint, changing QUERY would silently serve responses shaped by
    the old one for the rest of the TTL — a cache returning the right answer to a
    question nobody asked any more. The handle keeps its casing: LeetCode treats
    usernames as distinct, and folding them here would serve one account's numbers
    under another's name.
    """
    digest = hashlib.sha256(QUERY.encode()).hexdigest()[:8]
    return f"userProfile:{digest}:{handle}"


def _fetch(handle: str) -> Any | Gap:
    """The cached body, or one request. Failures are never cached.

    A 403 is a throttle and a timeout is a network, and storing either for seven days
    would turn a momentary problem into a week of false gaps.
    """
    key = _cache_key(handle)
    if (hit := cache.get(SOURCE, key)) is not None:
        return hit

    try:
        response = httpx.post(
            ENDPOINT,
            json={"query": QUERY, "variables": {"username": handle}},
            headers=HEADERS,
            timeout=30.0,
            follow_redirects=True,
        )
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPStatusError as exc:
        reason = (
            GapReason.RATE_LIMITED
            if exc.response.status_code in (429, 403)
            else GapReason.UNREACHABLE
        )
        return Gap(source=SOURCE, reason=reason, detail=str(exc))
    except (httpx.HTTPError, ValueError) as exc:
        return Gap(source=SOURCE, reason=GapReason.UNREACHABLE, detail=str(exc))

    # A missing account comes back as a 200 with `matchedUser: null`, so it is a
    # legitimate body and is cached like any other — an account that does not exist
    # today will not exist in an hour either.
    cache.put(SOURCE, key, body)
    return body


def _accepted(matched: dict[str, Any]) -> int | None:
    """The "All" bucket of acSubmissionNum — distinct problems accepted.

    LeetCode returns one row per difficulty plus an "All" total. Summing the
    difficulty rows would double-count it, which would inflate the observed number
    and make an honest claim look understated.
    """
    stats = (matched.get("submitStatsGlobal") or {}).get("acSubmissionNum") or []
    for row in stats:
        if row.get("difficulty") == "All":
            count = row.get("count")
            return int(count) if count is not None else None
    return None


def gather_leetcode(handle: str) -> PlatformEvidence | Gap:
    """One POST, cached for seven days like every other source here.

    A missing user comes back as `matchedUser: null` with HTTP 200, not as a 404.
    """
    body = _fetch(handle)
    if isinstance(body, Gap):
        return body

    data = body.get("data") or {}
    matched = data.get("matchedUser")
    if not matched:
        return Gap(
            source=SOURCE,
            reason=GapReason.NOT_FOUND,
            detail=f"No LeetCode account exists at leetcode.com/u/{handle}.",
        )

    contest = data.get("userContestRanking") or {}
    rating = contest.get("rating")
    return PlatformEvidence(
        platform=Platform.LEETCODE,
        # The platform's own casing, not the CV's.
        handle=str(matched.get("username") or handle),
        found=True,
        # LeetCode reports a live contest rating and no peak. Recording it as
        # `max_rating` would let a rule call a candidate an overstater for a rating
        # that has since fallen, which is exactly the P1 direction asymmetry
        # inverted. It is a current value and it is stored as one.
        current_rating=round(float(rating)) if rating is not None else None,
        max_rating=None,
        problems_solved=_accepted(matched),
        contests=[],
    )
