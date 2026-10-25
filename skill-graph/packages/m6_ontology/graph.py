"""The seed graph: which skills exist, how fast each decays, and what implies what.

Three things live here and nowhere else:

  membership   `knows()`. A skill_id M5 sends that is absent here is quarantined
               by 6.2 — stored, flagged, held out of scoring.
  volatility   `tier()`. The tier fixes lambda_s and therefore the half-life, so
               a wrong tier is the difference between a signal that fades in a
               year and one that holds for a decade. Tier is a claim about the
               SKILL and never about any candidate.
  edges        `relations()`. An edge asserts that evidence for one skill is
               genuine evidence for another — a strong thing to say, which is why
               the seed is sparse and 6.3 damps every hop.

Everything is read from contracts/ontology-seed.yaml. No skill, tier or edge is
defined in code, so the graph can be reviewed by someone who does not read Python.
"""
from __future__ import annotations

import functools
import pathlib
import re
from dataclasses import dataclass
from typing import Any, Iterator, Mapping, Sequence

import yaml

from .errors import InvalidOntology, UnknownSkill

SEED = pathlib.Path(__file__).resolve().parents[2] / "contracts" / "ontology-seed.yaml"

# skill_ids cross a service boundary and are matched exactly — quarantine, the
# fold, and propagation all key off the literal string. Allowing `React` and
# `react` to coexist would split one skill's evidence in two without any error.
SKILL_ID = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class Skill:
    skill_id: str
    label: str
    tier: str

    def to_dict(self) -> dict[str, str]:
        return {"skill_id": self.skill_id, "label": self.label, "volatility_tier": self.tier}


@dataclass(frozen=True, slots=True)
class Edge:
    """Directed. `source` implies something about `target`, not the reverse.

    RELATED_TO reads symmetric but is not: propagation only ever runs from a
    skill with direct evidence, so direction decides which way a signal can move.
    A genuinely two-way relation is two edges, written out.
    """
    source: str
    target: str
    type: str

    def as_tuple(self) -> tuple[str, str, str]:
        return (self.source, self.target, self.type)

    def to_dict(self) -> dict[str, str]:
        return {"from": self.source, "to": self.target, "type": self.type}


