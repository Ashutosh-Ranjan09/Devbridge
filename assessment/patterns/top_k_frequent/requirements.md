## Requirements

Implement `top_k` in `solution.py`, starting from the starter file. Keep the function
names.

- `top_k(items, k)` returns the **k most frequent** {item_kind_label}s in `items`, as a list,
  **most frequent first**. The dashboard calls it with `k = {k}`; your function must work
  for any `k` of 1 or more.
- Items are compared exactly: two strings are the same item only if they are equal.
- **Ties**: items with the same count are ordered by plain string comparison
  (`"a" < "b"`, and `"SKU-1042" < "SKU-998"`), smallest first. This also decides which
  item takes the last place when a tie crosses position k.
- If there are fewer than k distinct items, return all of them, in the same order.
  An empty list gives `[]`.
- Do not modify `items`; the caller still uses it.
- `items` can hold several hundred thousand entries. Each call must finish in well
  under a second; a solution that rescans the whole list once per distinct item is
  too slow.
- {twist_rule}

Time limit: **{time_limit} minutes**. Your code is run against hidden tests in a sandbox
with no network access. Only behaviour is tested, not style.
