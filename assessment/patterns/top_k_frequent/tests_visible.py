"""Visible examples for top_k_frequent v1: the candidate's Run button. Never scored.

Small cases read straight off the requirements, so a candidate can check they read
them right. Everything the hidden tests probe beyond these (fewer than k, empty input,
not modifying the list, a tie across position k, a large input) is left to them. The
reference passes these in every combination; validation checks it.
"""

import json
import pathlib

import pytest
import solution
from solution import top_k

_raw = json.loads((pathlib.Path(__file__).parent / "params.json").read_text())
CASES = _raw if isinstance(_raw, list) else [_raw]
IDS = [f"{c['item_kind']}-{c['k']}-{c['twist']}" for c in CASES]
each = pytest.mark.parametrize("p", CASES, ids=IDS)

ITEMS = ["b", "a", "b", "c", "b", "a"]                      # b three times, a twice, c once


@each
def test_example_most_frequent_first(p):
    got = top_k(list(ITEMS), 2)
    assert got == ["b", "a"], f"top_k({ITEMS}, 2): got {got!r}, expected ['b', 'a']"


@each
def test_example_ties_in_string_order(p):
    items = ["y", "x", "z", "x", "y"]                       # x and y twice: x comes first
    got = top_k(list(items), 3)
    assert got == ["x", "y", "z"], f"top_k({items}, 3): got {got!r}, expected ['x', 'y', 'z']"


@each
def test_example_twist(p):
    if p["twist"] == "with_counts":
        got = solution.top_k_with_counts(list(ITEMS), 2)
        assert got == [("b", 3), ("a", 2)], f"top_k_with_counts({ITEMS}, 2): got {got!r}, expected [('b', 3), ('a', 2)]"
    elif p["twist"] == "ignore_case":
        items = ["B", "a", "b", "A", "b"]
        got = solution.top_k_ignore_case(list(items), 2)
        assert got == ["b", "a"], f"top_k_ignore_case({items}, 2): got {got!r}, expected ['b', 'a']"
    elif p["twist"] == "excluding":
        got = solution.top_k_excluding(list(ITEMS), 2, {"b"})
        assert got == ["a", "c"], f"top_k_excluding({ITEMS}, 2, {{'b'}}): got {got!r}, expected ['a', 'c']"
    else:
        pytest.fail(f"unknown twist {p['twist']!r}")
