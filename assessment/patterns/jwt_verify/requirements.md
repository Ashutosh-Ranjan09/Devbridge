## Requirements

Implement `verify` in `solution.py`, starting from the starter file. Keep the names, and
use only Python's standard library (`base64`, `hmac`, `hashlib`, `json`).

- A token is **three parts** separated by `.`: header, payload, signature. Each part is
  **base64url without padding** (`-` and `_` instead of `+` and `/`, no trailing `=`).
  The header and the payload are JSON objects.
- The header's `alg` must be **exactly `"HS256"`**. Anything else is invalid —
  including `"none"`, `"HS512"`, and a header with no `alg`.
- The signature is HMAC-SHA256, keyed with `secret`, over the ASCII text
  `<header part>.<payload part>` exactly as they appear in the token. Compare it with
  `hmac.compare_digest`.
- If the payload has `exp`, the token is invalid once `now >= exp + leeway`. If it has
  `nbf`, the token is invalid while `now < nbf - leeway`. Both must be numbers.
- The {service_label} allows a leeway of **{leeway} seconds**, but `verify` takes the leeway
  as an argument: use the one it is given.
- On success, return the payload as a dict. **Every** failure raises `InvalidToken`,
  never any other exception: a malformed token is refused, not a crash.
- {twist_rule}

Time limit: **{time_limit} minutes**. Your code is run against hidden tests in a sandbox
with no network access. Only behaviour is tested, not style.
