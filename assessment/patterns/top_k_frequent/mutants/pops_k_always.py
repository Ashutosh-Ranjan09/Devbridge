"""MUTANT — pops k times from a heap, even when fewer than k items exist. Must fail: fewer_than_k."""

from collections import Counter
import heapq


def _ranked(counts: Counter[str], k: int) -> list[str]:
    heap = [(-c, item) for item, c in counts.items()]
    heapq.heapify(heap)
    return [heapq.heappop(heap)[1] for _ in range(k)]


def top_k(items: list[str], k: int) -> list[str]:
    return _ranked(Counter(items), k)


def top_k_with_counts(items: list[str], k: int) -> list[tuple[str, int]]:
    counts = Counter(items)
    return [(item, counts[item]) for item in _ranked(counts, k)]


def top_k_ignore_case(items: list[str], k: int) -> list[str]:
    return _ranked(Counter(item.lower() for item in items), k)


def top_k_excluding(items: list[str], k: int, exclude: set[str]) -> list[str]:
    return _ranked(Counter(item for item in items if item not in exclude), k)
