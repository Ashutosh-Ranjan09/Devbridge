"""Taking a task: issue → begin → run examples, submit (up to three times) → result.

One session per candidate, pattern and job — starting again returns the task already
issued, so refreshing a page cannot fish for an easier variant. A job's task is issued
without a clock and begins when the candidate presses Start, before its start-by date;
practice begins as it is issued.

Run tries the code on the visible examples, as often as the candidate likes; it is
stored nowhere. Submit runs the hidden tests and is one attempt of `max_attempts`. The
LAST attempt counts, and the session is final — its result written, the only one events
and calibration see — at the last attempt, at one that passes every test, when the
candidate finishes, or when the deadline passes. Code that does not parse is refused
before either runs and costs nothing. A submission after the deadline plus the grace
period is refused, not scored. One the sandbox could not run uses no attempt: nothing
was measured.
"""

from __future__ import annotations

import datetime
import secrets
import sqlite3

from assess.config import settings
from assess.models import (
    JobStatus,
    Outcome,
    Pattern,
    Priority,
    Result,
    Session,
    SessionStatus,
    Variant,
)
from assess.patterns import for_skill, load
from assess.providers import LLMProvider
from assess.sandbox import Run, run_candidate
from assess.scoring import build_result
from assess.store import Store
from assess.variants import generate


class SessionError(ValueError):
    """The action is not allowed for this session. The message says why."""


class NotPythonError(SessionError):
    """Code that does not parse. Refused before the sandbox; no attempt is used."""


def parses(source: str) -> None:
    """compile() parses and builds bytecode; it runs nothing, so candidate code may go
    through it outside the sandbox. A cut-off paste is an accident, not an answer: it is
    refused with its line and costs no attempt. Code that parses but fails on import is
    still scored zero: that is the candidate's program."""
    try:
        compile(source, "solution.py", "exec", dont_inherit=True)
    except SyntaxError as exc:
        raise NotPythonError(f"line {exc.lineno}: {exc.msg}. Not submitted; no attempt used") from exc
    except (ValueError, RecursionError, MemoryError) as exc:     # null bytes, absurd nesting
        raise NotPythonError(f"the code cannot be parsed ({type(exc).__name__}). Not submitted") from exc


def now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def start(
    store: Store,
    pattern_id: str,
    candidate_ref: str,
    *,
    job_id: str | None = None,
    seed: int | None = None,
    context: str | None = None,
    provider: LLMProvider | None = None,
    now: datetime.datetime | None = None,
    begin: bool = True,
    start_by: datetime.datetime | None = None,
) -> tuple[Session, Variant]:
    """`begin=False` issues the task with no clock, to be begun by `start_by`."""
    existing = store.existing_session(candidate_ref, pattern_id, job_id)
    if existing is not None:
        variant = store.variant(existing.variant_id, job_id)
        assert variant is not None
        return existing, variant

    pattern = load(pattern_id)
    variant = generate(
        pattern,
        seed if seed is not None else secrets.randbits(31),
        job_id=job_id,
        context=context,
        provider=provider,
        avoid=store.issued(job_id) if job_id else frozenset(),
    )
    issued = now or now_utc()
    session = Session(
        session_id="as_" + secrets.token_hex(6),
        variant_id=variant.variant_id,
        candidate_ref=candidate_ref,
        job_id=job_id,
        issued_at=issued,
        start_by=None if begin else _start_by(start_by, issued),
        status=SessionStatus.ISSUED,
    )
    if begin:
        session = _clocked(session, variant, issued)
    winner = store.save_issued(variant, session, pattern_id)
    if winner is not session:
        found = store.variant(winner.variant_id, job_id)
        assert found is not None
        return winner, found
    return session, variant


