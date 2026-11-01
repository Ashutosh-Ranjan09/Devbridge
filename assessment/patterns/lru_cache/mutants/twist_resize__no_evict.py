"""MUTANT — resize changes the number and evicts nothing. Must fail: twist_behaviour (resize)."""

from collections import OrderedDict


class LRUCache:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._entries: OrderedDict[str, object] = OrderedDict()   # least recently used first

    def get(self, key: str):
        if key not in self._entries:
            return None
        self._entries.move_to_end(key)
        return self._entries[key]

    def put(self, key: str, value) -> None:
        if key in self._entries:
            self._entries.move_to_end(key)
        self._entries[key] = value
        self._evict()

    def _evict(self) -> None:
        while len(self._entries) > self.capacity:
            self._entries.popitem(last=False)

    def __len__(self) -> int:
        return len(self._entries)

    def peek(self, key: str):
        return self._entries.get(key)

    def delete(self, key: str) -> bool:
        return self._entries.pop(key, None) is not None

    def resize(self, capacity: int) -> None:
        self.capacity = capacity
