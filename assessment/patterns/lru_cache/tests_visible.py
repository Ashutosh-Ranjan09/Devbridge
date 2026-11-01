"""Visible examples for lru_cache v1: the candidate's Run button. Never scored.

Small cases read straight off the requirements, so a candidate can check they read
them right. Everything the hidden tests probe beyond these (a miss adding nothing,
replacing a key, the cache never growing past its capacity, a large cache in constant
time) is left to them. The reference passes these in every combination; validation
checks it.
"""

import json
import pathlib

import pytest
from solution import LRUCache

_raw = json.loads((pathlib.Path(__file__).parent / "params.json").read_text())
CASES = _raw if isinstance(_raw, list) else [_raw]
IDS = [f"{c['item_kind']}-{c['capacity']}-{c['twist']}" for c in CASES]
each = pytest.mark.parametrize("p", CASES, ids=IDS)


@each
def test_example_put_then_get(p):
    cache = LRUCache(2)
    cache.put("a", 1)
    assert cache.get("a") == 1, "put('a', 1) then get('a') should give 1"
    assert cache.get("b") is None, "get('b') of a key never put should give None"


@each
def test_example_eviction(p):
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("a")                      # 'a' is used again, so 'b' is now the least recent
    cache.put("c", 3)
    assert cache.get("b") is None, "LRUCache(2): put a, put b, get a, put c — 'b' should be evicted"
    assert cache.get("a") == 1 and cache.get("c") == 3, "'a' and 'c' should still be cached"


@each
def test_example_twist(p):
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    if p["twist"] == "peek":
        assert cache.peek("a") == 1, "peek('a') should give 1"
    elif p["twist"] == "delete":
        assert cache.delete("a") is True and len(cache) == 1, "delete('a') should return True, leaving 1 entry"
    elif p["twist"] == "resize":
        cache.resize(1)
        assert len(cache) == 1 and cache.get("b") == 2, "resize(1) should keep only 'b', the most recently used"
    else:
        pytest.fail(f"unknown twist {p['twist']!r}")
