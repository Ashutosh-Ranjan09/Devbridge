"""Which of M6's skills does each name in a report mean? — the fourth model call site.

A CV writes "React.js", a repository's manifest says `react`, GitHub's census says
"TypeScript". M6 scores skills by id from one shared list, `schemas/skills/`, and a
name it cannot place is set aside. Spelling rules catch most of them; they cannot
know that "Amazon Web Services" is `aws`. So the names a rule cannot place are
handed to the model with the list, and it answers ONE id from it, or none.

That is resolution, not judgement — the contract names `llm_tiebreak` for exactly
this, and the catalogue's rule for it is "a closed candidate set, or abstain". The
model never sees the CV, never adds a skill, and never decides whether a claim is
true. Three guards hold it:

  - **Closed.** An answer that is not an id on the list is `none`, whatever it says.
  - **Remembered.** Every decision is cached by name, so a name is asked once and
    the next CV gets the same answer. `cvv aliases` lists them; one promoted into
    `aliases.yaml` is a rule from then on, and no model is asked again.
  - **Recorded.** The report carries every decision and who made it, so M6 can label
    a skill the model placed, and a reviewer can see it.

Nothing here changes what M5's own rules see: they keep checking the CV's wording.
This only tells M6 what that wording refers to.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

import yaml

from cvv.logs import get
from cvv.models import ClaimGraph, EvidenceBundle, SkillDecision, SkillSource
from cvv.providers import LLMProvider

log = get("cvv.skills")

PROMPT_VERSION = "skills/v1"
# The shared list, at the repository root beside the schemas both modules read.
SKILLS_DIR = Path(__file__).resolve().parents[3] / "schemas" / "skills"
CACHE = Path(".cache/skill-resolution.json")
# Names per model call. A manifest can list seventy packages, and a small model given
# a hundred names at once starts skipping some; a skipped name is `none`, never a guess.
BATCH = 40

INSTRUCTION = """\
You map skill names to a fixed list of skills. For each name, answer the id of the
skill it IS — the same skill under another spelling or another name — or null.

- A library, tool, plugin or framework that BUILDS ON a skill is not that skill:
  react-dom, next-auth, React Native and nodemon are not react, nextjs or nodejs.
- A broader or narrower topic is not the skill: "web development" is not html.
- A different technology with a similar name is not the skill: Java is not javascript.
- If you are not sure, answer null. A wrong id credits a skill nobody claimed.

