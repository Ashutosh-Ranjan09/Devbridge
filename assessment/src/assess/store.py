"""SQLite, local. Jobs, variants, sessions, submissions and results.

Each record is stored as its model's JSON, with only the columns that are queried
pulled out beside it — the same choice cvv made for its reports. A result and the
code it scored are written once: triggers refuse UPDATE and DELETE, so an assessment
cannot be quietly re-scored after the fact. Everything here names a candidate, so the
database lives in .data/, which git ignores.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from assess.config import settings
from assess.models import Job, JobStatus, Result, Session, SessionStatus, Variant

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    doc         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS variants (
    variant_id  TEXT NOT NULL,
    job_id      TEXT NOT NULL DEFAULT '',
    doc         TEXT NOT NULL,
    PRIMARY KEY (variant_id, job_id)
);
CREATE TABLE IF NOT EXISTS sessions (
    session_id     TEXT PRIMARY KEY,
    variant_id     TEXT NOT NULL,
    candidate_ref  TEXT NOT NULL,
    pattern_id     TEXT NOT NULL,
    job_id         TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL,
    doc            TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_session_per_task
    ON sessions (candidate_ref, pattern_id, job_id);
CREATE TABLE IF NOT EXISTS submissions (
    session_id  TEXT PRIMARY KEY,
    source      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS results (
    session_id       TEXT PRIMARY KEY,
    pattern_id       TEXT NOT NULL,
    pattern_version  INTEGER NOT NULL,
    doc              TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS results_no_update BEFORE UPDATE ON results
    BEGIN SELECT RAISE(ABORT, 'a result is never changed'); END;
CREATE TRIGGER IF NOT EXISTS results_no_delete BEFORE DELETE ON results
    BEGIN SELECT RAISE(ABORT, 'a result is never deleted'); END;
CREATE TRIGGER IF NOT EXISTS submissions_no_update BEFORE UPDATE ON submissions
    BEGIN SELECT RAISE(ABORT, 'a submission is never changed'); END;
"""


class Store:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else settings.db_path
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the HTTP API opens one Store per request, and FastAPI
        # may run that dependency's setup and its teardown on different worker threads.
        # sqlite3 refused the close, and the request failed with a 500 after its answer
        # was ready. One Store is still used by one thread at a time; never share one
        # between requests.
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.executescript(SCHEMA)

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self.db:
            yield self.db

    # ── jobs ───────────────────────────────────────────────────────────────
    def save_job(self, job: Job) -> None:
        """Insert, or replace a PROPOSED job. A confirmed job is never edited."""
        current = self.job(job.job_id)
        if current is not None and current.status is JobStatus.CONFIRMED:
            raise ValueError(f"{job.job_id} is confirmed; a confirmed job is never edited")
        with self.tx() as db:
            db.execute("INSERT OR REPLACE INTO jobs VALUES (?, ?, ?)",
                       (job.job_id, job.status.value, job.model_dump_json()))

    def job(self, job_id: str) -> Job | None:
        row = self.db.execute("SELECT doc FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return Job.model_validate_json(row[0]) if row else None

    def jobs(self) -> list[Job]:
        return [Job.model_validate_json(r[0]) for r in self.db.execute("SELECT doc FROM jobs ORDER BY rowid")]

    # ── variants ───────────────────────────────────────────────────────────
    def variant(self, variant_id: str, job_id: str | None) -> Variant | None:
        row = self.db.execute("SELECT doc FROM variants WHERE variant_id = ? AND job_id = ?",
                              (variant_id, job_id or "")).fetchone()
        return Variant.model_validate_json(row[0]) if row else None

    def issued(self, job_id: str | None) -> set[str]:
        """Variant ids already given to a candidate for this job."""
        rows = self.db.execute("SELECT variant_id FROM variants WHERE job_id = ?", (job_id or "",))
        return {r[0] for r in rows}

    # ── sessions ───────────────────────────────────────────────────────────
    def save_issued(self, variant: Variant, session: Session, pattern_id: str) -> Session:
        """The variant and its session in one transaction. Two requests for one task at
        once (a double click, two tabs) both find none and both make one; the unique
        index lets one in, and the other is handed the winner's session, its own variant
        rolled back with it, so `issued` never counts a task nobody was given."""
        try:
            with self.tx() as db:
                db.execute("INSERT OR IGNORE INTO variants VALUES (?, ?, ?)",
                           (variant.variant_id, variant.job_id or "", variant.model_dump_json()))
                db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (session.session_id, session.variant_id, session.candidate_ref, pattern_id,
                            session.job_id or "", session.status.value, session.model_dump_json()))
        except sqlite3.IntegrityError:
            winner = self.existing_session(session.candidate_ref, pattern_id, session.job_id)
            if winner is None:
                raise
            return winner
        return session

    def set_status(self, session: Session, status: SessionStatus) -> Session:
        return self.update_session(session.model_copy(update={"status": status}))

    def update_session(self, session: Session) -> Session:
        with self.tx() as db:
            db.execute("UPDATE sessions SET status = ?, doc = ? WHERE session_id = ?",
                       (session.status.value, session.model_dump_json(), session.session_id))
        return session

    def session(self, session_id: str) -> Session | None:
        row = self.db.execute("SELECT doc FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        return Session.model_validate_json(row[0]) if row else None

    def existing_session(self, candidate_ref: str, pattern_id: str, job_id: str | None) -> Session | None:
        row = self.db.execute(
            "SELECT doc FROM sessions WHERE candidate_ref = ? AND pattern_id = ? AND job_id = ?",
            (candidate_ref, pattern_id, job_id or ""),
        ).fetchone()
        return Session.model_validate_json(row[0]) if row else None

    def sessions_for_job(self, job_id: str) -> list[Session]:
        rows = self.db.execute("SELECT doc FROM sessions WHERE job_id = ? ORDER BY rowid", (job_id,))
        return [Session.model_validate_json(r[0]) for r in rows]

    # ── results ────────────────────────────────────────────────────────────
    def save_result(self, result: Result, source: str) -> None:
        with self.tx() as db:
            db.execute("INSERT INTO submissions VALUES (?, ?)", (result.session_id, source))
            db.execute("INSERT INTO results VALUES (?, ?, ?, ?)",
                       (result.session_id, result.pattern_id, result.pattern_version,
                        result.model_dump_json()))

    def result(self, session_id: str) -> Result | None:
        row = self.db.execute("SELECT doc FROM results WHERE session_id = ?", (session_id,)).fetchone()
        return Result.model_validate_json(row[0]) if row else None

    def submission(self, session_id: str) -> str | None:
        row = self.db.execute("SELECT source FROM submissions WHERE session_id = ?", (session_id,)).fetchone()
        return str(row[0]) if row else None

    def results_for(self, pattern_id: str, version: int) -> list[Result]:
        rows = self.db.execute(
            "SELECT doc FROM results WHERE pattern_id = ? AND pattern_version = ? ORDER BY rowid",
            (pattern_id, version),
        )
        return [Result.model_validate_json(r[0]) for r in rows]
