"""MUTANT — right answers, but a list scanned on every call: linear time. Must fail: many_operations_fast."""


class LRUCache:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._order: list[str] = []          # least recently used first
        self._values: dict[str, object] = {}

    def _use(self, key: str) -> None:
        if key in self._values:
            self._order.remove(key)          # O(n)
        self._order.append(key)

    def get(self, key: str):
        if key not in self._values:
            return None
        self._use(key)
        return self._values[key]

    def put(self, key: str, value) -> None:
        self._use(key)
        self._values[key] = value
        self._evict()

    def _evict(self) -> None:
        while len(self._order) > self.capacity:
            del self._values[self._order.pop(0)]

    def __len__(self) -> int:
        return len(self._order)

    def peek(self, key: str):
        return self._values.get(key)

    def delete(self, key: str) -> bool:
        if key not in self._values:
            return False
        self._order.remove(key)
        del self._values[key]
        return True

    def resize(self, capacity: int) -> None:
        self.capacity = capacity
        self._evict()
