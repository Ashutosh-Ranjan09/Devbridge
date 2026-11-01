"""Hidden tests for lru_cache v1. The only scorer.

Reads params.json beside it — one variant's parameters, or a list of them when the
pattern is validated over every combination. Test names match the groups in
pattern.yaml; the report and calibration speak in those names.

Every expected answer is known by construction: the order of uses is chosen, so which
entry is least recently used is known without re-implementing a cache. Each test that
checks an eviction looks for the evicted key first, before any `get` refreshes another.
"""

import json
import pathlib
import random

import pytest
from solution import LRUCache

_raw = json.loads((pathlib.Path(__file__).parent / "params.json").read_text())
CASES = _raw if isinstance(_raw, list) else [_raw]
IDS = [f"{c['item_kind']}-{c['capacity']}-{c['twist']}" for c in CASES]
each = pytest.mark.parametrize("p", CASES, ids=IDS)


def key(kind, i):
    if kind == "user_session":
        return f"sess_{0x7F3A00 + 131 * i:06x}"
    if kind == "product_page":
        return f"/products/{1000 + 37 * i}"
    return f"host{i}.example.com"


def value(kind, i, version=1):
    """Distinct for every key and version, and never None."""
    if kind == "user_session":
        return {"user": f"user{i}", "version": version}
    if kind == "product_page":
        return f"<html>page {i} v{version}</html>"
    return f"203.0.{version}.{i % 250}"


def filled(p):
    """A cache at capacity, keys 0..c-1 used in that order: key 0 is least recent."""
    c, kind = p["capacity"], p["item_kind"]
    cache = LRUCache(c)
    for i in range(c):
        cache.put(key(kind, i), value(kind, i))
    return cache


@each
def test_get_returns_put_value(p):
    cache, kind = filled(p), p["item_kind"]
    for i in range(p["capacity"]):
        got = cache.get(key(kind, i))
        assert got == value(kind, i), f"get({key(kind, i)!r}): expected {value(kind, i)!r}, got {got!r}"


@each
def test_missing_is_none(p):
    c, kind = p["capacity"], p["item_kind"]
    cache = filled(p)
    assert cache.get("not-cached") is None, "a key never put must give None"
    assert len(cache) == c, f"a miss must not add the key: len is {len(cache)}, expected {c}"
    cache.put(key(kind, c), value(kind, c))                 # evicts key 0
    assert cache.get(key(kind, 0)) is None, f"{key(kind, 0)!r} was evicted, so get must give None"


@each
def test_evicts_least_recent(p):
    c, kind = p["capacity"], p["item_kind"]
    cache = filled(p)
    cache.put(key(kind, c), value(kind, c))
    assert cache.get(key(kind, 0)) is None, (
        f"keys were put in order 0..{c - 1}; adding a new key to the full cache must evict "
        f"the least recently used, {key(kind, 0)!r}"
    )
    for i in range(1, c + 1):
        assert cache.get(key(kind, i)) == value(kind, i), f"{key(kind, i)!r} should still be cached"
    assert len(cache) == c, f"len is {len(cache)}, expected {c}"


@each
def test_get_counts_as_use(p):
    c, kind = p["capacity"], p["item_kind"]
    cache = filled(p)
    cache.get(key(kind, 0))                                  # key 0 is now the most recent
    cache.put(key(kind, c), value(kind, c))
    assert cache.get(key(kind, 1)) is None, (
        f"after get({key(kind, 0)!r}) the least recently used is {key(kind, 1)!r}; it must be "
        "the one evicted"
    )
    assert cache.get(key(kind, 0)) == value(kind, 0), f"{key(kind, 0)!r} was just used and must stay"


