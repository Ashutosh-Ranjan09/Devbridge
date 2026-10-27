"""Hidden tests for top_k_frequent v1. The only scorer.

Reads params.json beside it — one variant's parameters, or a list of them when the
pattern is validated over every combination. Test names match the groups in
pattern.yaml; the report and calibration speak in those names.

Every expected answer is known by construction — the counts are chosen, then the
list is built from them — so no test re-implements the solution it checks. Counts
rise in string order, so an answer that is right only by alphabetical accident (a
solution that miscounts and then breaks "ties") is caught.
"""

import json
import pathlib
import random

import pytest
import solution
from solution import top_k

_raw = json.loads((pathlib.Path(__file__).parent / "params.json").read_text())
CASES = _raw if isinstance(_raw, list) else [_raw]
IDS = [f"{c['item_kind']}-{c['k']}-{c['twist']}" for c in CASES]
each = pytest.mark.parametrize("p", CASES, ids=IDS)

WORDS = [
    "usb c cable", "wireless mouse", "laptop stand", "phone case", "hdmi adapter",
    "desk lamp", "webcam", "mechanical keyboard", "monitor arm", "power bank",
    "noise cancelling earbuds", "wifi router", "sd card", "graphics tablet",
    "ergonomic chair", "smart plug",
]


def names(kind, n):
    """n distinct items of one kind, in plain string order."""
    if kind == "search_query":
        out = [WORDS[i] if i < len(WORDS) else f"query {i}" for i in range(n)]
    elif kind == "product_id":
        out = [f"SKU-{1000 + 37 * i}" for i in range(n)]
    else:
        out = [f"E{100 + 7 * i}" for i in range(n)]
    return sorted(out)


def build(counts, seed=7):
    """A shuffled list holding each item exactly counts[item] times."""
    items = [item for item, c in counts.items() for _ in range(c)]
    random.Random(seed).shuffle(items)
    return items


def rising(kind, n):
    """n items whose counts rise with string order: the last is the most frequent."""
    return {name: 2 + i for i, name in enumerate(names(kind, n))}


def best(counts, k):
    """The expected answer when every count is distinct."""
    return sorted(counts, key=counts.__getitem__, reverse=True)[:k]


@each
def test_picks_most_frequent(p):
    k = p["k"]
    counts = rising(p["item_kind"], 2 * k + 3)
    got = top_k(build(counts), k)
    assert len(got) == k, f"asked for {k} items, got {len(got)}"
    assert set(got) == set(best(counts, k)), (
        f"the {k} most frequent are {sorted(best(counts, k))}; got {sorted(got)}"
    )


@each
def test_most_frequent_first(p):
    k = p["k"]
    counts = rising(p["item_kind"], 2 * k + 3)
    got = top_k(build(counts), k)
    expected = best(counts, k)
    assert got == expected, (
        f"expected {expected} (counts {[counts[i] for i in expected]}); got {got}"
    )


@each
def test_ties_alphabetical(p):
    k = p["k"]
    *others, leader = names(p["item_kind"], k + 3)
    # every other item appears 3 times; first seen in REVERSE string order, so an
    # answer that keeps first-seen order for ties is wrong
    items = [name for _ in range(3) for name in reversed(others)] + [leader] * 5
    expected = [leader] + sorted(others)[: k - 1]
    got = top_k(items, k)
    assert got == expected, (
        f"{len(others)} items tie on 3; the {k - 1} smallest in string order fill the "
        f"places after {leader!r}: expected {expected}, got {got}"
    )


@each
def test_fewer_than_k(p):
    k = p["k"]
    counts = rising(p["item_kind"], k - 1)
    got = top_k(build(counts), k)
    assert got == best(counts, k), (
        f"only {k - 1} distinct items exist; all of them are returned, most frequent "
        f"first: expected {best(counts, k)}, got {got}"
    )


@each
def test_empty_input(p):
    assert top_k([], p["k"]) == [], "an empty list has no most frequent items: expected []"


@each
def test_input_not_modified(p):
    items = build(rising(p["item_kind"], 2 * p["k"]))
    before = list(items)
    top_k(items, p["k"])
    assert items == before, "top_k changed the list it was given"


@each
def test_large_input(p):
    k = p["k"]
    fill = names(p["item_kind"], 80_000)
    rng = random.Random(11)
    counts = {name: 1 + rng.randrange(3) for name in fill}           # 1-3 each
    top = rng.sample(fill, k)
    for j, name in enumerate(top):
        counts[name] = 50 + 3 * j                                     # far above the rest
    items = build(counts, seed=13)
    got = top_k(items, k)
    assert got == best(counts, k), f"on {len(items):,} items: expected {best(counts, k)}, got {got}"


@each
def test_twist_behaviour(p):
    k = p["k"]
    kind = p["item_kind"]
    twist = p["twist"]
    if twist == "with_counts":
        counts = rising(kind, 2 * k + 3)
        expected = [(name, counts[name]) for name in best(counts, k)]
        got = solution.top_k_with_counts(build(counts), k)
        assert [tuple(x) for x in got] == expected, f"expected {expected}, got {got}"
    elif twist == "ignore_case":
        counts = {name.lower(): c for name, c in rising(kind, 2 * k + 3).items()}
        spellings = lambda name: [name.upper(), name.title(), name]   # noqa: E731
        items = []
        for name, c in counts.items():                                 # first seen in upper case
            items += [spellings(name)[i % 3] for i in range(c)]
        expected = best(counts, k)
        got = solution.top_k_ignore_case(items, k)
        assert got == expected, (
            f"counting spellings together, in lowercase: expected {expected}, got {got}"
        )
    elif twist == "excluding":
        counts = rising(kind, 2 * k + 3)
        ranked = best(counts, len(counts))
        exclude = {ranked[0], ranked[1], "not-in-the-list"}
        expected = ranked[2 : 2 + k]
        got = solution.top_k_excluding(build(counts), k, exclude)
        assert got == expected, (
            f"excluding {sorted(exclude - {'not-in-the-list'})}: expected {expected}, got {got}"
        )
    else:
        pytest.fail(f"unknown twist {twist!r}")
