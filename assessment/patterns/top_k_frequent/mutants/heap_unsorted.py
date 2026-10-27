"""MUTANT — keeps a k-sized min-heap and returns it in heap order. Must fail: most_frequent_first."""

from collections import Counter
import heapq


def _ranked(counts: Counter[str], k: int) -> list[str]:
    heap: list[tuple[int, str]] = []
    for item in sorted(counts, reverse=True):
        heapq.heappush(heap, (counts[item], item))
        if len(heap) > k:
            heapq.heappop(heap)
    return [item for _, item in heap]


def top_k(items: list[str], k: int) -> list[str]:
    return _ranked(Counter(items), k)


def top_k_with_counts(items: list[str], k: int) -> list[tuple[str, int]]:
    counts = Counter(items)
    return [(item, counts[item]) for item in _ranked(counts, k)]


def top_k_ignore_case(items: list[str], k: int) -> list[str]:
    return _ranked(Counter(item.lower() for item in items), k)


def top_k_excluding(items: list[str], k: int, exclude: set[str]) -> list[str]:
    return _ranked(Counter(item for item in items if item not in exclude), k)
