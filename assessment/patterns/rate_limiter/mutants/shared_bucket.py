"""MUTANT — one counter for every key. Must fail: keys_independent."""


import math
from collections import defaultdict, deque
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
        self.accepted: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, now: float) -> Response:
        times = self.accepted['all']
        while times and times[0] <= now - self.window:   # at exactly t + window, t stops counting
            times.popleft()
        if len(times) < self.limit:
            times.append(now)
            return Response(200, {"X-RateLimit-Remaining": str(self.limit - len(times))})
        return Response(
            429,
            {
                "Retry-After": str(math.ceil(times[0] + self.window - now)),
                "X-RateLimit-Remaining": "0",
            },
            {"error": "rate_limited", "key": key, "limit": self.limit, "window": self.window},
        )