@each
def test_put_existing_replaces_and_uses(p):
    c, kind = p["capacity"], p["item_kind"]
    # Replacing the least recent key makes it the most recent.
    cache = filled(p)
    cache.put(key(kind, 0), value(kind, 0, version=2))
    assert len(cache) == c, f"replacing a cached key must not change len: {len(cache)}, expected {c}"
    cache.put(key(kind, c), value(kind, c))
    assert cache.get(key(kind, 1)) is None, (
        f"after replacing {key(kind, 0)!r} the least recently used is {key(kind, 1)!r}; it must be evicted"
    )
    assert cache.get(key(kind, 0)) == value(kind, 0, version=2), "the replaced value must be returned"
    # Replacing a key that is not the least recent must evict nothing.
    cache = filled(p)
    cache.put(key(kind, c - 1), value(kind, c - 1, version=2))
    assert len(cache) == c, f"replacing never evicts: len is {len(cache)}, expected {c}"
    assert cache.get(key(kind, 0)) == value(kind, 0), f"{key(kind, 0)!r} must still be cached"


@each
def test_never_over_capacity(p):
    c, kind = p["capacity"], p["item_kind"]
    cache = LRUCache(c)
    for i in range(3 * c):
        cache.put(key(kind, i), value(kind, i))
        assert len(cache) == min(i + 1, c), (
            f"after {i + 1} distinct puts into a cache of {c}, len is {len(cache)}, expected {min(i + 1, c)}"
        )


@each
def test_many_operations_fast(p):
    """Constant time: a scan of the entries per call runs out the sandbox's time here,
    though it would pass every small case above."""
    kind, n = p["item_kind"], 50_000
    cache = LRUCache(n)
    for i in range(n):
        cache.put(key(kind, i), i)
    rng = random.Random(5)
    nxt = n
    for _ in range(150_000):
        if rng.random() < 0.5:
            cache.get(key(kind, rng.randrange(nxt - n, nxt)))
        else:
            cache.put(key(kind, nxt), nxt)
            nxt += 1
    assert len(cache) == n, f"len is {len(cache)}, expected {n}"
    assert cache.get(key(kind, nxt - 1)) == nxt - 1, "the last key put must be cached"


@each
def test_twist_behaviour(p):
    c, kind, twist = p["capacity"], p["item_kind"], p["twist"]
    if twist == "peek":
        cache = filled(p)
        assert cache.peek(key(kind, 0)) == value(kind, 0), f"peek({key(kind, 0)!r}) must return its value"
        assert cache.peek("not-cached") is None, "peek of a key never put must give None"
        cache.put(key(kind, c), value(kind, c))
        assert cache.get(key(kind, 0)) is None, (
            f"peek does not count as a use, so {key(kind, 0)!r} was still the least recent and must "
            "have been evicted"
        )
    elif twist == "delete":
        cache = filled(p)
        assert cache.delete(key(kind, 0)) is True, f"delete({key(kind, 0)!r}) of a cached key must return True"
        assert len(cache) == c - 1, f"after a delete, len is {len(cache)}, expected {c - 1}"
        assert cache.get(key(kind, 0)) is None, "a deleted key must give None"
        cache.put(key(kind, c), value(kind, c))
        assert len(cache) == c, f"the deleted entry's place was free: len is {len(cache)}, expected {c}"
        for i in range(1, c + 1):
            assert cache.get(key(kind, i)) == value(kind, i), f"nothing should have been evicted: {key(kind, i)!r} missing"
        assert cache.delete(key(kind, 0)) is False, "deleting a key not cached must return False"
    elif twist == "resize":
        cache = filled(p)
        cache.get(key(kind, 0))                              # the most recent now
        cache.resize(1)
        assert len(cache) == 1, f"after resize(1), len is {len(cache)}, expected 1"
        assert cache.get(key(kind, 0)) == value(kind, 0), "resize keeps the most recently used"
        cache.resize(c + 2)
        for i in range(c, 2 * c + 1):
            cache.put(key(kind, i), value(kind, i))
        assert len(cache) == c + 2, f"after growing to {c + 2}, len is {len(cache)}, expected {c + 2}"
        assert cache.get(key(kind, 0)) == value(kind, 0), "growing must not evict anything"
    else:
        pytest.fail(f"unknown twist {twist!r}")
