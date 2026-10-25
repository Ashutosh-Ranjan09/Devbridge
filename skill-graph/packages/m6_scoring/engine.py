"""Recompute-from-log, SkillState, and the explain response.

O4: the state is a DERIVED CACHE, never a source of truth. Every score is
produced by folding the immutable evidence log in occurred_at order, so deleting
every SkillState loses nothing. That is what makes as_of queries, per-source
ablation and the parameter sweep cheap — each is just another fold.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from .errors import ParameterMismatch
from .filter import Filter, State
from .observation import ObservationModel
from .params import Parameters, default_parameters

SCHEMA_VERSION = "1.0.0"


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if len(text) == 10:
        return date.fromisoformat(text)
    moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return moment.astimezone(timezone.utc).date() if moment.tzinfo else moment.date()


def _ts(value: date) -> str:
    return f"{value.isoformat()}T00:00:00Z"


@dataclass(frozen=True, slots=True)
class Contribution:
    """One event's effect on one skill, kept so a score can be taken apart."""
    event_id: str
    kind: str
    occurred_at: date
    observed: float
    relevance: float
    obs_var: float
    gain: float
    mean_before: float
    mean_after: float


@dataclass(frozen=True, slots=True)
class SkillState:
    """Conforms to contracts/schemas/skill-state.schema.json."""
    subject_ref: str
    skill_id: str
    state: State
    tier: str
    evidence_count: int
    parameter_version: str
    event_ids: tuple[str, ...] = ()
    newest_evidence_at: date | None = None
    propagated: dict[str, Any] | None = None
    contributions: tuple[Contribution, ...] = field(default=(), compare=False)

    @property
    def is_prior_only(self) -> bool:
        """Zero evidence means the number is the prior. The query API must say
        so rather than reporting it as though it were measured."""
        return self.evidence_count == 0

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "subject_ref": self.subject_ref,
            "skill_id": self.skill_id,
            "mu": round(self.state.mu, 6),
            "var": round(self.state.var, 6),
            "as_of": _ts(self.state.at),
            "tier": self.tier,
            "evidence_count": self.evidence_count,
            "newest_evidence_at": _ts(self.newest_evidence_at) if self.newest_evidence_at else None,
            "provenance": {"parameter_version": self.parameter_version,
                           "event_ids": list(self.event_ids)},
        }
        if self.propagated is not None:
            out["propagated"] = self.propagated
        return out


