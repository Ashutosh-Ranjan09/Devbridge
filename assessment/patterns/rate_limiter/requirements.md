## Requirements

Implement `RateLimiter` in `solution.py`, starting from the starter file. Keep the class
and method names.

- `RateLimiter({limit}, {window})` allows at most **{limit} requests per {key_kind_label}** in any
  sliding window of **{window} seconds** ({window_label}).
- `check(key, now)` is called once per incoming request. `key` is the {key_kind_label};
  `now` is the current time in seconds. Time never goes backwards.
- A request accepted at time `t` counts against its key until time `t + {window}`. At
  exactly `t + {window}` it no longer counts.
- Within the limit, return `Response(status=200)`; the request now counts.
- Over the limit, return `Response(status=429)`. A rejected request does **not** count.
- Each {key_kind_label} is limited independently of every other.
- {twist_rule}

Time limit: **{time_limit} minutes**. Your code is run against hidden tests in a sandbox
with no network access. Only behaviour is tested, not style.
