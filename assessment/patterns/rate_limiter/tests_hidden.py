"""Hidden tests for rate_limiter v1. The only scorer.

Reads params.json beside it — one variant's parameters, or a list of them when the
pattern is validated over every combination. Test names match the groups in
pattern.yaml; the report and calibration speak in those names.

Times are integers except where rounding is the point, and T0 is chosen so that no
window starts on a multiple of its own length: a fixed-window counter, which resets
on the clock, is then caught by `exact_boundary` in every combination.
"""

import json
import math
import pathlib

import pytest
from solution import RateLimiter

_raw = json.loads((pathlib.Path(__file__).parent / "params.json").read_text())
CASES = _raw if isinstance(_raw, list) else [_raw]
IDS = [f"{c['key_kind']}-{c['limit']}-{c['window']}-{c['twist']}" for c in CASES]
each = pytest.mark.parametrize("p", CASES, ids=IDS)

T0 = 1_000_000
KEYS = {
    "ip_address": ("203.0.113.7", "198.51.100.23"),
    "api_key": ("key_live_7Hf2", "key_live_Q9a1"),
    "user_email": ("asha@example.com", "ravi@example.com"),
}


def fill(rl, key, p, start=T0):
    """Use up a key's whole allowance, one request a second."""
    for i in range(p["limit"]):
        r = rl.check(key, start + i)
        assert r.status == 200, f"request {i + 1} of {p['limit']} at t={start + i} was refused"


@each
def test_allows_up_to_limit(p):
    rl = RateLimiter(p["limit"], p["window"])
    fill(rl, KEYS[p["key_kind"]][0], p)


@each
def test_rejects_one_over(p):
    rl = RateLimiter(p["limit"], p["window"])
    key = KEYS[p["key_kind"]][0]
    fill(rl, key, p)
    assert rl.check(key, T0 + p["limit"]).status == 429, "the request over the limit was allowed"
    assert rl.check(key, T0 + p["limit"] + 1).status == 429, "a second request over the limit was allowed"


@each
def test_keys_independent(p):
    rl = RateLimiter(p["limit"], p["window"])
    a, b = KEYS[p["key_kind"]]
    fill(rl, a, p)
    fill(rl, b, p, start=T0 + p["limit"])
    assert rl.check(a, T0 + 2 * p["limit"]).status == 429, "one key's allowance was shared with another"


@each
def test_exact_boundary(p):
    rl = RateLimiter(p["limit"], p["window"])
    key = KEYS[p["key_kind"]][0]
    fill(rl, key, p)
    for t in range(T0 + p["limit"], T0 + p["limit"] + 3):     # rejected; must not count
        rl.check(key, t)
    w = p["window"]
    assert rl.check(key, T0 + w - 1).status == 429, (
        f"at t={T0 + w - 1} the first request (t={T0}) still counts, so this must be refused"
    )
    assert rl.check(key, T0 + w).status == 200, (
        f"at t={T0 + w} the first request (t={T0}) no longer counts, so one slot is free"
    )
    assert rl.check(key, T0 + w).status == 429, "only one slot freed at that moment"


@each
def test_window_slides(p):
    rl = RateLimiter(p["limit"], p["window"])
    key = KEYS[p["key_kind"]][0]
    fill(rl, key, p)
    later = T0 + p["limit"] - 1 + p["window"]                 # every earlier request has expired
    for i in range(p["limit"]):
        assert rl.check(key, later).status == 200, f"request {i + 1} after the window passed was refused"
    assert rl.check(key, later).status == 429, "the allowance renewed beyond the limit"


@each
def test_twist_behaviour(p):
    rl = RateLimiter(p["limit"], p["window"])
    key = KEYS[p["key_kind"]][0]
    twist = p["twist"]
    if twist == "retry_after":
        fill(rl, key, p)
        now = T0 + p["limit"] + 0.5
        r = rl.check(key, now)
        assert r.status == 429
        expected = math.ceil(T0 + p["window"] - now)
        assert str(r.headers.get("Retry-After")) == str(expected), (
            f"Retry-After was {r.headers.get('Retry-After')!r}; the first request frees at "
            f"t={T0 + p['window']}, {T0 + p['window'] - now}s away, rounded up to {expected}"
        )
    elif twist == "remaining":
        for i in range(p["limit"]):
            r = rl.check(key, T0 + i)
            assert r.headers.get("X-RateLimit-Remaining") == str(p["limit"] - i - 1), (
                f"after request {i + 1} of {p['limit']}, {p['limit'] - i - 1} remain"
            )
        r = rl.check(key, T0 + p["limit"])
        assert r.status == 429 and r.headers.get("X-RateLimit-Remaining") == "0"
    elif twist == "error_payload":
        fill(rl, key, p)
        r = rl.check(key, T0 + p["limit"])
        assert r.status == 429
        assert r.body == {"error": "rate_limited", "key": key, "limit": p["limit"], "window": p["window"]}
    else:
        pytest.fail(f"unknown twist {twist!r}")
