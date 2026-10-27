"""MUTANT — sorts (count, item) descending, so ties come out in reverse order. Must fail: ties_alphabetical."""

from collections import Counter


def _ranked(counts: Counter[str], k: int) -> list[str]:
    return sorted(counts, key=lambda item: (counts[item], item), reverse=True)[:k]


def top_k(items: list[str], k: int) -> list[str]:
    return _ranked(Counter(items), k)


def top_k_with_counts(items: list[str], k: int) -> list[tuple[str, int]]:
    counts = Counter(items)
    return [(item, counts[item]) for item in _ranked(counts, k)]


def top_k_ignore_case(items: list[str], k: int) -> list[str]:
    return _ranked(Counter(item.lower() for item in items), k)


def top_k_excluding(items: list[str], k: int, exclude: set[str]) -> list[str]:
    return _ranked(Counter(item for item in items if item not in exclude), k)
