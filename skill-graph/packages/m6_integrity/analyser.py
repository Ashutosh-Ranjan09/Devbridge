"""The nine checks.

Every one reads the evidence log and the folded states, and every one returns
findings. Nothing here writes to the log, mutates a state, or adjusts a score —
`test_no_score_moves` asserts that by folding the graph with and without 6.5
running and comparing every number.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from .findings import SEVERITY_ORDER, Finding, IntegrityReport
from .rules import IntegrityRules, default_rules


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


def _origin(event: Mapping[str, Any]) -> str:
    return (event.get("source") or {}).get("origin", "unknown")


def _skills_of(event: Mapping[str, Any]) -> list[str]:
    return [r["skill_id"] for r in event.get("skill_refs") or []]


class IntegrityAnalyser:
    """Reads a graph; writes nothing."""

    def __init__(self, rules: IntegrityRules | None = None, *, engine: Any = None) -> None:
        self.rules = rules or default_rules()
        self.engine = engine          # only for half-life lookups; never for scoring

    # ── entry point ─────────────────────────────────────────────────────────
    def analyse(self, events: Sequence[Mapping[str, Any]], as_of: date, *,
                subject_ref: str = "", states: Mapping[str, Any] | None = None,
                quarantined: Mapping[str, Sequence[str]] | None = None
                ) -> IntegrityReport:
        by_skill: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for event in events:
            for skill in _skills_of(event):
                by_skill[skill].append(event)

        found: list[Finding] = []
        for check in (self._burst, self._ownership, self._breadth, self._quarantined):
            found.extend(check(events, as_of, by_skill, quarantined or {}))
        for skill, supporting in sorted(by_skill.items()):
            for check in (self._single_source, self._claim_only,
                          self._contradicted, self._wholly_stale):
                found.extend(check(skill, supporting, as_of))
        found.extend(self._inferred_only(states or {}))

        total = max(len(by_skill), 1)
        found.sort(key=lambda f: (SEVERITY_ORDER.get(f.severity, 9),
                                  -len(f.skills) / total, f.check_id))
        cap = self.rules.max_findings
        return IntegrityReport(
            subject_ref=subject_ref, as_of=as_of.isoformat(),
            contract_version=self.rules.contract_version,
            findings=tuple(found[:cap]), events_examined=len(events),
            skills_examined=len(by_skill), truncated=max(len(found) - cap, 0))

    def _make(self, check_id: str, summary: str, detail: str, *,
              skills: Iterable[str] = (), event_ids: Iterable[str] = (),
              **metrics: Any) -> Finding:
        return Finding(
            check_id=check_id, severity=self.rules.severity(check_id),
            summary=summary, detail=detail,
            innocent_explanation=self.rules.innocent_explanation(check_id),
            skills=tuple(sorted(skills)), event_ids=tuple(sorted(event_ids)),
            metrics=metrics)

    # ── whole-graph checks ──────────────────────────────────────────────────
    def _burst(self, events, as_of, by_skill, _q) -> list[Finding]:
        cid = "EVIDENCE_BURST"
        if not self.rules.enabled(cid) or not events:
            return []
        window = int(self.rules.param(cid, "window_days", 45))
        recent = [e for e in events if (as_of - _as_date(e["occurred_at"])).days <= window]
        share = len(recent) / len(events)
        if (len(recent) < int(self.rules.param(cid, "min_events", 4))
                or share < float(self.rules.param(cid, "min_share", 0.60))):
            return []
        return [self._make(
            cid,
            f"{len(recent)} of {len(events)} events are from the {window} days "
            f"before verification",
            f"{share:.0%} of the evidence was created inside one {window}-day window "
            "immediately before the CV was checked, so the graph reflects a short "
            "burst of activity rather than a sustained record.",
            skills={s for e in recent for s in _skills_of(e)},
            event_ids=[e["event_id"] for e in recent],
            window_days=window, share=round(share, 3),
            events_in_window=len(recent), events_total=len(events))]

    def _ownership(self, events, _as_of, _by_skill, _q) -> list[Finding]:
        cid = "OWNERSHIP_UNPROVEN"
        if not self.rules.enabled(cid) or not events:
            return []
        capped = [e for e in events
                  if any(f.get("factor") == "ownership_unverified"
                         for f in e.get("reliability_factors") or [])]
        share = len(capped) / len(events)
        if (len(capped) < int(self.rules.param(cid, "min_events", 3))
                or share < float(self.rules.param(cid, "min_share", 0.50))):
            return []
        return [self._make(
            cid,
            f"{share:.0%} of the evidence depends on an unproven account identity",
            f"{len(capped)} of {len(events)} events are attributed through a GitHub "
            "handle that was never confirmed by OAuth or a challenge. Their "
            "reliability is already capped; this is how much of the graph rests on "
            "that one assumption.",
            skills={s for e in capped for s in _skills_of(e)},
            event_ids=[e["event_id"] for e in capped],
            share=round(share, 3), capped_events=len(capped), events_total=len(events))]

    def _breadth(self, events, _as_of, _by_skill, _q) -> list[Finding]:
        cid = "BREADTH_FROM_ONE_ARTEFACT"
        if not self.rules.enabled(cid):
            return []
        threshold = int(self.rules.param(cid, "min_skills", 5))
        out = []
        for event in events:
            skills = _skills_of(event)
            if len(skills) >= threshold:
                out.append(self._make(
                    cid,
                    f"{len(skills)} skills come from the single artefact "
                    f"{event['event_id']}",
                    "These skills are not independently supported: one artefact "
                    "produced all of them, so they move together and a problem with "
                    "it affects every one.",
                    skills=skills, event_ids=[event["event_id"]],
                    skill_count=len(skills), kind=event.get("kind")))
        return out

    def _quarantined(self, _events, _as_of, _by_skill, quarantined) -> list[Finding]:
        cid = "QUARANTINED_EVIDENCE"
        if not self.rules.enabled(cid) or not quarantined:
            return []
        skills = {s for names in quarantined.values() for s in names}
        return [self._make(
            cid,
            f"{len(quarantined)} event(s) held out of scoring over "
            f"{len(skills)} unknown skill(s)",
            "The evidence was accepted and stored, but names skills the ontology "
            f"does not carry ({', '.join(sorted(skills))}), so it contributes "
            "nothing until those are added.",
            skills=skills, event_ids=quarantined.keys(),
            held_events=len(quarantined))]

    # ── per-skill checks ────────────────────────────────────────────────────
    def _single_source(self, skill, supporting, _as_of) -> list[Finding]:
        cid = "SINGLE_SOURCE"
        if not self.rules.enabled(cid):
            return []
        if len(supporting) < int(self.rules.param(cid, "min_events", 2)):
            return []
        origins = {_origin(e) for e in supporting}
        if len(origins) > 1:
            return []
        origin = next(iter(origins))
        return [self._make(
            cid, f"{skill}: all {len(supporting)} events come from {origin}",
            f"Nothing independent corroborates {skill}. If {origin} is wrong or "
            "incomplete, the whole score for this skill is wrong with it.",
            skills=[skill], event_ids=[e["event_id"] for e in supporting],
            origin=origin, events=len(supporting))]

    def _claim_only(self, skill, supporting, _as_of) -> list[Finding]:
        cid = "CLAIM_ONLY"
        if not self.rules.enabled(cid):
            return []
        if any(e.get("kind") != "cv_claim" for e in supporting):
            return []
        return [self._make(
            cid, f"{skill} rests only on self-reported claims",
            f"All {len(supporting)} events for {skill} are unverified CV claims. "
            "The low reliability already reflects that; the score is a floor, not "
            "a measurement.",
            skills=[skill], event_ids=[e["event_id"] for e in supporting],
            events=len(supporting))]

    def _contradicted(self, skill, supporting, _as_of) -> list[Finding]:
        cid = "CONTRADICTED"
        if not self.rules.enabled(cid):
            return []
        negative = [e for e in supporting if e.get("direction") == "negative"]
        positive = [e for e in supporting if e.get("direction") != "negative"]
        if not (negative and positive):
            return []
        return [self._make(
            cid, f"{skill} has both supporting and contradicting evidence",
            f"{len(positive)} event(s) support {skill} and {len(negative)} "
            "contradict it. The filter has folded both; a reader deciding on this "
            "skill should look at them directly.",
            skills=[skill],
            event_ids=[e["event_id"] for e in supporting],
            supporting=len(positive), contradicting=len(negative))]

    def _wholly_stale(self, skill, supporting, as_of) -> list[Finding]:
        cid = "WHOLLY_STALE"
        if not self.rules.enabled(cid) or self.engine is None:
            return []
        tier = self.engine.tier_of(skill)
        half_life = self.engine.p.half_life(tier)
        newest = max(_as_date(e["occurred_at"]) for e in supporting)
        age = (as_of - newest).days
        if age <= half_life:
            return []
        return [self._make(
            cid, f"{skill}: newest evidence is {age} days old, past its "
                 f"{round(half_life)}-day half-life",
            f"Every event for {skill} predates its own half-life, so the number is "
            "now driven more by decay toward the prior than by anything observed.",
            skills=[skill], event_ids=[e["event_id"] for e in supporting],
            age_days=age, half_life_days=round(half_life), tier=tier)]

    def _inferred_only(self, states) -> list[Finding]:
        cid = "INFERRED_ONLY"
        if not self.rules.enabled(cid):
            return []
        out = []
        for skill, state in sorted(states.items()):
            block = getattr(state, "propagated", None)
            if not block:
                continue
            out.append(self._make(
                cid, f"{skill} has no direct evidence; it is inferred from "
                     f"{block['from_skill_id']}",
                f"The score for {skill} comes from a {block['edge_type']} edge out of "
                f"{block['from_skill_id']}, damped by gamma={block['gamma']}. Nothing "
                "in the evidence log mentions this skill at all.",
                skills=[skill], from_skill=block["from_skill_id"],
                edge_type=block["edge_type"], gamma=block["gamma"]))
        return out
