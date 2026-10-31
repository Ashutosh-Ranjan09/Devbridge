# DevBridge — chat

A recruiter and a candidate talk here: **one thread per application**, between the
candidate and the recruiters of the company they applied to. **Only a recruiter opens a
thread**; the candidate can reply once one has. A recruiter can **ask for a document**,
and either side can **share a file** (PDF, PNG, JPG or DOCX, at most 10 MB). Messages,
file names and file bytes are **sealed at rest** (AES-256-GCM) and never edited or deleted.

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
| `crypto.py` | `Box`: seal and open, each ciphertext bound to its thread and message or file id |
| `files.py` | `sniff()`: a file's type from its bytes, one of four or none · `clean_name()` |
| `store.py` | SQLite: threads, messages (text, request, file), files, read marks — triggers refuse UPDATE and DELETE; sealed file bytes in `.data/files/<id>`; limits; old databases upgraded in place |
| `hub.py` | wakes the open streams on a thread; in process |
| `api.py` | the HTTP surface, below; `events()` is the stream |
| `cli.py` | `chat serve` · `chat keygen` |

```
POST /v1/threads                        a recruiter opens a thread (idempotent; 409 for another owner)
GET  /v1/threads/{id}?after=            the thread, its messages, who has seen what · 404 not opened
POST /v1/threads/{id}/messages          {sender, side, body, kind?} · kind "request": a recruiter asking for a document
                                         404 not opened · 422 empty, > 4,000, or a candidate's request · 429 > 30 a minute
POST /v1/threads/{id}/files             multipart: sender, side, file, note?, request_id?
                                         415 not PDF/PNG/JPG/DOCX by its bytes · 413 > 10 MB · 422 a request_id that is not a
                                         request in this thread, or a recruiter answering one
GET  /v1/threads/{id}/files/{file_id}   the bytes, opened, with the sniffed type; the name URL-encoded in X-File-Name
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
5. **The record is permanent.** Triggers refuse UPDATE and DELETE on messages and files:
   what was said and shared during a hiring process stays as it was, like a decision and
   its reason.
6. **A file is what its bytes say.** Four types, each by its signature (a DOCX must be a zip
   holding `word/document.xml`); a name or a claimed type is never believed, so an HTML page
   renamed `.pdf` is refused. The name is cleaned and only shown — files are stored under
   their ids. The web serves every file as an attachment with `nosniff` and a sandbox
   policy, so nothing shared is ever rendered in the site's origin.
7. **Only a recruiter asks for a document, and only the candidate answers**, in the same
   thread; a request may be answered with several files.
8. **A stream loses nothing.** It replays from `after` (the browser's Last-Event-ID on a
   reconnect), and clears its wake-up before reading, so a message posted in between still
   wakes it.

## Known limits, stated

- Fan-out is in process (`hub.py`): one `chat serve`. A second process would need a shared
  channel; a missed wake-up there is a delay of one keep-alive (15 s), never a lost message.
- No malware scanning: a PDF or DOCX can carry anything a reader opens. Files are only ever
  downloads, and the type check stops pages and programs, not a hostile document.
- A file is read into memory whole (10 MB at most).
- No key rotation: the version byte in each ciphertext leaves room for one.
- The rate limit is per sender per minute, counted from the stored messages.
