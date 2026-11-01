"""One candidate's task: different on the surface, identical in what is tested.

The parameters are chosen from the pattern's allowed values — by a seed, or by a model
reading the job description, but only ever FROM the list. Everything that is scored is
then produced by code: the requirements text the candidate is held to, and (in the
sandbox) the hidden tests, which read the same parameters.

Validity is the pattern's, not the variant's: a pattern is used only after its tests
were validated over EVERY combination, so every variant it can produce is already
covered. That validation is cached against a hash of the pattern's files, so editing
any one of them forces it to run again.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from assess.config import settings
from assess.models import Pattern, Scalar, Variant
from assess.patterns import PatternError, combinations, requirements, template_story
from assess.providers import LLMProvider
from assess.validation import ValidationReport, validate


class VariantError(ValueError):
    """No variant could be produced. The message says why."""


def params_key(pattern: Pattern, params: dict[str, Scalar]) -> str:
    """Identity of a variant: pattern, version and parameters — nothing else."""
    raw = json.dumps([pattern.id, pattern.version, sorted(params.items())], default=str)
    return "v_" + hashlib.sha256(raw.encode()).hexdigest()[:12]


def seeded(pattern: Pattern, seed: int) -> dict[str, Scalar]:
    rng = random.Random(f"{pattern.id}:{pattern.version}:{seed}")
    params: dict[str, Scalar] = {n: rng.choice(v) for n, v in sorted(pattern.parameters.items())}
    params["twist"] = rng.choice(sorted(pattern.twists))
    return params


# ── validation, once per pattern content ──────────────────────────────────


def content_hash(pattern: Pattern) -> str:
    h = hashlib.sha256()
    for path in sorted(pattern.directory.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            h.update(path.relative_to(pattern.directory).as_posix().encode())
            h.update(path.read_bytes())
    return h.hexdigest()[:16]


def _cache(pattern: Pattern, cache_dir: Path | None) -> Path:
    return (cache_dir or settings.db_path.parent / "validated") / f"{pattern.id}-{content_hash(pattern)}.json"


def remember_valid(pattern: Pattern, report: ValidationReport, cache_dir: Path | None = None) -> None:
    """Record a full validation that passed, for these exact files. `assess validate` calls
    it too, so the first task issued from a new pattern does not wait a minute or more for
    the proof — a recruiter's Send would otherwise sit through it."""
    if not report.ok or report.combinations != len(combinations(pattern)):
        return      # only a passing run over EVERY combination counts
    cache = _cache(pattern, cache_dir)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"ok": True, "pattern": pattern.id, "version": pattern.version,
                                 "combinations": report.combinations}))


def ensure_validated(pattern: Pattern, cache_dir: Path | None = None) -> None:
    """Refuse a pattern whose tests have not been proven right in every combination."""
    cache = _cache(pattern, cache_dir)
    if cache.is_file() and json.loads(cache.read_text()).get("ok"):
        return
    report = validate(pattern)
    if not report.ok:
        escaped = {m: len(e) for m, e in report.escapes.items() if e}
        raise PatternError(
            f"{pattern.id} v{pattern.version} failed validation: "
            f"{len(report.reference_failures)} reference failure(s), mutants escaping: {escaped}. "
            "Run `assess validate` for the detail."
        )
    remember_valid(pattern, report, cache_dir)


# ── the model's part: choose from the lists, word the story ──────────────


@dataclass(frozen=True)
class Choice:
    params: dict[str, Scalar]
    chosen_by: str          # "seed" | "model"
    story: str
    story_by: str           # "template" | "model"


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text.replace(",", "")))


def story_is_safe(story: str, params: dict[str, Scalar]) -> bool:
    """Every number in a story must be one of the variant's own values. A story that
    says "10 requests" over a limit of 5 would contradict the requirements a
    candidate is graded against — so it is discarded, not corrected."""
    allowed = {str(v) for v in params.values()}
    return bool(story.strip()) and _numbers(story) <= allowed


