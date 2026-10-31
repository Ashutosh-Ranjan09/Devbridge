"""SQLite: threads, messages and read marks. Message bodies are sealed (`crypto.Box`) on
the way in and opened on the way out; nothing else in this module sees ciphertext.

Messages are never edited or deleted — triggers refuse it — because this is a record of
what was said during a hiring process, like a decision and its reason.
"""

from __future__ import annotations

import datetime
import secrets
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from chat.config import settings
from chat.crypto import Box
from chat.models import InboxRow, Message, NewMessage, NewThread, ReadMark, Seen, Side, Thread

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
  id TEXT PRIMARY KEY,
  candidate TEXT NOT NULL,
  org TEXT NOT NULL,
  started_by TEXT NOT NULL,
  started_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS threads_by_candidate ON threads (candidate);
CREATE INDEX IF NOT EXISTS threads_by_org ON threads (org);
CREATE TABLE IF NOT EXISTS messages (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  thread_id TEXT NOT NULL REFERENCES threads(id),
  sender TEXT NOT NULL,
  side TEXT NOT NULL CHECK (side IN ('candidate', 'recruiter')),
  body BLOB NOT NULL,
  sent_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_by_thread ON messages (thread_id, seq);
CREATE INDEX IF NOT EXISTS messages_by_sender ON messages (sender, sent_at);
CREATE TRIGGER IF NOT EXISTS messages_no_update BEFORE UPDATE ON messages
  BEGIN SELECT RAISE(ABORT, 'messages are never edited'); END;
CREATE TRIGGER IF NOT EXISTS messages_no_delete BEFORE DELETE ON messages
  BEGIN SELECT RAISE(ABORT, 'messages are never deleted'); END;
CREATE TABLE IF NOT EXISTS reads (
  thread_id TEXT NOT NULL REFERENCES threads(id),
  reader TEXT NOT NULL,
  side TEXT NOT NULL CHECK (side IN ('candidate', 'recruiter')),
  seq INTEGER NOT NULL,
  PRIMARY KEY (thread_id, reader)
);
"""


class NoThreadError(Exception):
    """Nobody opened this thread. Only a recruiter can, so a candidate cannot write first."""


class ThreadConflictError(Exception):
    """A thread already exists under this id for another candidate or company."""


class RateLimitedError(Exception):
    pass


def now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="milliseconds")


def _aad(thread_id: str, message_id: str) -> str:
    return f"{thread_id}|{message_id}"


class Store:
    def __init__(self, path: Path | str, box: Box) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.box = box
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        self._lock = threading.RLock()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self.db:
            yield self.db

    # ── threads ─────────────────────────────────────────────────────────────
    def open_thread(self, new: NewThread) -> Thread:
        """Idempotent: opening it again returns the thread as first opened."""
        with self.tx() as db:
            db.execute(
                "INSERT OR IGNORE INTO threads (id, candidate, org, started_by, started_at) VALUES (?, ?, ?, ?, ?)",
                (new.thread_id, new.candidate, new.org, new.started_by, now()))
            thread = self.thread(new.thread_id)
        assert thread is not None
        if (thread.candidate, thread.org) != (new.candidate, new.org):
            raise ThreadConflictError(f"thread {new.thread_id} belongs to another candidate or company")
        return thread

    def thread(self, thread_id: str) -> Thread | None:
        row = self.db.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
        return None if row is None else Thread(
            thread_id=row["id"], candidate=row["candidate"], org=row["org"],
            started_by=row["started_by"], started_at=row["started_at"])

    # ── messages ────────────────────────────────────────────────────────────
    def post(self, thread_id: str, new: NewMessage) -> Message:
        with self.tx() as db:
            if self.thread(thread_id) is None:
                raise NoThreadError(thread_id)
            sent_at = now()
            minute_ago = (datetime.datetime.fromisoformat(sent_at) - datetime.timedelta(minutes=1)
                          ).isoformat(timespec="milliseconds")
            (recent,) = db.execute("SELECT count(*) FROM messages WHERE sender = ? AND sent_at > ?",
                                   (new.sender, minute_ago)).fetchone()
            if recent >= settings.per_minute:
                raise RateLimitedError(f"at most {settings.per_minute} messages a minute")
            message_id = "msg_" + secrets.token_hex(8)
            sealed = self.box.seal(new.body.encode(), _aad(thread_id, message_id))
            cur = db.execute(
                "INSERT INTO messages (id, thread_id, sender, side, body, sent_at) VALUES (?, ?, ?, ?, ?, ?)",
                (message_id, thread_id, new.sender, new.side, sealed, sent_at))
        return Message(seq=cur.lastrowid or 0, id=message_id, thread_id=thread_id, sender=new.sender,
                       side=new.side, body=new.body, sent_at=sent_at)

    def messages(self, thread_id: str, after: int = 0, limit: int = 1000) -> list[Message]:
        rows = self.db.execute(
            "SELECT * FROM messages WHERE thread_id = ? AND seq > ? ORDER BY seq LIMIT ?",
            (thread_id, after, limit)).fetchall()
        return [Message(seq=r["seq"], id=r["id"], thread_id=r["thread_id"], sender=r["sender"],
                        side=r["side"], body=self.box.open(r["body"], _aad(r["thread_id"], r["id"])).decode(),
                        sent_at=r["sent_at"]) for r in rows]

    # ── read marks ──────────────────────────────────────────────────────────
    def mark_read(self, thread_id: str, mark: ReadMark) -> Seen:
        """A mark only moves forward, and never past the newest message."""
        with self.tx() as db:
            if self.thread(thread_id) is None:
                raise NoThreadError(thread_id)
            (newest,) = db.execute("SELECT coalesce(max(seq), 0) FROM messages WHERE thread_id = ?",
                                   (thread_id,)).fetchone()
            db.execute(
                "INSERT INTO reads (thread_id, reader, side, seq) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (thread_id, reader) DO UPDATE SET seq = max(seq, excluded.seq)",
                (thread_id, mark.reader, mark.side, min(mark.seq, newest)))
        return self.seen(thread_id)

    def seen(self, thread_id: str) -> Seen:
        rows = self.db.execute("SELECT side, max(seq) AS seq FROM reads WHERE thread_id = ? GROUP BY side",
                               (thread_id,)).fetchall()
        return Seen(**{r["side"]: r["seq"] for r in rows})

    # ── inbox ───────────────────────────────────────────────────────────────
    def inbox(self, reader: str, *, candidate: str | None = None, orgs: list[str] | None = None) -> list[InboxRow]:
        """A candidate's threads, or those of a recruiter's companies, newest first. Unread
        counts the OTHER side's messages after this reader's own mark."""
        side: Side
        if candidate is not None:
            where, args, side = "t.candidate = ?", [candidate], "candidate"
        elif orgs:
            where, args, side = f"t.org IN ({','.join('?' * len(orgs))})", list(orgs), "recruiter"
        else:
            return []
        rows = self.db.execute(
            f"""SELECT t.id, t.started_at,
                       (SELECT max(sent_at) FROM messages m WHERE m.thread_id = t.id) AS last_at,
                       (SELECT count(*) FROM messages m WHERE m.thread_id = t.id AND m.side != ?
                          AND m.seq > coalesce((SELECT seq FROM reads r WHERE r.thread_id = t.id AND r.reader = ?), 0)
                       ) AS unread
                FROM threads t WHERE {where}
                ORDER BY coalesce(last_at, t.started_at) DESC""",  # `where` holds placeholders only
            [side, reader, *args]).fetchall()
        return [InboxRow(thread_id=r["id"], started_at=r["started_at"], last_at=r["last_at"],
                         unread=r["unread"]) for r in rows]
