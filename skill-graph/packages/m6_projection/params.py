"""Load contracts/projection-rules.yaml.

The YAML is the single source of truth. Nothing in this package hard-codes a
threshold, a relevance constant or a reliability prior — change the contract and
the module changes with it, which is what lets the sensitivity sweep reach these
values without a code edit.
"""
from __future__ import annotations

import functools
import pathlib
from dataclasses import dataclass
from typing import Any

import yaml

DEFAULT_RULES = pathlib.Path(__file__).resolve().parents[2] / "contracts" / "projection-rules.yaml"
# Shared with M5's skill resolver at the repository root.
DEFAULT_ALIASES = pathlib.Path(__file__).resolve().parents[3] / "schemas" / "skills" / "aliases.yaml"


def load_aliases(path: pathlib.Path | str | None = None) -> dict[str, str]:
    """Other names for ontology skills, from the shared aliases.yaml."""
    doc = yaml.safe_load(pathlib.Path(path or DEFAULT_ALIASES).read_text()) or {}
    return {str(k): str(v) for k, v in (doc.get("aliases") or {}).items()}


@dataclass(frozen=True, slots=True)
class Priors:
    """strength / reliability_base / direction for one event kind."""
    strength: float
    reliability_base: float
    direction: str = "positive"


class Rules:
    """Typed accessors over projection-rules.yaml."""

    def __init__(self, raw: dict[str, Any], aliases: dict[str, str] | None = None) -> None:
        self._raw = raw
        # The alias table is its own file, shared with M5, so a contract edit here
        # cannot change what a skill name means on one side of the seam only.
        self._aliases = aliases if aliases is not None else load_aliases()
        self._t = raw["thresholds"]
        self._emit = {r["id"]: r for r in raw["emit"]}
        self._factors = {f["factor"]: f for f in raw["reliability_factors"]}

    # ── construction ────────────────────────────────────────────────────────
    @classmethod
    def load(cls, path: pathlib.Path | str | None = None) -> "Rules":
        p = pathlib.Path(path) if path else DEFAULT_RULES
        return cls(yaml.safe_load(p.read_text()))

    @property
    def contract_version(self) -> str:
        return str(self._raw["contract_version"])

    # ── per-kind priors ─────────────────────────────────────────────────────
    def priors(self, rule_id: str) -> Priors:
        r = self._emit[rule_id]
        strength = r.get("strength")
        # repo_artifact's strength is a formula, not a scalar; resolved per repo.
        return Priors(strength=float(strength) if isinstance(strength, (int, float)) else float("nan"),
                      reliability_base=float(r["reliability_base"]),
                      direction=str(r.get("direction", "positive")))

    def contradicting_rules(self) -> frozenset[str]:
        """M5 rule ids whose decisive finding contradicts the skills a claim names."""
        return frozenset(self._emit["claim_contradicted"].get("rules") or ())

    def factor(self, name: str) -> tuple[float, str, str]:
        """(multiplier, direction_scope, rationale)"""
        f = self._factors[name]
        return (float(f["value"]), str(f.get("direction_scope", "both")),
                " ".join(str(f.get("rationale", "")).split()))

    # ── thresholds ──────────────────────────────────────────────────────────
    @property
    def band_order(self) -> list[str]:
        return list(self._t["substance_bands"]["order"])

    def band_spec(self, name: str) -> dict[str, Any]:
        return dict(self._t["substance_bands"][name])

    @property
    def repo_strength(self) -> tuple[float, float]:
        s = self._t["strength"]["repo_artifact"]
        return float(s["base"]), float(s["per_band"])

    @property
    def language(self) -> dict[str, float]:
        return {k: float(v) for k, v in self._t["language_relevance"].items()}

    @property
    def framework(self) -> dict[str, Any]:
        f = dict(self._t["framework_relevance"])
        f["secondary_skills"] = set(f.get("secondary_skills", []))
        return f

    @property
    def manifest_known_only(self) -> bool:
        """Credit only manifest dependencies that are skills on the list."""
        cfg = self._t.get("manifest_dependencies") or {}
        return bool(cfg.get("known_only", False))

    @property
    def deployment_frameworks(self) -> tuple[str, ...]:
        """Frameworks a live deployment may credit, most specific first."""
        cfg = self._t.get("deployment_framework") or {}
        return tuple(str(v) for v in cfg.get("prefer") or ())

    @property
    def aliases(self) -> dict[str, str]:
        return {str(k).lower(): str(v) for k, v in self._aliases.items()}

    def claim_discount_factors(self, flags: Any, bound: Any) -> tuple[str, ...]:
        """Reliability factors earned by M5's own flags on a claim.

        M5 already records when a claim is an aggregate or an open bound. Reading
        those here is the difference between "500+ across three platforms" and a
        precise single-source claim entering the graph at the same weight.
        """
        cfg = self._t.get("claim_discounts") or {}
        by_flag = cfg.get("flags") or {}
        names = [by_flag[f] for f in (flags or []) if f in by_flag]
        by_bound = cfg.get("bounds") or {}
        if bound in by_bound:
            names.append(by_bound[bound])
        return tuple(dict.fromkeys(names))

    @property
    def corroboratable_metrics(self) -> frozenset[str]:
        """Metrics a platform can independently confirm part of."""
        cfg = self._t.get("partial_corroboration") or {}
        if not cfg.get("record_in_payload"):
            return frozenset()
        return frozenset(cfg.get("metrics") or ())

    @property
    def rated_platforms(self) -> frozenset[str]:
        """Platforms whose rating scale 6.3 holds a reference distribution for."""
        cfg = self._t.get("rating_reference") or {}
        return frozenset(str(v) for v in cfg.get("platforms") or ())

    @property
    def confirmable_metrics(self) -> tuple[str, ...]:
        """Metrics an unplaced platform may confirm a claim on — higher is better."""
        cfg = self._t.get("rating_reference") or {}
        return tuple(str(v) for v in cfg.get("confirmable_metrics") or ())

    @property
    def scraped_source_qualities(self) -> frozenset[str]:
        """source_quality values that mark a platform reading as a scrape."""
        cfg = self._t.get("scraped_source_quality") or {}
        return frozenset(str(v).lower() for v in (cfg.get("values") or ()))


@functools.lru_cache(maxsize=4)
def default_rules() -> Rules:
    return Rules.load()
