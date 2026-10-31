# DevBridge — chat

A recruiter and a candidate talk here: **one thread per application**, between the
candidate and the recruiters of the company they applied to. **Only a recruiter opens a
thread**; the candidate can reply once one has. Messages are **sealed at rest**
(AES-256-GCM) and never edited or deleted.

The web is the only caller. It checks who a person is and whether they are on a thread,
then calls here with this module's key; the browser never reaches this module, and live
updates reach it through the web's relay (`web/src/app/api/chat/[appId]/stream`).

```
uv sync
uv run chat keygen                 # prints CHAT_ENCRYPTION_KEY for chat/.env (dev.sh makes one)
uv run chat serve                  # :8090, prints its key if CHAT_API_KEY is unset
uv run pytest · uv run ruff check . · uv run mypy
```

| | |
|---|---|
| `config.py` | settings, prefix `CHAT_`, from `chat/.env` wherever it runs |
| `crypto.py` | `Box`: seal and open, each ciphertext bound to its thread and message id |
| `store.py` | SQLite: threads, messages (triggers refuse UPDATE and DELETE), read marks; limits |
| `hub.py` | wakes the open streams on a thread; in process |
| `api.py` | the HTTP surface, below; `events()` is the stream |
| `cli.py` | `chat serve` · `chat keygen` |

```
POST /v1/threads                        a recruiter opens a thread (idempotent; 409 for another owner)
GET  /v1/threads/{id}?after=            the thread, its messages, who has seen what · 404 not opened
POST /v1/threads/{id}/messages          {sender, side, body} · 404 not opened · 422 empty or > 4,000 · 429 > 30 a minute
POST /v1/threads/{id}/read              {reader, side, seq}: a mark only moves forward
GET  /v1/threads/{id}/events?after=     the backlog after `after`, then each message and read mark, live (SSE)
GET  /v1/inbox?reader=…&candidate=… | &org=…    threads newest first, with the reader's unread count
GET  /healthz
```

## Guardrails — do not weaken these

1. **A candidate cannot write first.** A message to a thread nobody opened is a 404 here,
   whatever the web does; only the web's recruiter action opens one.
2. **People are the web's user ids.** No name, no email, ever: the web adds those when it
   shows a page. A thread's id is the web's application id.
3. **Encrypted at rest, and said precisely.** Bodies are sealed before they are stored and
   opened only to answer the web. A copy of `chat.db` is unreadable without the key; this
   process can read everything. That is encryption at rest, **not end to end** — never
   describe it as more. End to end would stop the platform checking shared files and
   giving several recruiters one thread.
4. **The key is required and never invented.** `chat serve` refuses to start without
   `CHAT_ENCRYPTION_KEY`: a key made up at startup would be lost at the next one, and every
   message with it. Losing or changing the key makes the stored messages unreadable. It
   lives in `chat/.env` (gitignored); back it up.
5. **The record is permanent.** Triggers refuse UPDATE and DELETE on messages: what was said
   during a hiring process stays as said, like a decision and its reason.
6. **A stream loses nothing.** It replays from `after` (the browser's Last-Event-ID on a
   reconnect), and clears its wake-up before reading, so a message posted in between still
   wakes it.

## Known limits, stated

- Fan-out is in process (`hub.py`): one `chat serve`. A second process would need a shared
  channel; a missed wake-up there is a delay of one keep-alive (15 s), never a lost message.
- No file sharing yet (the next step: document requests and uploads, sealed the same way).
- No key rotation: the version byte in each ciphertext leaves room for one.
- The rate limit is per sender per minute, counted from the stored messages.
