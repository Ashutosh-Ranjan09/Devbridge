"""The Codeforces connector's answers, against recorded responses (respx: no network).

Codeforces says "no such user" with HTTP 400 and a JSON body, not a 404. Read as an
HTTP error, that was "unreachable" — a transient gap that marked the report degraded
and asked for a re-run that could never help.
"""

from __future__ import annotations

import httpx
import respx

from cvv.gather import CODEFORCES_API, gather_codeforces
from cvv.models import Gap, GapReason


@respx.mock
def test_an_unknown_handle_is_not_found_not_unreachable() -> None:
    respx.get(f"{CODEFORCES_API}/user.info").mock(
        return_value=httpx.Response(
            400, json={"status": "FAILED", "comment": "handles: User with handle nobody_x not found"}
        )
    )
    gap = gather_codeforces("nobody_x")
    assert isinstance(gap, Gap)
    assert gap.reason is GapReason.NOT_FOUND
    assert gap.detail is not None and "codeforces.com/profile/nobody_x" in gap.detail


@respx.mock
def test_a_400_that_is_not_the_platforms_answer_is_still_unreachable() -> None:
    """A proxy's HTML error page is the network, not Codeforces saying no."""
    respx.get(f"{CODEFORCES_API}/user.info").mock(return_value=httpx.Response(400, text="<html>bad gateway</html>"))
    gap = gather_codeforces("ar009")
    assert isinstance(gap, Gap) and gap.reason is GapReason.UNREACHABLE


@respx.mock
def test_rate_limiting_stays_a_transient_gap() -> None:
    respx.get(f"{CODEFORCES_API}/user.info").mock(return_value=httpx.Response(429))
    gap = gather_codeforces("ar009")
    assert isinstance(gap, Gap) and gap.reason is GapReason.RATE_LIMITED
