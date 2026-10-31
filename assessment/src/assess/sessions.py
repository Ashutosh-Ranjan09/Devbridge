"""Taking a task: issue → begin → (time passes) → submit → result.

One session per candidate, pattern and job — starting again returns the task already
issued, so refreshing a page cannot fish for an easier variant. A job's task is issued
without a clock and begins when the candidate presses Start, before its start-by date;
practice begins as it is issued. A submission after the deadline plus the grace period
is refused, not scored. A submission the sandbox could not run leaves the session open:
nothing was measured, so the candidate may submit again.
"""

from __future__ import annotations

import datetime
import secrets

from assess.config import settings
from assess.models import JobStatus, Priority, Result, Session, SessionStatus, Variant
from assess.patterns import for_skill, load
from assess.providers import LLMProvider
from assess.sandbox import run_candidate
from assess.scoring import build_result
from assess.store import Store
from assess.variants import generate


class SessionError(ValueError):
    """The action is not allowed for this session. The message says why."""


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
        session = store.set_status(session, SessionStatus.EXPIRED)
    return session


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
        raise SessionError(f"{session_id} is {session.status.value}; a session takes one submission")
    assert session.deadline is not None, "an open session has begun"
    submitted = now or now_utc()
    if submitted > session.deadline + datetime.timedelta(seconds=settings.grace_seconds):
        store.set_status(session, SessionStatus.EXPIRED)
        raise SessionError(
            f"{session_id}: submitted {(submitted - session.deadline).seconds // 60} min after the "
            "deadline — refused, not scored"
        )

    variant = store.variant(session.variant_id, session.job_id)
    assert variant is not None
    pattern = load(variant.pattern_id)
    if pattern.version != variant.pattern_version:
        raise SessionError(
            f"{variant.pattern_id} is now v{pattern.version}; this task was issued from "
            f"v{variant.pattern_version}, and its tests are not the ones on disk"
        )

    run = run_candidate(pattern, variant.params, source)
    result = build_result(pattern, variant, session, run, submitted)
    if result.scored:
        store.save_result(result, source)
        store.set_status(session, SessionStatus.SUBMITTED)
    return result
