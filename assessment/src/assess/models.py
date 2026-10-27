"""The typed objects. Everything that crosses a function boundary is one of these.

`extra="forbid"` everywhere: a misspelled field in a pattern file or a stored record
is an error at load time, never a silently ignored setting.
"""

from __future__ import annotations

import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Scalar = str | int


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── patterns ───────────────────────────────────────────────────────────────


class Level(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class Twist(Model):
    rating: int = Field(ge=1)
    rule: str


class TestGroups(Model):
    core: list[str]
    twist: list[str]


class Pattern(Model):
    """One reusable task for one skill, written and reviewed by a person."""

    id: str
    version: int = Field(ge=1)
    skill: str
    title: str
    level: Level
    time_limit_minutes: int = Field(ge=5, le=240)
    language: Literal["python"]
    core: str
    parameters: dict[str, list[Scalar]]
    labels: dict[str, dict[str, str]] = Field(default_factory=dict)   # how a value reads in text
    twists: dict[str, Twist]
    tests: TestGroups
    directory: Path = Field(exclude=True)

    @model_validator(mode="after")
    def _equal_difficulty_by_construction(self) -> Pattern:
        # The whole case for comparing candidates on one pattern is that every variant
        # is equally hard. Parameters vary surface; twists are the only extra work, so
        # they must all carry one rating. Re-rating one means moving it out.
        if not self.twists:
            raise ValueError(f"{self.id}: a pattern needs at least one twist")
        if len({t.rating for t in self.twists.values()}) != 1:
            raise ValueError(f"{self.id}: twists must share one rating, or variants differ in difficulty")
        if any(not values for values in self.parameters.values()):
            raise ValueError(f"{self.id}: every parameter needs at least one allowed value")
        if "twist" in self.parameters:
            raise ValueError(f"{self.id}: 'twist' is reserved for the chosen twist")
        names = [*self.tests.core, *self.tests.twist]
        if len(names) != len(set(names)):
            raise ValueError(f"{self.id}: test names must be unique")
        return self

    @property
    def combinations(self) -> int:
        n = len(self.twists)
        for values in self.parameters.values():
            n *= len(values)
        return n


# ── variants and sessions ──────────────────────────────────────────────────


class Variant(Model):
    """One candidate's task. Different on the surface, identical in what is tested."""

    variant_id: str
    pattern_id: str
    pattern_version: int
    seed: int
    params: dict[str, Scalar]                       # includes "twist"
    chosen_by: Literal["seed", "model"]
    story: str
    story_by: Literal["template", "model"]
    requirements: str
    starter: str
    time_limit_minutes: int
    job_id: str | None = None
    created_at: datetime.datetime


class SessionStatus(StrEnum):
    OPEN = "open"
    SUBMITTED = "submitted"
    EXPIRED = "expired"


class Session(Model):
    session_id: str
    variant_id: str
    candidate_ref: str
    job_id: str | None = None
    started_at: datetime.datetime
    deadline: datetime.datetime
    status: SessionStatus = SessionStatus.OPEN


# ── runs and results ───────────────────────────────────────────────────────


class Outcome(StrEnum):
    """What happened to a submission. Only the last is not the candidate's doing."""

    PASSED = "passed"
    TESTS_FAILED = "tests_failed"
    IMPORT_ERROR = "import_error"          # the solution does not import: a syntax error, or it raised
    TIMEOUT = "timeout"                    # the whole run exceeded the wall clock
    RESOURCE_LIMIT = "resource_limit"      # killed for memory
    SANDBOX_UNAVAILABLE = "sandbox_unavailable"

    @property
    def scored(self) -> bool:
        return self is not Outcome.SANDBOX_UNAVAILABLE


class TestResult(Model):
    name: str
    group: Literal["core", "twist"]
    passed: bool
    detail: str | None = None


class Score(Model):
    passed: int
    total: int
    core_passed: int
    core_total: int
    twist_passed: int
    twist_total: int


class SandboxInfo(Model):
    image: str
    wall_seconds: float
    exit_code: int | None


class Result(Model):
    """Written once, never updated. No grade and no pass/fail field: what was tested,
    what happened, and how long it took."""

    session_id: str
    candidate_ref: str
    pattern_id: str
    pattern_version: int
    skill: str
    level: Level
    variant_id: str
    params: dict[str, Scalar]
    outcome: Outcome
    scored: bool
    tests: list[TestResult]
    score: Score | None
    time_used_seconds: int
    time_limit_minutes: int
    submitted_at: datetime.datetime
    sandbox: SandboxInfo
    note: str | None = None


# ── the JD layer ───────────────────────────────────────────────────────────


class Priority(StrEnum):
    MUST = "must"
    NICE = "nice"


class JobSkill(Model):
    """One skill a job description asks for, in the JD's own words."""

    skill_id: str | None                   # None: named in the JD, not on the skill list
    surface: str                           # as the JD names it
    quote: str                             # verbatim from the JD
    priority: Priority
    bar: float | None = Field(default=None, ge=0.0, le=1.0)   # must-haves only
    needs_review: bool = False
    assessable: bool = False               # a pattern exists for this skill


class JobStatus(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"


class Job(Model):
    job_id: str
    text: str
    text_sha256: str
    created_at: datetime.datetime
    status: JobStatus = JobStatus.PROPOSED
    skills: list[JobSkill] = Field(default_factory=list)
    extracted_by: str                      # "rules" or the model id
    dropped_unquoted: int = 0              # model items whose quote was not in the JD
    confirmed_by: str | None = None
    confirmed_at: datetime.datetime | None = None
