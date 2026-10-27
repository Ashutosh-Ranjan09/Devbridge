"""Query logic, with no transport in it.

Reads the evidence log, folds through 6.3, and answers three questions:
what can this developer do, why does it say that, and who clears a bar.

What it deliberately cannot answer: "how good is this developer overall". There
is no such number in this system and this module does not invent one.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Sequence

from m6_scoring import Propagator, ScoringEngine, edges_from_ontology

from .errors import BadRequirements, UnknownSkill, UnknownSubject
from .ranking import Candidate, Tier, meets_threshold, tiers


REQUIREMENTS_SCHEMA = (Path(__file__).resolve().parents[3]
                       / "schemas" / "job-requirements.schema.json")


def _validate_requirements(doc: dict[str, Any]) -> None:
    """The same contract the assessment module writes — checked, not trusted."""
    import jsonschema
    try:
        jsonschema.validate(doc, json.loads(REQUIREMENTS_SCHEMA.read_text()))
    except jsonschema.ValidationError as exc:
        where = "/".join(str(p) for p in exc.absolute_path) or "(root)"
        raise BadRequirements(f"requirements invalid at {where}: {exc.message}") from exc


@dataclass(frozen=True, slots=True)
class SkillView:
    """One skill as the API presents it. Always an interval, never a bare point."""
    skill_id: str
    lower: float
    upper: float
    mean: float
    tier: str
    evidence_count: int
    days_since_newest_evidence: int | None
    propagated: dict[str, Any] | None

    @property
    def inferred(self) -> bool:
        return self.evidence_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            # `score` is the lower bound. Named plainly, but the interval is
            # always beside it so it cannot be read as a point estimate.
            "score": round(self.lower, 3),
            "interval": [round(self.lower, 3), round(self.upper, 3)],
            "mean": round(self.mean, 3),
            "volatility_tier": self.tier,
            "evidence_count": self.evidence_count,
            "inferred": self.inferred,
            "days_since_newest_evidence": self.days_since_newest_evidence,
            "propagated": self.propagated,
        }


class QueryService:
    def __init__(self, log, engine: ScoringEngine | None = None, *, ontology=None) -> None:
        self.log = log
        self.ontology = ontology
        self.engine = engine or ScoringEngine(ontology=ontology)

    # ── reading the log ─────────────────────────────────────────────────────
    def subjects(self) -> list[str]:
        return sorted({e.subject_ref for e in self.log.events()})

    def _events(self, subject_ref: str) -> list[dict]:
        events = [e.document for e in self.log.events(subject_ref)]
        if not events:
            raise UnknownSubject(f"no evidence on record for {subject_ref!r}")
        return events

    # ── the graph for one developer ─────────────────────────────────────────
    def skills(self, subject_ref: str, as_of: date, *, propagate: bool = True,
               include_inferred: bool = True,
               min_evidence: int = 0) -> list[SkillView]:
        events = self._events(subject_ref)
        # Fold each skill from the log's own filtered read rather than from every
        # event. events_for_skill() excludes events where the ontology could not
        # resolve THAT skill, so a quarantined skill never reaches a score — the
        # ingestor's decision has to hold on the read path too, or the quarantine
        # is decorative.
        states = {s: self.engine.fold(
                      [e.document for e in self.log.events_for_skill(s, subject_ref=subject_ref)],
                      s, as_of,
                      subject_ref=subject_ref)
                  for s in self.log.resolved_skills(subject_ref)}
        if propagate and self.ontology is not None:
            states = Propagator(self.engine).propagate(
                states, edges_from_ontology(self.ontology), as_of)

        z = self.engine.p.z
        views = []
        for state in states.values():
            if state.evidence_count < min_evidence:
                continue
            if not include_inferred and state.evidence_count == 0:
                continue
            lower, upper = state.state.interval(z)
            newest = state.newest_evidence_at
            views.append(SkillView(
                skill_id=state.skill_id, lower=lower, upper=upper,
                mean=state.state.mean, tier=state.tier,
                evidence_count=state.evidence_count,
                days_since_newest_evidence=(as_of - newest).days if newest else None,
                propagated=state.propagated))

        # Presented lower-bound first, but the interval travels with every row so
        # a reader can see which neighbours are actually separable.
        return sorted(views, key=lambda v: (-v.lower, v.skill_id))

    # ── the demo endpoint ───────────────────────────────────────────────────
    def explain(self, subject_ref: str, skill_id: str, as_of: date,
                *, propagate: bool = True) -> dict[str, Any]:
        """Why this number. The plan calls this the demo, so it carries the
        contributing events, the decay story, and what was NOT counted."""
        events = self._events(subject_ref)
        known = {r["skill_id"] for e in events for r in e.get("skill_refs") or []}

        state = self.engine.fold(events, skill_id, as_of, subject_ref=subject_ref)
        if state.evidence_count == 0 and propagate and self.ontology is not None:
            reached = Propagator(self.engine).propagate(
                self.engine.fold_all(events, as_of, subject_ref=subject_ref),
                edges_from_ontology(self.ontology), as_of)
            if skill_id in reached:
                state = reached[skill_id]

        if state.evidence_count == 0 and state.propagated is None and skill_id not in known:
            raise UnknownSkill(
                f"{skill_id!r} has no evidence and no path to any; "
                f"known here: {', '.join(sorted(known))}")

        out = self.engine.explain(state, as_of)
        z = self.engine.p.z
        out["interval"] = [round(state.state.score(z), 3), round(state.state.upper(z), 3)]
        out["subject_ref"] = subject_ref
        out["as_of"] = as_of.isoformat()
        out["basis"] = ("propagated" if state.propagated else
                        "prior" if state.evidence_count == 0 else "direct_evidence")
        out["not_counted"] = self._not_counted(subject_ref, skill_id)
        return out

    def _not_counted(self, subject_ref: str, skill_id: str) -> list[dict[str, str]]:
        """What the graph considered and left out.

        The projection records suppressions in not_emitted[]; surfacing them here
        is what lets a candidate see that a claim was read and rejected rather
        than never noticed. Silence is never an option.
        """
        import json
        out: list[dict[str, str]] = []
        for row in self.log.batches():
            if row["subject_ref"] != subject_ref:
                continue
            for entry in json.loads(row["not_emitted"] or "[]"):
                out.append({"what": entry["what"], "reason": entry["reason"]})
        held = self.log.quarantined()
        for event_id, skills in held.items():
            if skill_id in skills:
                out.append({"what": f"event {event_id} names {skill_id}, "
                                    "which is not in the ontology",
                            "reason": "skill_not_in_ontology"})
        return out

    # ── search ──────────────────────────────────────────────────────────────
    def search(self, skill_id: str, as_of: date, *, minimum: float = 0.0,
               definite: bool = True, include_inferred: bool = False,
               subjects: Iterable[str] | None = None) -> list[Tier]:
        """Who clears the bar for one skill.

        Returns TIERS, not a ranking. Within a tier the candidates cannot be
        separated on the evidence, and the API says so rather than inventing an
        order. `definite` chooses whether the whole interval must clear the bar
        or merely reach it — the caller's risk decision, never a default made
        quietly on their behalf.
        """
        found: list[Candidate] = []
        for subject_ref in (subjects if subjects is not None else self.subjects()):
            try:
                events = self._events(subject_ref)
            except UnknownSubject:
                continue
            state = self.engine.fold(events, skill_id, as_of, subject_ref=subject_ref)
            if state.evidence_count == 0 and include_inferred and self.ontology is not None:
                reached = Propagator(self.engine).propagate(
                    self.engine.fold_all(events, as_of, subject_ref=subject_ref),
                    edges_from_ontology(self.ontology), as_of)
                state = reached.get(skill_id, state)
            if state.evidence_count == 0 and state.propagated is None:
                continue                      # the prior is not a search result
            if not include_inferred and state.evidence_count == 0:
                continue

            z = self.engine.p.z
            lower, upper = state.state.interval(z)
            candidate = Candidate(
                subject_ref=subject_ref, skill_id=skill_id, lower=lower, upper=upper,
                evidence_count=state.evidence_count,
                propagated_from=(state.propagated or {}).get("from_skill_id"))
            if meets_threshold(candidate, minimum, definite=definite):
                found.append(candidate)
        return tiers(found)

    # ── a job's confirmed requirements → who qualifies ─────────────────────
    def shortlist(self, requirements: dict[str, Any], as_of: date, *,
                  definite: bool = True) -> dict[str, Any]:
        """Candidates whose every must-have clears its bar. Alphabetical, never ranked.

        `requirements` is ../schemas/job-requirements.schema.json — what the assessment
        module exports once a person has confirmed a job's skills. Each must-have is a
        FILTER: direct evidence for it, its interval clearing the bar (the lower bound by
        default, as `search` decides for one skill). Nice-to-haves are shown beside each
        candidate and filter nothing.

        Several skills are never combined into one order. That would need a weighted sum
        of intervals — an overall score by another name, which this system refuses. A
        reader compares the columns; the note in the answer says so.
        """
        _validate_requirements(requirements)
        musts = {m["skill_id"]: (None if m["bar"] is None else float(m["bar"])) for m in requirements["must"]}
        # A must-have without a bar is to be ASSESSED, not filtered on: shown, filters nobody.
        filters = {sk: bar for sk, bar in musts.items() if bar is not None}
        nice = list(requirements["nice"])
        known = set(getattr(self.ontology, "skill_ids", lambda: [])()) if self.ontology else None
        unknown = sorted(s for s in [*musts, *nice] if known is not None and s not in known)

        def view(v: SkillView | None) -> dict[str, Any] | None:
            return None if v is None else {
                "interval": [round(v.lower, 3), round(v.upper, 3)], "mean": round(v.mean, 3),
                "evidence_count": v.evidence_count, "inferred": v.inferred}

        candidates = []
        for subject_ref in self.subjects():
            views = {v.skill_id: v for v in self.skills(subject_ref, as_of)}
            # A must-have needs DIRECT evidence: an interval inferred from a neighbour
            # skill is a hint, not a demonstration, and does not qualify anyone.
            def clears(skill: str, bar: float) -> bool:
                v = views.get(skill)
                return v is not None and not v.inferred and (
                    v.lower >= bar if definite else v.upper >= bar)
            if all(clears(sk, bar) for sk, bar in filters.items()):
                candidates.append({
                    "subject_ref": subject_ref,
                    "must": {sk: view(views.get(sk)) for sk in musts},
                    "nice": {sk: view(views.get(sk)) for sk in nice},
                })
        return {
            "job_id": requirements["job_id"],
            "as_of": as_of.isoformat(),
            "match": ("every must-have's whole interval clears its bar" if definite
                      else "every must-have's interval reaches its bar"),
            "must": [{"skill_id": sk, "bar": bar, "filters": bar is not None} for sk, bar in musts.items()],
            "nice": nice,
            "considered": len(self.subjects()),
            "qualified": len(candidates),
            "candidates": sorted(candidates, key=lambda c: c["subject_ref"]),
            "unknown_skills": unknown,
            "not_on_list": list(requirements.get("not_on_list") or []),
            "note": ("Alphabetical, not ranked. Combining several skills into one order "
                     "would be an overall score; compare the intervals per skill."
                     + ("" if filters else " No must-have has a bar, so nothing filtered: "
                        "every candidate is listed, and the must-haves are to be assessed.")),
        }

    # ── the ontology, for a client building a filter UI ─────────────────────
    def known_skills(self) -> list[dict[str, Any]]:
        if self.ontology is None:
            return []
        return sorted(
            ({"skill_id": s, "volatility_tier": self.engine.tier_of(s),
              "half_life_days": round(self.engine.p.half_life(self.engine.tier_of(s)))}
             for s in getattr(self.ontology, "skill_ids", lambda: [])()),
            key=lambda r: r["skill_id"])
