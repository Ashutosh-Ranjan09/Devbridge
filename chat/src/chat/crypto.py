"""Messages are encrypted at rest: AES-256-GCM, a fresh random nonce each time, the key
from CHAT_ENCRYPTION_KEY.

What this protects: a copy of chat.db — a backup, a stolen disk — reads as noise without
the key. What it does not: this process decrypts to answer the web, so whoever runs it
can read every message. Encryption at rest, not end to end; say so wherever it is
described.

Each ciphertext is bound to where it is stored (`aad`: the thread and the message id), so
a row copied onto another thread fails to open instead of appearing there.
"""

from __future__ import annotations

import base64
import binascii
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION = b"\x01"          # so a second scheme can be told from this one
NONCE = 12


class MissingKeyError(Exception):
    """No key, or not one this module can use."""


def load_key(encoded: str | None) -> bytes:
    if not encoded:
        raise MissingKeyError("CHAT_ENCRYPTION_KEY is unset: `uv run chat keygen` prints one for chat/.env")
    try:
        key = base64.urlsafe_b64decode(encoded)
    except (binascii.Error, ValueError) as exc:
        raise MissingKeyError("CHAT_ENCRYPTION_KEY is not base64") from exc
    if len(key) != 32:
        raise MissingKeyError("CHAT_ENCRYPTION_KEY must be 32 bytes, base64")
    return key


def new_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


class Box:
    def __init__(self, key: bytes) -> None:
        self._aes = AESGCM(key)

    def seal(self, plain: bytes, aad: str) -> bytes:
        nonce = os.urandom(NONCE)
        return VERSION + nonce + self._aes.encrypt(nonce, plain, aad.encode())

    def open(self, sealed: bytes, aad: str) -> bytes:
        """Raises `cryptography.exceptions.InvalidTag` when the bytes were changed, moved,
        or sealed with another key: never returns something else."""
        if sealed[:1] != VERSION:
            raise ValueError("unknown ciphertext version")
        return self._aes.decrypt(sealed[1:1 + NONCE], sealed[1 + NONCE:], aad.encode())