def _start_by(chosen: datetime.datetime | None, issued: datetime.datetime) -> datetime.datetime:
    """The recruiter's date, or the default. Refused in the past or too far out: a task
    nobody could start, or one that waits months for a candidate who has moved on."""
    if chosen is None:
        return issued + datetime.timedelta(days=settings.start_by_days)
    if chosen.tzinfo is None:
        raise SessionError("the start-by date needs a time zone")
    if chosen <= issued:
        raise SessionError("the start-by date has already passed")
    if chosen > issued + datetime.timedelta(days=settings.start_by_max_days):
        raise SessionError(f"the start-by date is more than {settings.start_by_max_days} days away")
    return chosen


def _clocked(session: Session, variant: Variant, now: datetime.datetime) -> Session:
    return session.model_copy(update={
        "status": SessionStatus.OPEN, "started_at": now,
        "deadline": now + datetime.timedelta(minutes=variant.time_limit_minutes),
    })


def _lapsed(session: Session, now: datetime.datetime) -> bool:
    if session.status is SessionStatus.ISSUED:
        return session.start_by is not None and now > session.start_by
    if session.status is SessionStatus.OPEN and session.deadline is not None:
        return now > session.deadline + datetime.timedelta(seconds=settings.grace_seconds)
    return False


def current(store: Store, session_id: str, *, now: datetime.datetime | None = None) -> Session:
    """A session as it stands now. One never begun has expired once its start-by date
    passes; one begun, once its deadline and the grace period have. Written down the first
    time anyone looks, not only when a late submission arrives, so no list says "open"
    for a task nobody can submit any more."""
    session = store.session(session_id)
    if session is None:
        raise SessionError(f"no session {session_id}")
    if _lapsed(session, now or now_utc()):
        session = _close(store, session)
    return session


def _close(store: Store, session: Session) -> Session:
    """Time is up: the last attempt counts, or, with none, the task has expired."""
    attempts = store.attempts(session.session_id)
    if not attempts:
        return store.set_status(session, SessionStatus.EXPIRED)
    last, source = attempts[-1]
    return _finalise(store, session, last, source)


def _finalise(store: Store, session: Session, last: Result, source: str) -> Session:
    store.save_result(last, source)                # the counted result: written once
    return store.set_status(session, SessionStatus.SUBMITTED)


def _task_of(store: Store, session: Session) -> tuple[Pattern, Variant]:
    variant = store.variant(session.variant_id, session.job_id)
    assert variant is not None
    pattern = load(variant.pattern_id)
    if pattern.version != variant.pattern_version:
        raise SessionError(
            f"{variant.pattern_id} is now v{pattern.version}; this task was issued from "
            f"v{variant.pattern_version}, and its tests are not the ones on disk"
        )
    return pattern, variant


def begin(store: Store, session_id: str, *, now: datetime.datetime | None = None) -> Session:
    """The candidate presses Start: the time limit runs from now. Pressing it again on a
    task already begun changes nothing; after the start-by date it is refused."""
    moment = now or now_utc()
    session = current(store, session_id, now=moment)
    if session.status is SessionStatus.EXPIRED and session.started_at is None:
        assert session.start_by is not None
        raise SessionError(f"{session_id}: the start-by date passed ({session.start_by:%d %b %Y %H:%M} UTC) "
                           "before it was started")
    if session.status is not SessionStatus.ISSUED:
        return session
    variant = store.variant(session.variant_id, session.job_id)
    assert variant is not None
    return store.update_session(_clocked(session, variant, moment))


