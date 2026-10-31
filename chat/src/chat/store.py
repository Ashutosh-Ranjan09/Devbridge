"""SQLite: threads, messages, files and read marks. Message bodies, file names and file
bytes are sealed (`crypto.Box`) on the way in and opened on the way out; nothing else in
this module sees ciphertext. File bytes live under `files/` beside the database, each
under its id.

Messages and files are never edited or deleted — triggers refuse it — because this is a
record of what was said and shared during a hiring process, like a decision and its reason.
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
from chat.files import ACCEPTED, clean_name, sniff
from chat.models import (
    FileInfo,
    InboxRow,
    Message,
    NewMessage,
    NewThread,
    ReadMark,
    Seen,
    Side,
    Thread,
)

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
CREATE TABLE IF NOT EXISTS files (
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL REFERENCES threads(id),
  message_id TEXT NOT NULL UNIQUE,
  name BLOB NOT NULL,
  mime TEXT NOT NULL,
  size INTEGER NOT NULL
);
CREATE TRIGGER IF NOT EXISTS files_no_update BEFORE UPDATE ON files
  BEGIN SELECT RAISE(ABORT, 'files are never edited'); END;
CREATE TRIGGER IF NOT EXISTS files_no_delete BEFORE DELETE ON files
  BEGIN SELECT RAISE(ABORT, 'files are never deleted'); END;
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


class NotAllowedError(Exception):
    """A request from a candidate, a recruiter answering one, or a request from elsewhere."""


class TooLargeError(Exception):
    pass


class UnsupportedFileError(Exception):
    pass


class NoFileError(Exception):
    pass


def now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="milliseconds")


def _aad(thread_id: str, message_id: str) -> str:
    return f"{thread_id}|{message_id}"


# Columns added after the first release, added in place to a database that lacks them.
UPGRADES = {"messages": [("kind", "TEXT NOT NULL DEFAULT 'text'"), ("request_id", "TEXT")]}


class Store:
    def __init__(self, path: Path | str, box: Box) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.box = box
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        for table, columns in UPGRADES.items():
            have = {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}
            for name, decl in columns:
                if name not in have:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        self.files_dir = self.path.parent / "files"
        self.files_dir.mkdir(exist_ok=True)
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
    def _admit(self, db: sqlite3.Connection, thread_id: str, sender: str) -> str:
        """The thread exists and the sender is under the limit; the time to stamp."""
        if self.thread(thread_id) is None:
            raise NoThreadError(thread_id)
        sent_at = now()
        minute_ago = (datetime.datetime.fromisoformat(sent_at) - datetime.timedelta(minutes=1)
                      ).isoformat(timespec="milliseconds")
        (recent,) = db.execute("SELECT count(*) FROM messages WHERE sender = ? AND sent_at > ?",
                               (sender, minute_ago)).fetchone()
        if recent >= settings.per_minute:
            raise RateLimitedError(f"at most {settings.per_minute} messages a minute")
        return sent_at

    def post(self, thread_id: str, new: NewMessage) -> Message:
        if new.kind == "request" and new.side != "recruiter":
            raise NotAllowedError("only a recruiter asks for a document")
        with self.tx() as db:
            sent_at = self._admit(db, thread_id, new.sender)
            message_id = "msg_" + secrets.token_hex(8)
            sealed = self.box.seal(new.body.encode(), _aad(thread_id, message_id))
            cur = db.execute(
                "INSERT INTO messages (id, thread_id, sender, side, kind, body, sent_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (message_id, thread_id, new.sender, new.side, new.kind, sealed, sent_at))
        return Message(seq=cur.lastrowid or 0, id=message_id, thread_id=thread_id, sender=new.sender,
                       side=new.side, kind=new.kind, body=new.body, sent_at=sent_at)

    def post_file(self, thread_id: str, *, sender: str, side: Side, name: str, data: bytes,
                  note: str = "", request_id: str | None = None) -> Message:
        """A shared file, with an optional note, perhaps answering a request. The type comes
        from the bytes; the name is only shown. Bytes and name are sealed, each bound to
        this thread and file, so a file copied elsewhere does not open."""
        if len(data) > settings.max_file_bytes:
            raise TooLargeError(f"at most {settings.max_file_bytes // (1024 * 1024)} MB")
        mime = sniff(data)
        if mime is None:
            raise UnsupportedFileError(f"not a {ACCEPTED} file")
        if len(note) > settings.max_body_chars:
            raise NotAllowedError(f"a note of at most {settings.max_body_chars} characters")
        name = clean_name(name)
        with self.tx() as db:
            sent_at = self._admit(db, thread_id, sender)
            if request_id is not None:
                asked = db.execute("SELECT side, kind FROM messages WHERE id = ? AND thread_id = ?",
                                   (request_id, thread_id)).fetchone()
                if asked is None or asked["kind"] != "request":
                    raise NotAllowedError("no such request in this chat")
                if side != "candidate":
                    raise NotAllowedError("only the candidate answers a request")
            message_id = "msg_" + secrets.token_hex(8)
            file_id = "file_" + secrets.token_hex(8)
            path = self.files_dir / file_id
            tmp = path.with_suffix(".part")
            tmp.write_bytes(self.box.seal(data, f"{thread_id}|{file_id}|bytes"))
            try:
                cur = db.execute(
                    "INSERT INTO messages (id, thread_id, sender, side, kind, body, request_id, sent_at) "
                    "VALUES (?, ?, ?, ?, 'file', ?, ?, ?)",
                    (message_id, thread_id, sender, side, self.box.seal(note.encode(), _aad(thread_id, message_id)),
                     request_id, sent_at))
                db.execute("INSERT INTO files (id, thread_id, message_id, name, mime, size) VALUES (?, ?, ?, ?, ?, ?)",
                           (file_id, thread_id, message_id, self.box.seal(name.encode(), f"{thread_id}|{file_id}|name"),
                            mime, len(data)))
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
            tmp.replace(path)
        return Message(seq=cur.lastrowid or 0, id=message_id, thread_id=thread_id, sender=sender, side=side,
                       kind="file", body=note, request_id=request_id,
                       file=FileInfo(id=file_id, name=name, mime=mime, size=len(data)), sent_at=sent_at)

    def file(self, thread_id: str, file_id: str) -> tuple[FileInfo, bytes]:
        row = self.db.execute("SELECT * FROM files WHERE id = ? AND thread_id = ?", (file_id, thread_id)).fetchone()
        path = self.files_dir / file_id
        if row is None or not path.is_file():
            raise NoFileError(file_id)
        data = self.box.open(path.read_bytes(), f"{thread_id}|{file_id}|bytes")
        return self._info(row), data

    def _info(self, row: sqlite3.Row) -> FileInfo:
        name = self.box.open(row["name"], f"{row['thread_id']}|{row['id']}|name").decode()
        return FileInfo(id=row["id"], name=name, mime=row["mime"], size=row["size"])

    def messages(self, thread_id: str, after: int = 0, limit: int = 1000) -> list[Message]:
        rows = self.db.execute(
            "SELECT * FROM messages WHERE thread_id = ? AND seq > ? ORDER BY seq LIMIT ?",
            (thread_id, after, limit)).fetchall()
        files = {f["message_id"]: self._info(f) for f in self.db.execute(
            "SELECT * FROM files WHERE message_id IN (SELECT id FROM messages WHERE thread_id = ? AND seq > ?)",
            (thread_id, after))}
        return [Message(seq=r["seq"], id=r["id"], thread_id=r["thread_id"], sender=r["sender"],
                        side=r["side"], kind=r["kind"], request_id=r["request_id"], file=files.get(r["id"]),
                        body=self.box.open(r["body"], _aad(r["thread_id"], r["id"])).decode(),
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
