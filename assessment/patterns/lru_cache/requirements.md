## Requirements

Implement `LRUCache` in `solution.py`, starting from the starter file. Keep the class
and method names.

- `LRUCache(capacity)` holds at most `capacity` {item_kind_label}s. The service uses a
  capacity of {capacity}; your class must work for any capacity of 1 or more.
- `get(key)` returns the cached value, or `None` if the key is not cached. A hit counts
  as a use. A miss changes nothing: it does not add the key.
- `put(key, value)` adds the entry, or replaces the value of a key already cached.
  Either way it counts as a use. Replacing never evicts anything.
- When a **new** key is put into a full cache, the **least recently used** entry is
  evicted first. An entry's last use is its most recent `get` hit or `put`.
- `len(cache)` is the number of entries cached now.
- Keys are strings. Values are never `None`.
- `get` and `put` must take constant time on average: the cache may hold tens of
  thousands of entries, and a call that scans them all is too slow.
- {twist_rule}

Time limit: **{time_limit} minutes**. Your code is run against hidden tests in a sandbox
with no network access. Only behaviour is tested, not style.
