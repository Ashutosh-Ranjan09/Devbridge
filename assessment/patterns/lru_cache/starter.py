"""Your solution. Keep the class and method names: the tests call exactly these."""


class LRUCache:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity

    def get(self, key: str):
        """The cached value, or None. A hit counts as a use."""
        raise NotImplementedError

    def put(self, key: str, value) -> None:
        """Add or replace. Counts as a use. May evict the least recently used entry."""
        raise NotImplementedError

    def __len__(self) -> int:
        """How many entries are cached now."""
        raise NotImplementedError
