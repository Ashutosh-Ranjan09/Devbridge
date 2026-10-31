"""Visible examples for rate_limiter v1: the candidate's Run button. Never scored.

Cases read straight off the requirements, so a candidate can check they read them
right. Every edge the hidden tests probe (the exact boundary, rejected requests not
counting, the window sliding, rounding) is left to them. The reference passes these in
every combination; validation checks it.
"""

import json
import pathlib

import pytest
from solution import RateLimiter

_raw = json.loads((pathlib.Path(__file__).parent / "params.json").read_text())
CASES = _raw if isinstance(_raw, list) else [_raw]
IDS = [f"{c['key_kind']}-{c['limit']}-{c['window']}-{c['twist']}" for c in CASES]
each = pytest.mark.parametrize("p", CASES, ids=IDS)

KEY = {"ip_address": "192.0.2.10", "api_key": "key_test_A1", "user_email": "test@example.com"}


def fill(rl, p):
    for i in range(p["limit"]):
        r = rl.check(KEY[p["key_kind"]], 100 + i)
        assert r.status == 200, f"request {i + 1} of {p['limit']} at t={100 + i}: got {r.status}, expected 200"


@each
def test_example_within_the_limit(p):
    fill(RateLimiter(p["limit"], p["window"]), p)


@each
def test_example_over_the_limit(p):
    rl = RateLimiter(p["limit"], p["window"])
    fill(rl, p)
    r = rl.check(KEY[p["key_kind"]], 100 + p["limit"])
    assert r.status == 429, f"request {p['limit'] + 1} inside the window: got {r.status}, expected 429"


@each
def test_example_twist(p):
    rl, key = RateLimiter(p["limit"], p["window"]), KEY[p["key_kind"]]
    if p["twist"] == "remaining":
        got = rl.check(key, 100).headers.get("X-RateLimit-Remaining")
        want = str(p["limit"] - 1)
        assert got == want, f"X-RateLimit-Remaining after the first request: got {got!r}, expected {want!r}"
        return
    fill(rl, p)
    r = rl.check(key, 100 + p["limit"])
    if p["twist"] == "retry_after":
        want = str(p["window"] - p["limit"])                # whole seconds here; the hidden tests check rounding
        got = r.headers.get("Retry-After")
        assert got == want, f"Retry-After: got {got!r}, expected {want!r}"
    elif p["twist"] == "error_payload":
        want = {"error": "rate_limited", "key": key, "limit": p["limit"], "window": p["window"]}
        assert r.body == want, f"body: got {r.body!r}, expected {want!r}"
    else:
        pytest.fail(f"unknown twist {p['twist']!r}")
