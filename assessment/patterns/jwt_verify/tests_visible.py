"""Visible examples for jwt_verify v1: the candidate's Run button. Never scored.

Small cases read straight off the requirements, so a candidate can check they read them
right. Everything the hidden tests probe beyond these (alg "none", a tampered payload,
the leeway at its exact edges, malformed tokens, base64url without padding) is left to
them. The reference passes these in every combination; validation checks it.
"""

import base64
import hashlib
import hmac
import json
import pathlib

import pytest
import solution
from solution import InvalidToken, verify

_raw = json.loads((pathlib.Path(__file__).parent / "params.json").read_text())
CASES = _raw if isinstance(_raw, list) else [_raw]
IDS = [f"{c['service']}-{c['leeway']}-{c['twist']}" for c in CASES]
each = pytest.mark.parametrize("p", CASES, ids=IDS)

SECRET = b"example-secret"
NOW = 1_700_000_000


def make(claims, secret=SECRET):
    enc = lambda obj: base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()  # noqa: E731
    head, body = enc({"alg": "HS256", "typ": "JWT"}), enc(claims)
    sig = base64.urlsafe_b64encode(hmac.new(secret, f"{head}.{body}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{head}.{body}.{sig}"


@each
def test_example_valid(p):
    claims = {"sub": "user-1", "exp": NOW + 600}
    got = verify(make(claims), SECRET, NOW, 0)
    assert got == claims, f"a correctly signed, unexpired token should return its claims: got {got!r}"


@each
def test_example_wrong_secret(p):
    with pytest.raises(InvalidToken):
        verify(make({"sub": "user-1"}, b"another-secret"), SECRET, NOW, 0)


@each
def test_example_twist(p):
    if p["twist"] == "audience":
        got = solution.verify_audience(make({"sub": "u", "aud": "api"}), SECRET, NOW, 0, "api")
        assert got["aud"] == "api", "aud 'api' should be accepted for audience 'api'"
    elif p["twist"] == "issuer":
        got = solution.verify_issuer(make({"sub": "u", "iss": "https://auth.example"}), SECRET, NOW, 0, "https://auth.example")
        assert got["iss"] == "https://auth.example", "the exact issuer should be accepted"
    elif p["twist"] == "required":
        with pytest.raises(InvalidToken):
            solution.verify_required(make({"sub": "u"}), SECRET, NOW, 0, {"sub", "role"})
    else:
        pytest.fail(f"unknown twist {p['twist']!r}")
