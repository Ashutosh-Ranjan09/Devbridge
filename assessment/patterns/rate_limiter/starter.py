"""Your solution. Keep the class and method names: the tests call exactly these."""

from dataclasses import dataclass, field


@dataclass
class Response:
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: dict = field(default_factory=dict)


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window = window_seconds

    def check(self, key: str, now: float) -> Response:
        """Called once per incoming request. `now` is the time in seconds; it never goes backwards."""
        raise NotImplementedError