def model_choice(
    pattern: Pattern, fallback: dict[str, Scalar], context: str, provider: LLMProvider
) -> Choice:
    """Let a model fit the variant to a job description — choosing ONLY from the
    allowed values — and write the scenario. Any choice off a list is replaced by the
    seeded one; an unsafe or missing story by the template."""
    allowed: dict[str, list[Any]] = {**pattern.parameters, "twist": sorted(pattern.twists)}
    prompt = (
        "You prepare a coding task for a job candidate. The task is fixed; you only fit "
        "its surface to the job.\n\n"
        f"Job description:\n{context.strip()[:4000]}\n\n"
        f"Task: {pattern.title}. {' '.join(pattern.core.split())}\n\n"
        "1. For EACH parameter, choose ONE value from its allowed list that best fits the "
        "job. Do not invent values.\n"
        f"Allowed values: {json.dumps(allowed)}\n"
        f"Labels: {json.dumps(pattern.labels)}\n\n"
        "2. Write `story`: 2-3 sentences setting the scene in the job's industry — which "
        "service, which endpoint, why it needs this. Do NOT state requirements, numbers, "
        "limits or status codes; those are given separately. No numbers at all."
    )
    schema = {
        "type": "object",
        "properties": {
            "params": {"type": "object", "properties": {k: {} for k in allowed}},
            "story": {"type": "string"},
        },
        "required": ["params", "story"],
    }
    try:
        reply = provider.complete_json(prompt, schema)
    except Exception:  # a model outage must never stop a task being issued
        return Choice(fallback, "seed", template_story(pattern, fallback), "template")

    raw = reply.get("params")
    proposed: dict[str, Any] = raw if isinstance(raw, dict) else {}
    params: dict[str, Scalar] = {}
    for name, values in allowed.items():
        value = proposed.get(name)
        # Closed: a value off the list — or of the wrong type — is the seeded one.
        params[name] = value if value in values and isinstance(value, str | int) else fallback[name]
    by = "model" if proposed else "seed"
    story = reply.get("story") if isinstance(reply.get("story"), str) else ""
    if story and story_is_safe(story, params):
        return Choice(params, by, " ".join(story.split()), "model")
    return Choice(params, by, template_story(pattern, params), "template")


# ── generation ────────────────────────────────────────────────────────────


def generate(
    pattern: Pattern,
    seed: int,
    *,
    job_id: str | None = None,
    context: str | None = None,
    provider: LLMProvider | None = None,
    avoid: set[str] | frozenset[str] = frozenset(),
) -> Variant:
    """One candidate's task.

    `avoid` holds variant ids already issued for the same job, so two candidates for
    one role never get the same task while unused combinations remain.
    """
    ensure_validated(pattern)
    first = seeded(pattern, seed)
    choice = (
        model_choice(pattern, first, context, provider)
        if context and provider is not None
        else Choice(first, "seed", template_story(pattern, first), "template")
    )
    if params_key(pattern, choice.params) in avoid:
        # Taken for this job already. Uniqueness wins over fit: the next unused seeded
        # variant, with the template story — the model is not asked again.
        total = len(combinations(pattern))
        for attempt in range(1, 4 * total):
            candidate = seeded(pattern, seed + attempt)
            if params_key(pattern, candidate) not in avoid:
                choice = Choice(candidate, "seed", template_story(pattern, candidate), "template")
                break
        else:
            raise VariantError(f"all {total} variants of {pattern.id} are already issued for this job")

    return Variant(
        variant_id=params_key(pattern, choice.params),
        pattern_id=pattern.id,
        pattern_version=pattern.version,
        seed=seed,
        params=choice.params,
        chosen_by="model" if choice.chosen_by == "model" else "seed",
        story=choice.story,
        story_by="model" if choice.story_by == "model" else "template",
        requirements=requirements(pattern, choice.params),
        starter=(pattern.directory / "starter.py").read_text(),
        time_limit_minutes=pattern.time_limit_minutes,
        job_id=job_id,
        created_at=datetime.datetime.now(datetime.UTC),
    )
