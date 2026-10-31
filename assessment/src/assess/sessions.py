"""Taking a task: start → (time passes) → submit → result.

One session per candidate, pattern and job — starting again returns the task already
issued, so refreshing a page cannot fish for an easier variant. A submission after the
deadline plus the grace period is refused, not scored. A submission the sandbox could
not run leaves the session open: nothing was measured, so the candidate may submit again.
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
) -> tuple[Session, Variant]:
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
    started = now or now_utc()
    session = Session(
        session_id="as_" + secrets.token_hex(6),
        variant_id=variant.variant_id,
        candidate_ref=candidate_ref,
        job_id=job_id,
        started_at=started,
        deadline=started + datetime.timedelta(minutes=variant.time_limit_minutes),
    )
    winner = store.save_issued(variant, session, pattern_id)
    if winner is not session:
        found = store.variant(winner.variant_id, job_id)
        assert found is not None
        return winner, found
    return session, variant


def start_for_job(
    store: Store,
    job_id: str,
    candidate_ref: str,
    *,
    provider: LLMProvider | None = None,
    now: datetime.datetime | None = None,
) -> tuple[list[tuple[Session, Variant]], list[str]]:
    """One task per must-have skill the job confirmed and a pattern exists for.

    Returns (the sessions, the must-have skills NOT assessable) — the second list is
    reported, never silently skipped: "api_security cannot be assessed" is something
    a recruiter needs to know. The job's own text is the context the model fits each
    task to; it may only choose among each pattern's allowed values.
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
                             context=job.text, provider=provider, now=now))
    return started, not_assessable


def submit(
    store: Store, session_id: str, source: str, *, now: datetime.datetime | None = None
) -> Result:
    session = store.session(session_id)
    if session is None:
        raise SessionError(f"no session {session_id}")
    if session.status is not SessionStatus.OPEN:
        raise SessionError(f"{session_id} is {session.status.value}; a session takes one submission")
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