Answer every name, exactly as given."""


def load_skills(directory: Path = SKILLS_DIR) -> tuple[dict[str, str], dict[str, str], str]:
    """(id -> label, alias -> id, ontology version) from the shared list."""
    ontology = yaml.safe_load((directory / "ontology.yaml").read_text()) or {}
    aliases = yaml.safe_load((directory / "aliases.yaml").read_text()) or {}
    skills = {
        str(sid): str((spec or {}).get("label") or sid)
        for sid, spec in (ontology.get("skills") or {}).items()
    }
    table = {str(k).lower(): str(v) for k, v in (aliases.get("aliases") or {}).items()}
    return skills, table, str(ontology.get("ontology_version", "0"))


def names_in(graph: ClaimGraph, bundle: EvidenceBundle) -> list[str]:
    """Every skill-like name M6 will try to place: what the claims name, what the
    repositories' language census and manifests name. Order kept, case-duplicates
    dropped."""
    found: list[str] = [ref for c in graph.claims for ref in c.skill_refs]
    if bundle.github is not None:
        for repo in bundle.github.repos:
            found.extend(repo.languages)
            found.extend(repo.frameworks)
    seen: dict[str, str] = {}
    for name in found:
        if name.strip():
            seen.setdefault(name.strip().lower(), name.strip())
    return list(seen.values())


def by_rule(name: str, skills: dict[str, str], aliases: dict[str, str]) -> str | None:
    """The id a name IS, without asking anyone: the id itself, or an alias."""
    key = name.strip().lower()
    for candidate in (key, key.replace(" ", "_")):
        if candidate in skills:
            return candidate
    target = aliases.get(key)
    return target if target in skills else None


def resolve_skills(
    graph: ClaimGraph,
    bundle: EvidenceBundle,
    provider: LLMProvider | None,
    *,
    cache: Path = CACHE,
    directory: Path = SKILLS_DIR,
) -> dict[str, SkillDecision]:
    """Each name in the report -> the skill it means, and who decided.

    Rules first, then the cache, then the model for what is left. A model that is
    down or absent leaves those names `unresolved` — the verification still completes,
    and M6 falls back to its own spelling rules for them.
    """
    skills, aliases, version = load_skills(directory)
    remembered = _read_cache(cache, version)
    decisions: dict[str, SkillDecision] = {}
    ask: list[str] = []

    for name in names_in(graph, bundle):
        if (sid := by_rule(name, skills, aliases)) is not None:
            source = SkillSource.RULE if sid == name.strip().lower().replace(" ", "_") else SkillSource.ALIAS
            decisions[name] = SkillDecision(id=sid, by=source)
        elif (hit := remembered.get(name.lower())) is not None:
            # A remembered id that is no longer on the list is not an answer.
            sid = hit.get("id")
            decisions[name] = SkillDecision(id=sid if sid in skills else None, by=SkillSource.MODEL)
        else:
            ask.append(name)

    if ask and provider is not None:
        answered = _ask(provider, ask, skills)
        for name in ask:
            if name in answered:
                decisions[name] = SkillDecision(id=answered[name], by=SkillSource.MODEL)
                remembered[name.lower()] = {
                    "id": answered[name],
                    "name": name,
                    "model": provider.model_id,
                    "decided": datetime.date.today().isoformat(),
                }
        _write_cache(cache, version, remembered)

    for name in ask:
        decisions.setdefault(name, SkillDecision(id=None, by=SkillSource.UNRESOLVED))

    log.info(
        "skills.resolved",
        names=len(decisions),
        by_rule=sum(d.by in (SkillSource.RULE, SkillSource.ALIAS) for d in decisions.values()),
        by_model=sum(d.by is SkillSource.MODEL for d in decisions.values()),
        unresolved=sum(d.by is SkillSource.UNRESOLVED for d in decisions.values()),
    )
    return decisions


def _ask(provider: LLMProvider, names: list[str], skills: dict[str, str]) -> dict[str, str | None]:
    """The model's answers, closed over the list. A batch that fails is skipped and
    its names stay unresolved — it is never retried into a guess."""
    catalogue = "\n".join(f"{sid}: {label}" for sid, label in sorted(skills.items()))
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "mappings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "skill_id": {"type": ["string", "null"]},
                    },
                    "required": ["name", "skill_id"],
                },
            }
        },
        "required": ["mappings"],
    }
    answered: dict[str, str | None] = {}
    for start in range(0, len(names), BATCH):
        batch = names[start : start + BATCH]
        prompt = (
            f"{INSTRUCTION}\n\nSkills (id: label):\n{catalogue}\n\nNames:\n"
            + json.dumps(batch)
            + "\n\nReturn JSON only."
        )
        try:
            reply = provider.complete_json(prompt, schema)
        except Exception as exc:  # a model outage must never fail a verification
            log.warning("skills.model_failed", error=type(exc).__name__, names=len(batch))
            continue
        asked = {n.lower(): n for n in batch}
        for item in reply.get("mappings") or []:
            if not isinstance(item, dict):
                continue
            name = asked.get(str(item.get("name", "")).strip().lower())
            if name is None:
                continue  # a name we did not ask about
            sid = item.get("skill_id")
            # Closed: anything that is not an id on the list is `none`.
            answered[name] = sid if isinstance(sid, str) and sid in skills else None
    return answered


def _read_cache(path: Path, version: str) -> dict[str, dict[str, Any]]:
    """Decisions made against THIS version of the list. A name refused under 0.2.0
    may be a skill under 0.3.0, so another version's answers are not reused."""
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    decisions = (doc.get("by_ontology_version") or {}).get(version) or {}
    return {str(k): v for k, v in decisions.items() if isinstance(v, dict)}


def _write_cache(path: Path, version: str, decisions: dict[str, dict[str, Any]]) -> None:
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        doc = {}
    doc.setdefault("by_ontology_version", {})[version] = decisions
    doc["prompt_version"] = PROMPT_VERSION
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True))


def cached_decisions(cache: Path = CACHE, directory: Path = SKILLS_DIR) -> list[dict[str, Any]]:
    """What the model has decided under the current list, for `cvv aliases`."""
    _, aliases, version = load_skills(directory)
    rows = [
        {**v, "name": v.get("name", k), "promoted": k in aliases}
        for k, v in _read_cache(cache, version).items()
    ]
    return sorted(rows, key=lambda r: (r.get("id") is None, str(r.get("name")).lower()))


def promote(name: str, cache: Path = CACHE, directory: Path = SKILLS_DIR) -> str:
    """Make one model decision a rule: append `name: id` to aliases.yaml.

    Appended as a line rather than re-dumped, so the file's comments survive. Refuses
    a name the model mapped to nothing, one never decided, and one already aliased.
    """
    skills, aliases, version = load_skills(directory)
    key = name.strip().lower()
    decision = _read_cache(cache, version).get(key)
    if decision is None:
        raise KeyError(f"the model has not decided {name!r}; run a verification that names it")
    sid = decision.get("id")
    if sid not in skills:
        raise ValueError(f"{name!r} was mapped to no skill, so there is nothing to promote")
    if key in aliases:
        raise ValueError(f"{name!r} is already an alias of {aliases[key]!r}")
    path = directory / "aliases.yaml"
    text = path.read_text()
    line = f"  {json.dumps(key)}: {sid}\n"
    path.write_text(text if text.endswith("\n") else text + "\n")
    with path.open("a") as handle:
        handle.write(line)
    return str(sid)

