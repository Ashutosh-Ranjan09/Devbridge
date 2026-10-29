"""The job description layer: extract → edit → confirm → export.

A model PROPOSES the skills a job description asks for, choosing ids from the shared
skill list and quoting the JD's own words for each. Code checks every item; a person
edits and confirms. Nothing reaches the shortlist that a person has not confirmed.

  - **Grounded.** An item whose quote is not in the JD is dropped and counted — the same
    rule as M5's span grounding. A model that invents a requirement invents its quote.
  - **Closed.** An id not on the list is kept only as a surface name, "not on the skill
    list", so nobody assumes it was checked.
  - **Inferred is marked.** A skill whose quote does not literally name it ("protect
    our login endpoint" → rate_limiting) is kept, and marked for review.
  - **No model, no problem.** A rule-based fallback finds skills named as whole words
    and proposes them, every one marked for review.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import secrets
from typing import Any

from assess.models import Job, JobSkill, JobStatus, Priority
from assess.patterns import for_skill
from assess.providers import LLMProvider
from assess.skills import SkillList, skill_list


class JobError(ValueError):
    """The edit or confirmation is not allowed. The message says why."""


MUST_CUES = re.compile(r"\b(must|required|requires|need|needs|essential|mandatory|strong)\b", re.I)
NICE_CUES = re.compile(r"\b(plus|nice|bonus|preferred|familiar|familiarity|exposure|ideally)\b", re.I)


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _sentences(text: str, words: str) -> list[str]:
    """Every sentence or list line of the JD that contains `words`, bullets stripped."""
    out = []
    for piece in re.split(r"(?<=[.!?])\s+|\n+", text):
        clean = " ".join(piece.strip().lstrip("-*•·").split())
        if clean and words.lower() in clean.lower():
            out.append(clean)
    return out or [words]


def _assessable(skill_id: str | None) -> bool:
    return skill_id is not None and bool(for_skill(skill_id))


def _names(skill_id: str, skills: SkillList) -> set[str]:
    return {n for n, sid in skills.names().items() if sid == skill_id}


def by_rules(text: str, skills: SkillList) -> list[JobSkill]:
    out = []
    for skill_id, words in skills.find_in(text):
        # A skill named in several places is as required as its most demanding mention:
        # "Build services in Python" then "Strong Python is required" is a must-have.
        found = _sentences(text, words)
        demanding = [q for q in found if MUST_CUES.search(q) and not NICE_CUES.search(q)]
        quote = (demanding or found)[0]
        must = bool(demanding)
        out.append(JobSkill(skill_id=skill_id, surface=words, quote=quote,
                            priority=Priority.MUST if must else Priority.NICE,
                            needs_review=True, assessable=_assessable(skill_id)))
    return out


def by_model(text: str, skills: SkillList, provider: LLMProvider) -> tuple[list[JobSkill], int]:
    """(the skills, how many proposals were dropped for quoting text not in the JD)."""
    catalogue = "\n".join(f"{sid}: {label}" for sid, label in sorted(skills.labels.items()))
    prompt = (
        "Read this job description and list the technical skills it asks for.\n\n"
        f"Job description:\n{text.strip()[:6000]}\n\n"
        f"Skill list (id: label):\n{catalogue}\n\n"
        "For each skill the job asks for:\n"
        "- skill_id: the id from the list that it IS, or null if none on the list is it.\n"
        "  A requirement may imply a skill without naming it (\"protect the login endpoint\n"
        "  from abuse\" implies rate_limiting) — that is allowed; do not stretch further.\n"
        "- surface: the skill as the job names it.\n"
        "- quote: the job description's own words for it, copied EXACTLY, a phrase or sentence.\n"
        "- priority: \"must\" if required (must, required, need, strong), \"nice\" if a plus\n"
        "  (plus, nice to have, preferred, familiarity).\n"
        "Do not include soft skills, years of experience or degrees."
    )
    schema = {
        "type": "object",
        "properties": {"skills": {"type": "array", "items": {
            "type": "object",
            "properties": {"skill_id": {"type": ["string", "null"]}, "surface": {"type": "string"},
                           "quote": {"type": "string"}, "priority": {"type": "string"}},
            "required": ["skill_id", "surface", "quote", "priority"],
        }}},
        "required": ["skills"],
    }
    reply = provider.complete_json(prompt, schema)
    jd = _norm(text)
    out: list[JobSkill] = []
    dropped = 0
    for item in reply.get("skills") or []:
        if not isinstance(item, dict):
            continue
        quote = " ".join(str(item.get("quote") or "").split())
        if not quote or _norm(quote) not in jd:
            dropped += 1                          # grounded, or not at all
            continue
        sid = item.get("skill_id")
        sid = sid if isinstance(sid, str) and skills.knows(sid) else None
        surface = str(item.get("surface") or quote)
        try:
            priority = Priority(str(item.get("priority")).lower())
            unclear = False
        except ValueError:
            priority, unclear = Priority.NICE, True
        named = sid is not None and any(n in _norm(quote) for n in _names(sid, skills))
        out.append(JobSkill(skill_id=sid, surface=surface, quote=quote, priority=priority,
                            needs_review=unclear or (sid is not None and not named),
                            assessable=_assessable(sid)))
    return out, dropped


def _dedupe(items: list[JobSkill]) -> list[JobSkill]:
    """One row per skill. A must-have mention outranks a nice-to-have one."""
    seen: dict[str, JobSkill] = {}
    for s in items:
        key = s.skill_id or f"surface:{s.surface.lower()}"
        if key not in seen or (s.priority is Priority.MUST and seen[key].priority is Priority.NICE):
            seen[key] = s
    return list(seen.values())


def extract(text: str, provider: LLMProvider | None = None, *, job_id: str | None = None) -> Job:
    skills = skill_list()
    extracted_by, dropped = "rules", 0
    items: list[JobSkill]
    if provider is not None:
        try:
            items, dropped = by_model(text, skills, provider)
            extracted_by = provider.model_id
        except Exception:  # a model outage must never stop a job being entered
            items = by_rules(text, skills)
    else:
        items = by_rules(text, skills)
    return Job(
        job_id=job_id or "job_" + secrets.token_hex(5),
        text=text,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        created_at=datetime.datetime.now(datetime.UTC),
        skills=_dedupe(items),
        extracted_by=extracted_by,
        dropped_unquoted=dropped,
    )


def edit(
    job: Job,
    *,
    must: dict[str, float | None] | None = None,
    nice: list[str] | None = None,
    drop: list[str] | None = None,
) -> Job:
    """A person's changes to a proposed job. `must` maps id → bar (None keeps it);
    an id not yet in the job is added, quoted as added by the reviewer."""
    if job.status is JobStatus.CONFIRMED:
        raise JobError(f"{job.job_id} is confirmed; a confirmed job is never edited — enter a new one")
    skills = skill_list()
    rows = {s.skill_id: s for s in job.skills if s.skill_id}
    others = [s for s in job.skills if not s.skill_id]
    for sid in drop or []:
        if sid not in rows:
            raise JobError(f"{sid} is not in {job.job_id}")
        del rows[sid]
    for sid, bar in (must or {}).items():
        # model_copy below does not re-validate, so a bar out of range would be stored.
        if bar is not None and not 0.0 <= bar <= 1.0:
            raise JobError(f"{sid}: a bar is between 0 and 1, not {bar}")
    for sid, priority in [*((s, Priority.MUST) for s in (must or {})), *((s, Priority.NICE) for s in nice or [])]:
        if not skills.knows(sid):
            raise JobError(f"{sid!r} is not on the shared skill list")
        current = rows.get(sid) or JobSkill(skill_id=sid, surface=skills.labels[sid],
                                            quote="(added by the reviewer)", priority=priority,
                                            assessable=_assessable(sid))
        bar = (must or {}).get(sid) if priority is Priority.MUST else None
        rows[sid] = current.model_copy(update={
            "priority": priority, "needs_review": False,
            "bar": bar if bar is not None else (current.bar if priority is Priority.MUST else None),
        })
    return job.model_copy(update={"skills": [*rows.values(), *others]})


def confirm(job: Job, by: str) -> Job:
    if job.status is JobStatus.CONFIRMED:
        raise JobError(f"{job.job_id} is already confirmed")
    musts = [s for s in job.skills if s.skill_id and s.priority is Priority.MUST]
    if not musts:
        raise JobError("a job needs at least one must-have skill on the list to shortlist anyone")
    if not by.strip():
        raise JobError("say who confirmed it")
    # An unbarred must-have a pattern can test stays unbarred: it is to be ASSESSED,
    # not filtered on — nobody has evidence for a skill before they are tested on it,
    # so a bar would shortlist no one. An unbarred one nothing can test filters on
    # any direct evidence at all (0.0).
    skills = [s.model_copy(update={"bar": 0.0}) if s in musts and s.bar is None and not s.assessable
              else s for s in job.skills]
    return job.model_copy(update={
        "skills": skills, "status": JobStatus.CONFIRMED, "confirmed_by": by.strip(),
        "confirmed_at": datetime.datetime.now(datetime.UTC),
    })


def requirements(job: Job) -> dict[str, Any]:
    """The confirmed job as schemas/job-requirements.schema.json — what M6 reads."""
    if job.status is not JobStatus.CONFIRMED or job.confirmed_at is None or job.confirmed_by is None:
        raise JobError(f"{job.job_id} is not confirmed; only a confirmed job is exported")
    return {
        "schema_version": "1.0.0",
        "job_id": job.job_id,
        "confirmed_at": job.confirmed_at.isoformat(),
        "confirmed_by": job.confirmed_by,
        "skill_list_version": skill_list().version,
        "must": [{"skill_id": s.skill_id, "bar": s.bar, "assessable": s.assessable}
                 for s in job.skills if s.skill_id and s.priority is Priority.MUST],
        "nice": [s.skill_id for s in job.skills if s.skill_id and s.priority is Priority.NICE],
        "not_on_list": [s.surface for s in job.skills if not s.skill_id],
    }


def render(job: Job) -> str:
    lines = [f"{job.job_id} · {job.status.value} · extracted by {job.extracted_by}"
             + (f" · confirmed by {job.confirmed_by}" if job.confirmed_by else "")]
    if job.dropped_unquoted:
        lines.append(f"  ({job.dropped_unquoted} proposed skill(s) dropped: their quote is not in the JD)")
    for s in sorted(job.skills, key=lambda s: (s.priority is not Priority.MUST, s.skill_id or "~")):
        tag = s.skill_id or f"[not on list] {s.surface}"
        bar = (f" bar {s.bar:.2f}" if s.bar is not None else
               " assessed, not filtered" if job.status is JobStatus.CONFIRMED and s.priority is Priority.MUST else "")
        flags = " · review" if s.needs_review else ""
        flags += " · assessable" if s.assessable else ""
        lines.append(f"  {s.priority.value:4}  {tag:22}{bar}{flags}\n        \"{s.quote[:110]}\"")
    return "\n".join(lines)


def dumps(job: Job) -> str:
    return json.dumps(requirements(job), indent=2)