class ScoringEngine:
    """Folds evidence into scores. Holds no state of its own between calls."""

    def __init__(self, params: Parameters | None = None, *,
                 ontology: Any = None) -> None:
        self.p = params or default_parameters()
        self.filter = Filter(self.p)
        self.observation = ObservationModel(self.p)
        self.ontology = ontology

    # ── tier resolution ─────────────────────────────────────────────────────
    def tier_of(self, skill_id: str) -> str:
        """The ontology is authoritative — tier is a property of the skill.
        m6-parameters.yaml's skill_tiers is a fallback for skills the ontology
        does not yet carry, and a test asserts the two never disagree."""
        if self.ontology is not None:
            tier = getattr(self.ontology, "tier", lambda _s: None)(skill_id)
            if tier:
                return tier
        return self.p.skill_tiers.get(skill_id, self.p.default_tier)

    # ── the fold ────────────────────────────────────────────────────────────
    def fold(self, events: Iterable[Mapping[str, Any]], skill_id: str, as_of: date,
             *, subject_ref: str = "", tier: str | None = None) -> SkillState:
        """Every event bearing on one skill, in order, into one state."""
        tier = tier or self.tier_of(skill_id)
        relevant = sorted(
            (e for e in events
             if _as_date(e["occurred_at"]) <= as_of
             and any(r["skill_id"] == skill_id for r in e.get("skill_refs") or [])),
            # (occurred_at, event_id) is a total order, so the fold is
            # deterministic even when two events share a day.
            key=lambda e: (_as_date(e["occurred_at"]), e["event_id"]))

        if not relevant:
            return SkillState(subject_ref=subject_ref, skill_id=skill_id,
                              state=self.filter.initial(as_of), tier=tier,
                              evidence_count=0,
                              parameter_version=self.p.parameter_version)

        first = _as_date(relevant[0]["occurred_at"])
        state = self.filter.initial(first)
        contributions: list[Contribution] = []

        for event in relevant:
            when = _as_date(event["occurred_at"])
            state = self.filter.decayed_to(state, when, tier)
            observed, obs_var = self.observation.measure(event, skill_id)
            gain = self.filter.gain(state, obs_var)
            before = state.mean
            state = self.filter.updated(state, observed, obs_var)
            contributions.append(Contribution(
                event_id=event["event_id"], kind=event["kind"], occurred_at=when,
                observed=observed, relevance=self.observation.relevance(event, skill_id),
                obs_var=obs_var, gain=gain, mean_before=before, mean_after=state.mean))

        state = self.filter.decayed_to(state, as_of, tier)
        return SkillState(
            subject_ref=subject_ref or str(relevant[0].get("subject_ref", "")),
            skill_id=skill_id, state=state, tier=tier, evidence_count=len(relevant),
            parameter_version=self.p.parameter_version,
            event_ids=tuple(e["event_id"] for e in relevant),
            newest_evidence_at=max(_as_date(e["occurred_at"]) for e in relevant),
            contributions=tuple(contributions))

    def fold_all(self, events: Sequence[Mapping[str, Any]], as_of: date,
                 *, subject_ref: str = "") -> dict[str, SkillState]:
        """Every skill any event mentions."""
        skills = {ref["skill_id"] for e in events for ref in e.get("skill_refs") or []}
        return {s: self.fold(events, s, as_of, subject_ref=subject_ref)
                for s in sorted(skills)}

    # ── ablation, which the fold makes nearly free ──────────────────────────
    def fold_without(self, events: Sequence[Mapping[str, Any]], skill_id: str, as_of: date,
                     *, origin: str | None = None, kind: str | None = None) -> SkillState:
        """Re-fold with one source held out. The report's ablation table is this
        function in a loop — no special machinery, because state is derived."""
        kept = [e for e in events
                if not (origin and (e.get("source") or {}).get("origin") == origin)
                and not (kind and e.get("kind") == kind)]
        return self.fold(kept, skill_id, as_of)

    # ── reading a stored state ──────────────────────────────────────────────
    def rehydrate(self, document: Mapping[str, Any], as_of: date | None = None) -> SkillState:
        """Load a persisted SkillState, refusing one from another parameter set."""
        stored = (document.get("provenance") or {}).get("parameter_version", "")
        if stored != self.p.parameter_version:
            raise ParameterMismatch(document["skill_id"], stored, self.p.parameter_version)
        state = State(mu=float(document["mu"]), var=float(document["var"]),
                      at=_as_date(document["as_of"]))
        tier = document["tier"]
        if as_of is not None:
            state = self.filter.decayed_to(state, as_of, tier)
        newest = document.get("newest_evidence_at")
        return SkillState(
            subject_ref=document["subject_ref"], skill_id=document["skill_id"],
            state=state, tier=tier, evidence_count=int(document["evidence_count"]),
            parameter_version=stored,
            event_ids=tuple((document.get("provenance") or {}).get("event_ids") or ()),
            newest_evidence_at=_as_date(newest) if newest else None,
            propagated=document.get("propagated"))

    # ── the explain response ────────────────────────────────────────────────
    def explain(self, skill_state: SkillState, as_of: date | None = None) -> dict[str, Any]:
        """The shape fixed by cv-to-skill-graph.html §06.

        `sigma` is the DISPLAY-space half-width (mean - score), not the logit
        state — that is what reconciles the published numbers. `sigma_logit`
        carries the state itself.
        """
        z = self.p.z
        st = skill_state.state
        as_of = as_of or st.at
        newest = skill_state.newest_evidence_at
        return {
            "skill": skill_state.skill_id,
            "score": round(st.score(z), 3),
            "mean": round(st.mean, 3),
            "sigma": round(st.band(z), 3),
            "sigma_logit": round(st.sigma, 3),
            "tier": skill_state.tier,
            "evidence_count": skill_state.evidence_count,
            "prior_only": skill_state.is_prior_only,
            "days_since_newest_evidence": (as_of - newest).days if newest else None,
            "half_life_days": round(self.p.half_life(skill_state.tier)),
            "parameter_version": skill_state.parameter_version,
            "propagated": skill_state.propagated,
            "contributions": [
                {"event_id": c.event_id, "kind": c.kind,
                 "occurred_at": _ts(c.occurred_at), "observed": round(c.observed, 3),
                 "relevance": round(c.relevance, 3), "weight": round(c.gain, 3),
                 "moved_mean_to": round(c.mean_after, 3)}
                for c in skill_state.contributions],
        }