class SeedOntology:
    """The graph in contracts/ontology-seed.yaml, loaded and checked.

    Constructed from raw contract shapes rather than from Skill/Edge objects so
    that the file stays the source of truth and this class stays a reader of it.
    """

    def __init__(self, skills: Mapping[str, Mapping[str, Any]], version: str,
                 edges: Sequence[Mapping[str, str]] | None = None,
                 tiers: Mapping[str, str] | None = None) -> None:
        self._skills = dict(skills)
        self._version = version
        self._edges = [dict(e) for e in (edges or [])]
        self._tiers = dict(tiers or {})

    # ── loading ─────────────────────────────────────────────────────────────
    @classmethod
    def load(cls, path: pathlib.Path | str | None = None, *,
             strict: bool = True) -> "SeedOntology":
        """Read the seed and refuse to return a broken one.

        Strict by default because the failure this prevents is silent: an edge
        pointing at a skill that does not exist propagates nothing, and a missing
        tier decays at the default rate. Both produce plausible numbers that are
        simply wrong, with nothing downstream in a position to notice.
        """
        source = pathlib.Path(path or SEED)
        raw = yaml.safe_load(source.read_text()) or {}
        got = cls(raw.get("skills") or {}, str(raw.get("ontology_version", "0.0.0")),
                  raw.get("edges") or [], raw.get("tiers") or {})
        if strict:
            problems = got.validate()
            if problems:
                raise InvalidOntology(problems, str(source))
        return got

    def validate(self) -> list[str]:
        """Every structural problem in the graph, in one pass.

        Structural only. Whether `cpp REQUIRES algorithms` is *true* is a
        modelling judgement no checker can make; whether it points at a skill
        that exists is not.

        Deliberately absent: a cycle check. Propagation runs one hop from
        direct-evidence sources only, so a cycle cannot loop — flagging one would
        imply a constraint 6.3 does not actually have.
        """
        problems: list[str] = []
        if not self._version or self._version == "0.0.0":
            problems.append("ontology_version is missing — receipts would not "
                            "record which graph judged them")
        if not self._skills:
            problems.append("no skills: every incoming skill_ref would be quarantined")

        declared = set(self._tiers)
        for skill_id, entry in sorted(self._skills.items()):
            if not SKILL_ID.match(skill_id):
                problems.append(f"skill_id {skill_id!r} is not lower_snake_case; "
                                "ids are matched literally across the M5 boundary")
            if not isinstance(entry, Mapping):
                problems.append(f"{skill_id}: expected a mapping, got {type(entry).__name__}")
                continue
            tier = entry.get("tier")
            if not tier:
                problems.append(f"{skill_id}: no tier, so it would decay at the "
                                "default rate rather than its own")
            elif declared and tier not in declared:
                problems.append(f"{skill_id}: tier {tier!r} is not one of "
                                f"{', '.join(sorted(declared))}")

        seen: set[tuple[str, str, str]] = set()
        for i, edge in enumerate(self._edges):
            where = f"edge {i}"
            source, target, kind = (edge.get("from"), edge.get("to"), edge.get("type"))
            if not (source and target and kind):
                problems.append(f"{where}: needs from, to and type; got {edge!r}")
                continue
            where = f"edge {source} -> {target} ({kind})"
            for end, node in (("from", source), ("to", target)):
                if node not in self._skills:
                    problems.append(f"{where}: {end} names {node!r}, which is not a skill")
            if source == target:
                problems.append(f"{where}: a skill cannot imply itself")
            key = (source, target, kind)
            if key in seen:
                problems.append(f"{where}: duplicated")
            seen.add(key)
        return problems

    # ── the resolver port (this is all 6.2 may use) ─────────────────────────
    def knows(self, skill_id: str) -> bool:
        return skill_id in self._skills

    @property
    def ontology_version(self) -> str:
        return self._version

    # ── the rest, for 6.3 and 6.4 ───────────────────────────────────────────
    @property
    def edges(self) -> list[dict[str, str]]:
        """Raw contract shape, read by 6.3's `edges_from_ontology`."""
        return [dict(e) for e in self._edges]

    def relations(self) -> tuple[Edge, ...]:
        return tuple(Edge(e["from"], e["to"], e["type"]) for e in self._edges)

    def neighbours(self, skill_id: str) -> tuple[Edge, ...]:
        """Edges leading OUT of this skill — the hops evidence here can take."""
        return tuple(e for e in self.relations() if e.source == skill_id)

    def skill_ids(self) -> list[str]:
        """Every skill the ontology carries. Read by 6.4 to build a filter UI."""
        return sorted(self._skills)

    def skills(self) -> tuple[Skill, ...]:
        return tuple(self.skill(s) for s in self.skill_ids())

    def skill(self, skill_id: str) -> Skill:
        entry = self._skills.get(skill_id)
        if entry is None:
            raise UnknownSkill(f"{skill_id!r} is not in ontology {self._version}")
        return Skill(skill_id=skill_id,
                     label=str(entry.get("label") or skill_id),
                     tier=str(entry.get("tier") or ""))

    def tier(self, skill_id: str) -> str | None:
        """None rather than a default, so a caller with its own fallback can tell
        "this ontology has no opinion" from "this ontology says fundamental"."""
        entry = self._skills.get(skill_id)
        return entry.get("tier") if entry else None

    def label(self, skill_id: str) -> str | None:
        entry = self._skills.get(skill_id)
        return entry.get("label") if entry else None

    def by_tier(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {t: [] for t in self._tiers}
        for skill in self.skills():
            out.setdefault(skill.tier, []).append(skill.skill_id)
        return out

    @property
    def tiers(self) -> dict[str, str]:
        """Tier name -> the prose defining it, straight from the contract."""
        return dict(self._tiers)

    def to_dict(self) -> dict[str, Any]:
        return {"ontology_version": self._version,
                "tiers": sorted(self._tiers),
                "skills": [s.to_dict() for s in self.skills()],
                "edges": [e.to_dict() for e in self.relations()]}

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, skill_id: object) -> bool:
        return isinstance(skill_id, str) and self.knows(skill_id)

    def __iter__(self) -> Iterator[Skill]:
        return iter(self.skills())

    def __repr__(self) -> str:
        return (f"SeedOntology(version={self._version!r}, "
                f"skills={len(self._skills)}, edges={len(self._edges)})")


@functools.lru_cache(maxsize=2)
def default_ontology() -> SeedOntology:
    """The seed, loaded once. Cached because it is read on every ingest and the
    file cannot change under a running process without a redeploy."""
    return SeedOntology.load()
