"""The HTTP surface: the CLI's commands as endpoints, for the web layer.

Thin by design, like the CLI: parse, call, return. Nothing here decides anything —
one session per task, the deadline, a confirmed job is never edited, an unrunnable
submission is not a score: every such rule lives in the function it calls, so the
CLI and the API cannot disagree. Candidate code reaches Docker only through
`sessions.submit`, exactly as from `assess submit`.
"""

from __future__ import annotations

import contextlib
import datetime
import secrets
import shutil
import subprocess
from collections.abc import Iterator
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field, model_validator

from assess import jd
from assess.config import settings
from assess.events import NotEvidenceError, batch
from assess.models import Job, Model, Outcome, Result, Score, Session, SessionStatus, Variant
from assess.patterns import PatternError, all_patterns, load
from assess.sessions import SessionError, begin, current, start, start_for_job, submit
from assess.store import Store
from assess.variants import VariantError

app = FastAPI(title="DevBridge assessment", version="1.0.0",
              description="Unique, equally hard, sandboxed coding tasks. No verdicts.")

# Generated when unset and printed by `assess serve`, as cvv does: results name
# candidates, so an open-by-default surface is the wrong default.
API_KEY = settings.api_key or secrets.token_urlsafe(24)


class RefusedError(Exception):
    """Any answer that is not a 2xx. Flat, like M6's: {"error": code, "detail": why}."""

    def __init__(self, status: int, error: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.error, self.detail = status, error, detail


@app.exception_handler(RefusedError)
def _refused(_: Request, exc: RefusedError) -> JSONResponse:
    return JSONResponse({"error": exc.error, "detail": exc.detail}, status_code=exc.status)


@app.exception_handler(RequestValidationError)
def _invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
    # FastAPI's own 422 is a list of dicts; one shape for every error keeps the
    # web layer to a single error path.
    why = "; ".join(f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors())
    return JSONResponse({"error": "invalid_request", "detail": why}, status_code=422)


def authorise(authorization: Annotated[str | None, Header()] = None) -> None:
    """Bearer token, compared in constant time (cvv's reasoning: `==` leaks the prefix)."""
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not supplied or not secrets.compare_digest(supplied, API_KEY):
        raise RefusedError(401, "unauthorised", "Supply the API key as `Authorization: Bearer <key>`.")


def store() -> Iterator[Store]:
    """One connection per request. FastAPI runs sync handlers on a thread pool, and an
    sqlite3 connection refuses use from any thread but the one that opened it."""
    s = Store()
    try:
        yield s
    finally:
        s.db.close()


Auth = Annotated[None, Depends(authorise)]
Db = Annotated[Store, Depends(store)]


# ── request bodies and views ───────────────────────────────────────────────

Bar = Annotated[float, Field(ge=0.0, le=1.0)]


class NewJob(Model):
    text: str = Field(min_length=1, max_length=50_000)
    model: bool = True                     # False: rules only, as `assess jd new --no-model`


class JobEdit(Model):
    must: dict[str, Bar | None] = Field(default_factory=dict)   # id → bar; None keeps it
    nice: list[str] = Field(default_factory=list)
    drop: list[str] = Field(default_factory=list)


class Confirmation(Model):
    by: str = Field(min_length=1)


class NewSessions(Model):
    candidate_ref: str = Field(min_length=1)   # the subject_ref M6 uses; never a name
    job_id: str | None = None
    pattern_id: str | None = None
    model: bool = True                     # with job_id: let the model fit tasks to the JD
    start_by: datetime.datetime | None = None  # with job_id: the last moment to press Start

    @model_validator(mode="after")
    def _one_source(self) -> NewSessions:
        if (self.job_id is None) == (self.pattern_id is None):
            raise ValueError("give job_id or pattern_id, not both")
        if self.start_by is not None and self.job_id is None:
            raise ValueError("start_by is for a job's tasks; practice begins at once")
        return self


class Submission(Model):
    code: str = Field(max_length=200_000)


class Task(Model):
    """What a candidate is shown. Never the hidden tests, the seed or the parameters.
    Before Start, not the story, requirements or starter either: read at leisure, a
    task's time limit would measure nothing."""

    session_id: str
    pattern_id: str
    title: str
    skill: str
    level: str
    story: str | None
    requirements: str | None
    starter: str | None
    time_limit_minutes: int
    issued_at: datetime.datetime
    start_by: datetime.datetime | None
    started_at: datetime.datetime | None
    deadline: datetime.datetime | None
    status: SessionStatus
    fitted_by_model: bool


class Issued(Model):
    tasks: list[Task]
    not_assessable: list[str]              # said, never dropped (guardrail 7)


class CandidateTest(Model):
    name: str
    group: str
    passed: bool


class CandidateResult(Model):
    """A result as its candidate sees it: which tests passed, not why the others
    failed — a failure's detail quotes the hidden test's input and expected answer,
    which would let the next attempt be fitted to the tests rather than the task."""

    session_id: str
    outcome: Outcome
    score: Score | None
    tests: list[CandidateTest]
    time_used_seconds: int
    note: str | None                       # the candidate's own error: an import failure, a timeout


# ── health, patterns, jobs ─────────────────────────────────────────────────


def _task(session: Session, variant: Variant) -> Task:
    pattern = load(variant.pattern_id)
    shown = session.started_at is not None
    return Task(
        session_id=session.session_id, pattern_id=variant.pattern_id, title=pattern.title,
        skill=pattern.skill, level=pattern.level.value,
        story=variant.story if shown else None,
        requirements=variant.requirements if shown else None,
        starter=variant.starter if shown else None,
        time_limit_minutes=variant.time_limit_minutes, issued_at=session.issued_at,
        start_by=session.start_by, started_at=session.started_at,
        deadline=session.deadline, status=session.status,
        fitted_by_model=variant.chosen_by == "model",
    )


def _job(db: Store, job_id: str) -> Job:
    if (job := db.job(job_id)) is None:
        raise RefusedError(404, "not_found", f"no job {job_id}")
    return job


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    """Unauthenticated, and about the sandbox only: could a submission run right now?
    Always 200 — the answer is in the body, so the web layer can say why not."""
    docker = shutil.which("docker") is not None
    image = False
    if docker:
        with contextlib.suppress(subprocess.TimeoutExpired):
            image = subprocess.run(["docker", "image", "inspect", settings.sandbox_image],
                                   capture_output=True, timeout=10).returncode == 0
    return {"status": "ok" if image else "degraded", "docker": docker,
            "image": settings.sandbox_image, "image_present": image}


@app.get("/v1/patterns")
def patterns(_: Auth) -> list[dict[str, Any]]:
    return [{"id": p.id, "version": p.version, "skill": p.skill, "title": p.title,
             "level": p.level.value, "time_limit_minutes": p.time_limit_minutes,
             "variants": p.combinations, "twists": sorted(p.twists)} for p in all_patterns()]


@app.post("/v1/jobs", status_code=201)
def new_job(_: Auth, db: Db, body: NewJob) -> Job:
    """Propose the skills a JD asks for. Every one is quoted from it, or dropped."""
    from assess.providers import default_provider

    job = jd.extract(body.text, default_provider() if body.model else None)
    db.save_job(job)
    return job


@app.get("/v1/jobs")
def jobs(_: Auth, db: Db) -> list[Job]:
    return db.jobs()


@app.get("/v1/jobs/{job_id}")
def get_job(_: Auth, db: Db, job_id: str) -> Job:
    return _job(db, job_id)


@app.patch("/v1/jobs/{job_id}")
def edit_job(_: Auth, db: Db, job_id: str, body: JobEdit) -> Job:
    try:
        job = jd.edit(_job(db, job_id), must=body.must, nice=body.nice, drop=body.drop)
        db.save_job(job)
    except ValueError as exc:              # JobError, and the store's own refusal
        raise RefusedError(409, "refused", str(exc)) from exc
    return job


@app.post("/v1/jobs/{job_id}/confirm")
def confirm_job(_: Auth, db: Db, job_id: str, body: Confirmation) -> Job:
    try:
        job = jd.confirm(_job(db, job_id), body.by)
        db.save_job(job)
    except ValueError as exc:
        raise RefusedError(409, "refused", str(exc)) from exc
    return job


@app.get("/v1/jobs/{job_id}/requirements")
def job_requirements(_: Auth, db: Db, job_id: str) -> dict[str, Any]:
    """schemas/job-requirements.schema.json — the body for M6's POST /shortlist."""
    try:
        return jd.requirements(_job(db, job_id))
    except jd.JobError as exc:
        raise RefusedError(409, "refused", str(exc)) from exc


# ── sessions, submission, results, events ──────────────────────────────────


def _session(db: Store, session_id: str) -> Session:
    """The session as it stands now: past its start-by date or deadline, expired."""
    if db.session(session_id) is None:
        raise RefusedError(404, "not_found", f"no session {session_id}")
    return current(db, session_id)


def _result(db: Store, session_id: str) -> Result:
    _session(db, session_id)
    if (result := db.result(session_id)) is None:
        raise RefusedError(404, "not_found", f"{session_id} has no result yet")
    return result


def candidate_view(result: Result) -> CandidateResult:
    return CandidateResult(
        session_id=result.session_id, outcome=result.outcome, score=result.score,
        tests=[CandidateTest(name=t.name, group=t.group, passed=t.passed) for t in result.tests],
        time_used_seconds=result.time_used_seconds, note=result.note,
    )


@app.post("/v1/sessions")
def new_sessions(_: Auth, db: Db, body: NewSessions) -> Issued:
    """Issue tasks — one per assessable must-have of a confirmed job, or one from a
    pattern. Asking again returns the tasks already issued, never fresh ones."""
    from assess.providers import default_provider

    if body.job_id is not None:
        _job(db, body.job_id)
    elif body.pattern_id not in {p.id for p in all_patterns()}:
        raise RefusedError(404, "not_found", f"no pattern {body.pattern_id}")
    try:
        if body.job_id is not None:
            issued, missing = start_for_job(db, body.job_id, body.candidate_ref,
                                            provider=default_provider() if body.model else None,
                                            start_by=body.start_by)
        else:
            assert body.pattern_id is not None
            issued, missing = [start(db, body.pattern_id, body.candidate_ref)], []
    except (SessionError, PatternError, VariantError) as exc:
        raise RefusedError(409, "refused", str(exc)) from exc
    if not issued:
        raise RefusedError(409, "nothing_assessable",
                      f"no task issued: no pattern tests {', '.join(missing) or 'any must-have'}")
    return Issued(tasks=[_task(s, v) for s, v in issued], not_assessable=missing)


@app.get("/v1/sessions/{session_id}")
def get_session(_: Auth, db: Db, session_id: str) -> Task:
    session = _session(db, session_id)
    variant = db.variant(session.variant_id, session.job_id)
    assert variant is not None
    return _task(session, variant)


@app.post("/v1/sessions/{session_id}/begin")
def begin_task(_: Auth, db: Db, session_id: str) -> Task:
    """The candidate presses Start: the clock runs from now and the task is shown. Again
    on a begun task, the same task; after its start-by date, 409."""
    _session(db, session_id)
    try:
        session = begin(db, session_id)
    except SessionError as exc:
        raise RefusedError(409, "refused", str(exc)) from exc
    variant = db.variant(session.variant_id, session.job_id)
    assert variant is not None
    return _task(session, variant)


@app.post("/v1/sessions/{session_id}/submit")
def submit_code(_: Auth, db: Db, session_id: str, body: Submission) -> CandidateResult:
    """Run the code in the sandbox. Synchronous: at most the 30 s wall clock."""
    _session(db, session_id)
    try:
        result = submit(db, session_id, body.code)
    except (SessionError, PatternError) as exc:
        raise RefusedError(409, "refused", str(exc)) from exc
    if not result.scored:
        # Guardrail 4: nothing was measured, the session stays open, nothing is stored.
        raise RefusedError(503, "sandbox_unavailable",
                      f"{result.note or 'the sandbox could not run'} — nothing was measured; "
                      "the session is still open, so submit again once it is fixed")
    return candidate_view(result)


@app.get("/v1/sessions/{session_id}/result", response_model=None)
def get_result(_: Auth, db: Db, session_id: str,
               view: Literal["candidate", "full"] = "candidate") -> CandidateResult | Result:
    """`candidate` by default: the view that reveals least is the one a caller gets
    without asking. `full` adds each failure's detail, for the person reading results."""
    result = _result(db, session_id)
    return result if view == "full" else candidate_view(result)


@app.get("/v1/sessions/{session_id}/events")
def get_events(_: Auth, db: Db, session_id: str) -> dict[str, Any]:
    """The result as an evidence batch — the body for M6's POST /evidence/batch.
    Validated against schemas/evidence-event.schema.json before it is returned."""
    try:
        return batch(_result(db, session_id))
    except NotEvidenceError as exc:
        raise RefusedError(409, "not_evidence", str(exc)) from exc
