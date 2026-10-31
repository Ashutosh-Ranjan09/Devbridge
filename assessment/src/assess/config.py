"""Settings, from the environment and `.env`, prefix ASSESS_.

Every model setting is optional. A model is only ever asked to CHOOSE or to WORD
something; each such step has a code fallback, so an unset or unreachable backend
gives template stories, seeded parameters and rule-based JD skills — never a failure.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]          # assessment/
REPO = ROOT.parent                                  # devbridge/


class Settings(BaseSettings):
    # The module's own .env, wherever the command is run from. A path relative to the
    # working directory silently loaded nothing from elsewhere, and every model step
    # fell back without anyone being told.
    model_config = SettingsConfigDict(env_prefix="ASSESS_", env_file=ROOT / ".env", extra="ignore")

    # "claude-code" (the local wrapper cvv also uses) or "ollama".
    llm_backend: str = "claude-code"
    claude_code_url: str = "http://127.0.0.1:8000"
    claude_code_api_key: str | None = None
    claude_code_model: str | None = "sonnet"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:1.7b"
    num_ctx: int = 8192
    seed: int = 7
    request_timeout: float = 180.0

    # Bearer key for `assess serve`. Unset: one is generated and printed at startup.
    api_key: str | None = None

    sandbox_image: str = "assess-python:3.12"
    # Whole-container wall clock. Each test has its own 2 s limit inside it, so one
    # infinite loop fails one test rather than the run.
    sandbox_wall_seconds: float = 30.0
    # Accepted after the deadline before a submission is refused rather than scored.
    grace_seconds: int = 120
    # A job's task waits for the candidate to press Start, until its start-by date: this
    # many days after it is sent unless the recruiter chose one, and never further out
    # than the maximum.
    start_by_days: int = 7
    start_by_max_days: int = 60
    # Hidden-test submissions per task; the last one counts.
    max_attempts: int = 3
    # What one task is worth in an assessment's total, whatever its number of tests.
    points_per_task: int = 100

    patterns_dir: Path = ROOT / "patterns"
    skills_dir: Path = REPO / "schemas" / "skills"
    db_path: Path = ROOT / ".data" / "assess.db"


settings = Settings()