def start_for_job(
    store: Store,
    job_id: str,
    candidate_ref: str,
    *,
    provider: LLMProvider | None = None,
    now: datetime.datetime | None = None,
    begin: bool = False,
    start_by: datetime.datetime | None = None,
) -> tuple[list[tuple[Session, Variant]], list[str]]:
    """One task per must-have skill the job confirmed and a pattern exists for.

    Returns (the sessions, the must-have skills NOT assessable) — the second list is
    reported, never silently skipped: "api_security cannot be assessed" is something
    a recruiter needs to know. The job's own text is the context the model fits each
    task to; it may only choose among each pattern's allowed values.

    Issued without a clock unless `begin`: each waits for the candidate to press Start,
    until `start_by` (the default when None).
    """
    job = store.job(job_id)
    if job is None:
        raise SessionError(f"no job {job_id}")
    if job.status is not JobStatus.CONFIRMED:
        raise SessionError(f"{job_id} is not confirmed; tasks are issued only for confirmed requirements")
    started: list[tuple[Session, Variant]] = []
    not_assessable: list[str] = []
    for skill in job.skills:
        if skill.skill_id is None or skill.priority is not Priority.MUST:
            continue
        patterns = for_skill(skill.skill_id)
        if not patterns:
            not_assessable.append(skill.skill_id)
            continue
        started.append(start(store, patterns[0].id, candidate_ref, job_id=job_id,
                             context=job.text, provider=provider, now=now,
                             begin=begin, start_by=start_by))
    return started, not_assessable


def submit(
    store: Store, session_id: str, source: str, *, now: datetime.datetime | None = None
) -> Result:
    session = store.session(session_id)
    if session is None:
        raise SessionError(f"no session {session_id}")
    if session.status is SessionStatus.ISSUED:
        raise SessionError(f"{session_id} has not been started; press Start first")
    if session.status is not SessionStatus.OPEN:
        raise SessionError(f"{session_id} is {session.status.value}; its result is final")
    assert session.deadline is not None, "an open session has begun"
    submitted = now or now_utc()
    if submitted > session.deadline + datetime.timedelta(seconds=settings.grace_seconds):
        _close(store, session)
        raise SessionError(
            f"{session_id}: submitted {(submitted - session.deadline).seconds // 60} min after the "
            "deadline — refused, not scored"
        )
    parses(source)
    pattern, variant = _task_of(store, session)

    attempt = len(store.attempts(session_id)) + 1          # open means one is left
    run = run_candidate(pattern, variant.params, source)
    result = build_result(pattern, variant, session, run, submitted, attempt=attempt)
    if not result.scored:
        return result                                       # nothing measured, no attempt used
    try:
        store.save_attempt(result, source)
    except sqlite3.IntegrityError as exc:                   # two submissions at once
        raise SessionError(f"{session_id}: another submission was being scored; nothing was used") from exc
    if attempt >= settings.max_attempts or result.outcome is Outcome.PASSED:
        _finalise(store, session, result, source)           # nothing left to try, or to improve
    return result


def finish(store: Store, session_id: str, *, now: datetime.datetime | None = None) -> Result:
    """The candidate is done before their attempts run out: the last attempt counts now.
    Again on a final session, the same result."""
    session = current(store, session_id, now=now)
    if session.status is SessionStatus.SUBMITTED:
        result = store.result(session_id)
        assert result is not None
        return result
    if session.status is not SessionStatus.OPEN:
        raise SessionError(f"{session_id} is {session.status.value}; there is nothing to finish")
    attempts = store.attempts(session_id)
    if not attempts:
        raise SessionError(f"{session_id}: nothing submitted yet; submit at least once to finish")
    last, source = attempts[-1]
    _finalise(store, session, last, source)
    return last


def run_examples(store: Store, session_id: str, source: str, *, now: datetime.datetime | None = None) -> Run:
    """The Run button: the visible examples, in the same sandbox. Stored nowhere, scores
    nothing, uses no attempt; allowed until the deadline."""
    session = current(store, session_id, now=now)
    if session.status is SessionStatus.ISSUED:
        raise SessionError(f"{session_id} has not been started; press Start first")
    if session.status is not SessionStatus.OPEN:
        raise SessionError(f"{session_id} is {session.status.value}; examples run only while it is open")
    parses(source)
    pattern, variant = _task_of(store, session)
    return run_candidate(pattern, variant.params, source, suite="visible")
