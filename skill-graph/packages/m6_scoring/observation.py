"""Event → observed ability, and event → observation variance.

This is the boundary the projection deliberately left open. An EvidenceEvent
carries no `observed` field — evidence-event.schema.json sets
additionalProperties:false and does not define one — so the projection emits raw
facts in `payload` and the number is computed here, from m6-parameters.yaml.
The projection decides what a repository IS; this decides what it is WORTH.

Two quantities, and keeping them separate is the whole design:

  observed  — what this evidence says the ability IS, in display space.
  variance  — how much to believe it: S0 / (reliability x relevance x strength).

Relevance is epistemic. A TypeScript repository that is 60% TypeScript is not
evidence of *worse* TypeScript ability; it is *weaker evidence* about TypeScript
ability. So relevance belongs in the variance and never in the observed value.
"""
from __future__ import annotations

from typing import Any, Mapping

from .errors import UnscoreableEvent
from .params import Parameters, default_parameters

# Display-space bounds. logit() is undefined at 0 and 1, and a contract value of
# exactly either would mean "certain", which no single event ever earns.
FLOOR, CEILING = 0.01, 0.99


def interpolate(anchors: Mapping[int, float], x: float) -> float:
    """Piecewise-linear lookup, clamped at both ends.

    The ECDF is a measured table, not a fitted curve — the contract is explicit
    that it is "a for-loop, not a training run".
    """
    keys = sorted(anchors)
    if x <= keys[0]:
        return float(anchors[keys[0]])
    if x >= keys[-1]:
        return float(anchors[keys[-1]])
    for low, high in zip(keys, keys[1:]):
        if low <= x <= high:
            span = high - low
            if span == 0:
                return float(anchors[low])
            weight = (x - low) / span
            return float(anchors[low]) + weight * (float(anchors[high]) - float(anchors[low]))
    raise AssertionError("unreachable: x is inside the anchor range")


class ObservationModel:
    """Turns one event document into (observed, variance)."""

    def __init__(self, params: Parameters | None = None) -> None:
        self.p = params or default_parameters()

    # ── observed value ──────────────────────────────────────────────────────
    def observed(self, event: Mapping[str, Any]) -> float:
        kind = event.get("kind")
        spec = self.p.observed_value.get(kind)
        if spec is None:
            raise UnscoreableEvent(
                f"{event.get('event_id')}: no observed_value rule for kind {kind!r}. "
                "Add one to m6-parameters.yaml rather than guessing here.")
        payload = event.get("payload") or {}

        if "observed" in spec:                       # a flat constant
            value = float(spec["observed"])
        elif spec.get("method") == "substance_band":
            value = self._from_band(event, spec, payload)
        elif spec.get("method") == "proficiency_band":
            value = self._from_proficiency(spec, payload)
        elif spec.get("method") == "percentile_against_reference":
            value = self._from_percentile(event, spec, payload)
        else:
            raise UnscoreableEvent(
                f"{event.get('event_id')}: observed_value.{kind} declares no usable method")
        return min(max(value, FLOOR), CEILING)

    def _from_band(self, event, spec, payload) -> float:
        band = payload.get("substance_band")
        bands = spec["bands"]
        if band not in bands:
            raise UnscoreableEvent(
                f"{event.get('event_id')}: substance_band {band!r} is not one of "
                f"{sorted(bands)}. The projection and the parameters disagree.")
        return float(bands[band]["observed"])

    def _from_proficiency(self, spec, payload) -> float:
        """The proficiency enum already on the Claim. An absent or unrecognised
        band takes the declared default — low RELIABILITY, not a low observed
        value, is what keeps an uncorroborated claim from moving a score."""
        bands = spec["bands"]
        band = payload.get("proficiency")
        if band not in bands:
            band = spec.get("default", "intermediate")
        return float(bands[band])

    def _from_percentile(self, event, spec, payload) -> float:
        """observed = a + b * ECDF_rated(rating).

        `a` encodes that being rated at all clears the general-population floor:
        the reference population for algorithmic ability is developers generally,
        not the self-selected cohort that competes.
        """
        rating = payload.get("max_rating")
        if rating is None:
            raise UnscoreableEvent(
                f"{event.get('event_id')}: platform_rating with no max_rating in payload")
        ecdf = interpolate(self.p.ecdf_anchors, float(rating))
        return float(spec["a"]) + float(spec["b"]) * ecdf

    # ── observation variance ────────────────────────────────────────────────
    def variance(self, event: Mapping[str, Any], skill_id: str) -> float:
        """S0 / (reliability x relevance x strength).

        High reliability, high relevance, high strength => low variance => the
        Kalman gain is large and the observation moves the estimate a lot.
        """
        relevance = self.relevance(event, skill_id)
        reliability = float(event.get("reliability", 0.0))
        strength = float(event.get("strength", 0.0))
        return self.p.s0 / max(reliability * relevance * strength, 1e-6)

    @staticmethod
    def relevance(event: Mapping[str, Any], skill_id: str) -> float:
        for ref in event.get("skill_refs") or []:
            if ref["skill_id"] == skill_id:
                return float(ref["relevance"])
        raise UnscoreableEvent(
            f"{event.get('event_id')} does not name skill {skill_id!r}")

    # ── both at once ────────────────────────────────────────────────────────
    def measure(self, event: Mapping[str, Any], skill_id: str) -> tuple[float, float]:
        return self.observed(event), self.variance(event, skill_id)

    @staticmethod
    def is_negative(event: Mapping[str, Any]) -> bool:
        return event.get("direction") == "negative"
