"""Hidden tests for jwt_verify v1. The only scorer.

Reads params.json beside it — one variant's parameters, or a list of them when the
pattern is validated over every combination. Test names match the groups in
pattern.yaml; the report and calibration speak in those names.

Every token is built here from chosen claims and a chosen secret, so whether it is valid
is known by construction. The leeway tests use the variant's leeway AND a second, larger
one: a solution that ignores the leeway would otherwise be right by accident wherever the
variant's leeway is 0.
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

NOW = 1_800_000_000
HEADER = {"alg": "HS256", "typ": "JWT"}


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def part(obj) -> str:
    return b64(json.dumps(obj, separators=(",", ":")).encode())


def sign(head: str, body: str, secret: bytes) -> str:
    return b64(hmac.new(secret, f"{head}.{body}".encode(), hashlib.sha256).digest())


def token(claims, secret: bytes, header=HEADER) -> str:
    head, body = part(header), part(claims)
    return f"{head}.{body}.{sign(head, body, secret)}"


def secret_of(p) -> bytes:
    return f"{p['service']}-signing-key".encode()


def claims_of(p, **extra) -> dict:
    return {"sub": "user-42", "role": "viewer", "iat": NOW - 60, "exp": NOW + 3600, **extra}


def refused(call, why: str) -> None:
    with pytest.raises(InvalidToken):
        call()
        pytest.fail(f"{why}: the token was accepted")


@each
def test_valid_token_returns_claims(p):
    claims = claims_of(p)
    got = verify(token(claims, secret_of(p)), secret_of(p), NOW, p["leeway"])
    assert got == claims, f"a valid token must return its claims: expected {claims}, got {got}"


@each
def test_wrong_secret(p):
    t = token(claims_of(p), b"someone-elses-key")
    refused(lambda: verify(t, secret_of(p), NOW, p["leeway"]), "signed with another secret")


@each
def test_tampered_payload(p):
    head, _body, sig = token(claims_of(p), secret_of(p)).split(".")
    forged = f"{head}.{part(claims_of(p, role='admin'))}.{sig}"
    refused(lambda: verify(forged, secret_of(p), NOW, p["leeway"]), "the payload was changed after signing")


@each
def test_alg_none_attack(p):
    body = part(claims_of(p))
    for alg in ("none", "None", "NONE"):
        head = part({"alg": alg, "typ": "JWT"})
        refused(lambda: verify(f"{head}.{body}.", secret_of(p), NOW, p["leeway"]),
                f'alg "{alg}" with no signature (the classic attack)')


@each
def test_other_alg_refused(p):
    for header in ({"alg": "HS512", "typ": "JWT"}, {"typ": "JWT"}):
        t = token(claims_of(p), secret_of(p), header)             # a valid HS256 signature
        refused(lambda: verify(t, secret_of(p), NOW, p["leeway"]), f"header {header} is not HS256")


@each
def test_expiry_with_leeway(p):
    for leeway in (p["leeway"], p["leeway"] + 15):
        t = token(claims_of(p, exp=NOW), secret_of(p))
        got = verify(t, secret_of(p), NOW + leeway - 1, leeway)
        assert got["exp"] == NOW, f"exp={NOW}, leeway {leeway}: still valid at now={NOW + leeway - 1}"
        refused(lambda: verify(t, secret_of(p), NOW + leeway, leeway),
                f"exp={NOW}, leeway {leeway}: expired at now={NOW + leeway}")


@each
def test_not_before_with_leeway(p):
    for leeway in (p["leeway"], p["leeway"] + 15):
        t = token(claims_of(p, nbf=NOW), secret_of(p))
        refused(lambda: verify(t, secret_of(p), NOW - leeway - 1, leeway),
                f"nbf={NOW}, leeway {leeway}: not yet valid at now={NOW - leeway - 1}")
        got = verify(t, secret_of(p), NOW - leeway, leeway)
        assert got["nbf"] == NOW, f"nbf={NOW}, leeway {leeway}: valid from now={NOW - leeway}"


@each
def test_malformed_tokens(p):
    s = secret_of(p)
    good = token(claims_of(p), s)
    head = part(HEADER)

    def signed(body: str) -> str:
        return f"{head}.{body}.{sign(head, body, s)}"

    cases = {
        "two parts": ".".join(good.split(".")[:2]),
        "four parts": good + ".extra",
        "a character outside base64url": good.replace(".", ".!", 1),
        "a payload that is a JSON list": signed(b64(b"[1, 2, 3]")),
        "a payload that is not JSON": signed(b64(b"definitely not json")),
        "an exp that is not a number": signed(part(claims_of(p, exp="tomorrow"))),
        "a header that is not JSON": f"{b64(b'oops')}.{part(claims_of(p))}.x",
    }
    for what, bad in cases.items():
        refused(lambda: verify(bad, s, NOW, p["leeway"]), f"{what} must raise InvalidToken")


def _claims_needing(pad: int, p) -> dict:
    """Claims whose encoding needs `pad` '=' characters and uses '-' or '_'."""
    for n in range(300):
        claims = claims_of(p, note="~?>" * (n // 3) + "~?>"[: n % 3])
        raw = json.dumps(claims, separators=(",", ":")).encode()
        enc = b64(raw)
        if (-len(raw) % 3) == pad and ("-" in enc or "_" in enc):
            return claims
    raise AssertionError("no such claims")                      # never: chosen by search


@each
def test_base64url_without_padding(p):
    for pad in (1, 2):
        claims = _claims_needing(pad, p)
        got = verify(token(claims, secret_of(p)), secret_of(p), NOW, p["leeway"])
        assert got == claims, f"a payload needing {pad} padding character(s), with - or _, must decode"


@each
def test_twist_behaviour(p):
    s, lw, twist = secret_of(p), p["leeway"], p["twist"]
    audience = p["service"].replace("_", "-")
    issuer = f"https://auth.{p['service'].replace('_', '-')}.example"
    if twist == "audience":
        ok = solution.verify_audience(token(claims_of(p, aud=audience), s), s, NOW, lw, audience)
        assert ok["aud"] == audience, "aud equal to the audience is accepted"
        listed = solution.verify_audience(token(claims_of(p, aud=["reports", audience]), s), s, NOW, lw, audience)
        assert listed["aud"] == ["reports", audience], "a list containing the audience is accepted"
        for aud in ("reports", ["reports", "search"]):
            t = token(claims_of(p, aud=aud), s)
            refused(lambda: solution.verify_audience(t, s, NOW, lw, audience), f"aud {aud!r} does not name {audience!r}")
        t = token(claims_of(p), s)
        refused(lambda: solution.verify_audience(t, s, NOW, lw, audience), "a token without aud")
        t = token(claims_of(p, aud=audience), b"someone-elses-key")
        refused(lambda: solution.verify_audience(t, s, NOW, lw, audience), "the signature still has to hold")
    elif twist == "issuer":
        ok = solution.verify_issuer(token(claims_of(p, iss=issuer), s), s, NOW, lw, issuer)
        assert ok["iss"] == issuer, "the exact issuer is accepted"
        for iss in (issuer + "/", issuer.upper(), "https://evil.example"):
            t = token(claims_of(p, iss=iss), s)
            refused(lambda: solution.verify_issuer(t, s, NOW, lw, issuer), f"iss {iss!r} is not exactly {issuer!r}")
        t = token(claims_of(p), s)
        refused(lambda: solution.verify_issuer(t, s, NOW, lw, issuer), "a token without iss")
    elif twist == "required":
        need = {"sub", "role", "exp"}
        ok = solution.verify_required(token(claims_of(p), s), s, NOW, lw, need)
        assert ok["role"] == "viewer", "all required claims present: accepted"
        claims = claims_of(p)
        del claims["role"]
        t = token(claims, s)
        refused(lambda: solution.verify_required(t, s, NOW, lw, need), "the required claim 'role' is missing")
        t = token(claims_of(p), b"someone-elses-key")
        refused(lambda: solution.verify_required(t, s, NOW, lw, need), "the signature still has to hold")
    else:
        pytest.fail(f"unknown twist {twist!r}")
