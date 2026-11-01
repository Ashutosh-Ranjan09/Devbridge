"""MUTANT — alg "none" skips the signature. Must fail: alg_none_attack."""

import base64
import binascii
import hashlib
import hmac
import json
import re

_PART = re.compile(r"[A-Za-z0-9_-]*")


class InvalidToken(Exception):
    """Raised for any token that must not be trusted."""


def _decode(part: str) -> bytes:
    if not _PART.fullmatch(part):
        raise InvalidToken("not base64url")
    try:
        return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
    except (binascii.Error, ValueError) as exc:
        raise InvalidToken("not base64url") from exc


def _object(raw: bytes) -> dict:
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidToken("not JSON") from exc
    if not isinstance(value, dict):
        raise InvalidToken("not a JSON object")
    return value


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def verify(token: str, secret: bytes, now: int, leeway: int) -> dict:
    parts = token.split(".") if isinstance(token, str) else []
    if len(parts) != 3:
        raise InvalidToken("a JWT has three parts")
    head, body, sig = parts
    alg = _object(_decode(head)).get("alg")
    if str(alg).lower() == "none":
        return _object(_decode(body))
    if alg != "HS256":
        raise InvalidToken("alg must be HS256")
    expected = hmac.new(secret, f"{head}.{body}".encode("ascii"), hashlib.sha256).digest()
    if not hmac.compare_digest(expected, _decode(sig)):
        raise InvalidToken("bad signature")
    claims = _object(_decode(body))
    for name in ("exp", "nbf"):
        if name in claims and not _number(claims[name]):
            raise InvalidToken(f"{name} must be a number")
    if "exp" in claims and now >= claims["exp"] + leeway:
        raise InvalidToken("expired")
    if "nbf" in claims and now < claims["nbf"] - leeway:
        raise InvalidToken("not yet valid")
    return claims


def verify_audience(token: str, secret: bytes, now: int, leeway: int, audience: str) -> dict:
    claims = verify(token, secret, now, leeway)
    aud = claims.get("aud")
    if not (aud == audience or (isinstance(aud, list) and audience in aud)):
        raise InvalidToken("wrong audience")
    return claims


def verify_issuer(token: str, secret: bytes, now: int, leeway: int, issuer: str) -> dict:
    claims = verify(token, secret, now, leeway)
    if claims.get("iss") != issuer:
        raise InvalidToken("wrong issuer")
    return claims


def verify_required(token: str, secret: bytes, now: int, leeway: int, required: set[str]) -> dict:
    claims = verify(token, secret, now, leeway)
    if set(required) - claims.keys():
        raise InvalidToken("a required claim is missing")
    return claims
