"""Read-time propagation across ontology edges — O5, O7.

Three constraints, all deliberate:

  read time     Nothing propagated is ever stored. A stored propagated state
                would become a source for further propagation, and evidence would
                drift arbitrarily far through the ontology.
  one hop       Depth is a parameter, but the contract sets it to 1.
  direct only   Sources must be direct-evidence states. This is what makes the
                pass non-iterative and loop-free without needing cycle detection.

A neighbour enters as a pseudo-observation whose variance is inflated by
1/gamma, so damping reuses the observation mechanism instead of adding a second
one. Weak evidence and distant evidence are then the same kind of thing, which
is why they can share an update rule.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Iterable, Mapping

from .engine import ScoringEngine, SkillState
from .filter import State


class Propagator:
    """One hop out from the states that have direct evidence."""

    def __init__(self, engine: ScoringEngine) -> None:
        self.engine = engine
        self.p = engine.p

    def propagate(self, direct: Mapping[str, SkillState],
                  edges: Iterable[tuple[str, str, str]],
                  as_of: date) -> dict[str, SkillState]:
        """Returns direct states unchanged, plus states reachable in one hop.

        A skill that already has direct evidence is never overwritten: real
        evidence about a skill always beats an inference about it.
        """
        out: dict[str, SkillState] = dict(direct)
        for source_id, target_id, edge_type in edges:
            source = direct.get(source_id)
            if source is None or source.evidence_count == 0:
                continue                      # direct-evidence sources only
            if edge_type not in self.p.gamma:
                continue                      # one gamma per TYPE, never per edge
            if target_id in direct and direct[target_id].evidence_count > 0:
                continue                      # direct evidence wins
            out[target_id] = self._hop(source, target_id, edge_type,
                                       out.get(target_id), as_of)
        return out

    def _hop(self, source: SkillState, target_id: str, edge_type: str,
             existing: SkillState | None, as_of: date) -> SkillState:
        gamma = self.p.gamma[edge_type]
        tier = self.engine.tier_of(target_id)

        near = self.engine.filter.decayed_to(source.state, as_of, source.tier)
        far = existing.state if existing else self.engine.filter.initial(as_of)

        # Damping IS variance inflation — the same Kalman update as an
        # observation, with the neighbour's uncertainty widened by 1/gamma.
        obs_var = near.var / gamma
        k = far.var / (far.var + obs_var)
        moved = State(mu=far.mu + k * (near.mu - far.mu),
                      var=far.var * (1.0 - k), at=as_of)

        return SkillState(
            subject_ref=source.subject_ref, skill_id=target_id, state=moved, tier=tier,
            # Still zero: propagation is not evidence, and the query API has to
            # be able to say "inferred, not measured".
            evidence_count=0,
            parameter_version=self.p.parameter_version,
            newest_evidence_at=source.newest_evidence_at,
            propagated={"from_skill_id": source.skill_id, "edge_type": edge_type,
                        "gamma": gamma})


def edges_from_ontology(ontology) -> list[tuple[str, str, str]]:
    """Read (from, to, type) triples off an ontology.

    Prefers 6.1's typed `relations()`, so the Edge type is the actual integration
    surface rather than a convenience 6.1 offers and nobody takes. Falls back to
    the raw contract shape, because a test stub is allowed to be a bare object
    with an `edges` list and should not have to grow a class to say so.
    """
    relations = getattr(ontology, "relations", None)
    if callable(relations):
        return [edge.as_tuple() for edge in relations()]
    raw = getattr(ontology, "edges", None)
    if raw is None:
        return []
    return [(e["from"], e["to"], e["type"]) for e in raw]
