"""MUTANT — delete removes the value but the entry still counts towards the capacity. Must fail: twist_behaviour (delete)."""

from collections import OrderedDict


class LRUCache:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._entries: OrderedDict[str, object] = OrderedDict()
        self._size = 0

    def get(self, key: str):
        if key not in self._entries:
            return None
        self._entries.move_to_end(key)
        return self._entries[key]

    def put(self, key: str, value) -> None:
        if key in self._entries:
            self._entries.move_to_end(key)
        else:
            self._size += 1
        self._entries[key] = value
        self._evict()

    def _evict(self) -> None:
        while self._size > self.capacity and self._entries:
            self._entries.popitem(last=False)
            self._size -= 1

    def __len__(self) -> int:
        return self._size

    def peek(self, key: str):
        return self._entries.get(key)

    def delete(self, key: str) -> bool:
        return self._entries.pop(key, None) is not None   # the size is not given back

    def resize(self, capacity: int) -> None:
        self.capacity = capacity
        self._evict()
