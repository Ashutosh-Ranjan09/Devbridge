"""Stable id derivation.

The same input must give the same id on a re-run months later. An unstable claim_id
silently breaks temporal self-diff: every claim in the new report looks new.

Nothing here may read the clock, a random source, or an unordered collection.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

_DIGEST_CHARS = 10  # 40 bits, and ids are scoped to one graph or report


def _digest(*parts: str) -> str:
    # sha1 as a checksum, not a security primitive. usedforsecurity=False keeps this
    # working on FIPS-restricted builds, where a bare sha1() call raises.
    return hashlib.sha1(
        "|".join(parts).encode("utf-8"), usedforsecurity=False
    ).hexdigest()[:_DIGEST_CHARS]


def stable_id(*parts: str) -> str:
    """A short, stable id from any parts. Used where the caller owns the meaning —
    a verification id from a uuid, a webhook id from its URL."""
    return _digest(*parts)


def claim_id(graph_id: str, char_start: int, kind: str, discriminator: str = "") -> str:
    """Identity is (position, kind, discriminator).

    The discriminator is load-bearing: one line — "Proficient - C | C++  Familiar -
    TypeScript" — yields several skill claims sharing a span and a kind, and without
    it they collide onto one id and overwrite each other.
    """
    return "c" + _digest(graph_id, str(char_start), str(kind), discriminator)


def finding_id(report_id: str, rule_id: str, claim_refs: Iterable[str]) -> str:
    """Sorted, so the id does not depend on the order a rule yielded its refs in."""
    return "f" + _digest(report_id, rule_id, ",".join(sorted(claim_refs)))
