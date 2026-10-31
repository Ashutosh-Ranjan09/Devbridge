"""Load contracts/m6-parameters.yaml.

The engine reads `value`; the sweep reads `sweep`. Both from this one file, so
they cannot drift apart — which is the whole reason the constants do not live in
Python. Nothing here is fitted.
"""
from __future__ import annotations

import functools
import pathlib
from dataclasses import dataclass
from typing import Any, Iterator

import yaml

CONTRACTS = pathlib.Path(__file__).resolve().parents[2] / "contracts"
DEFAULT_PARAMETERS = CONTRACTS / "m6-parameters.yaml"
DEFAULT_DISTRIBUTIONS = CONTRACTS / "reference-distributions.yaml"


def _value(node: Any) -> Any:
    """A parameter is either a scalar or a {value, sweep, rationale} block."""
    if isinstance(node, dict) and "value" in node:
        return node["value"]
    return node


@dataclass(frozen=True, slots=True)
class Sweepable:
    """One parameter the sensitivity sweep may vary, with its declared range."""
    name: str
    value: float
    low: float
    high: float

    def steps(self, n: int = 5) -> list[float]:
        if n < 2:
            return [self.value]
        return [self.low + (self.high - self.low) * i / (n - 1) for i in range(n)]


class Parameters:
    """Typed accessors over m6-parameters.yaml."""

    def __init__(self, raw: dict[str, Any], distributions: dict[str, Any] | None = None) -> None:
        self._raw = raw
        self._dist = distributions or {}

    @classmethod
    def load(cls, path: pathlib.Path | str | None = None,
             distributions: pathlib.Path | str | None = None) -> "Parameters":
        raw = yaml.safe_load(pathlib.Path(path or DEFAULT_PARAMETERS).read_text())
        dist = yaml.safe_load(pathlib.Path(distributions or DEFAULT_DISTRIBUTIONS).read_text())
        return cls(raw, dist)

    def replacing(self, **overrides: float) -> "Parameters":
        """A copy with named parameters overridden — how the sweep varies one
        constant without editing the contract on disk."""
        import copy
        raw = copy.deepcopy(self._raw)
        for dotted, value in overrides.items():
            node = raw
            *path, leaf = dotted.split("__")
            for key in path:
                node = node[key]
            if isinstance(node[leaf], dict) and "value" in node[leaf]:
                node[leaf]["value"] = value
            else:
                node[leaf] = value
        return Parameters(raw, self._dist)

    # ── identity ────────────────────────────────────────────────────────────
    @property
    def parameter_version(self) -> str:
        """Stamped onto every SkillState. A parameter change invalidates every
        stored state, and this is how a reader knows which set produced one."""
        return str(self._raw["contract_version"])

    # ── prior ───────────────────────────────────────────────────────────────
    @property
    def theta_0(self) -> float:
        return float(_value(self._raw["prior"]["theta_0"]))

    @property
    def sigma_0(self) -> float:
        return float(_value(self._raw["prior"]["sigma_0"]))

    # ── observation ─────────────────────────────────────────────────────────
    @property
    def s0(self) -> float:
        return float(_value(self._raw["observation"]["S0"]))

    @property
    def observed_value(self) -> dict[str, Any]:
        return self._raw["observed_value"]

    @property
    def ecdf_anchors(self) -> dict[int, float]:
        anchors = self.ecdf_anchors_for("codeforces")
        assert anchors is not None, "the Codeforces table is the published worked example"
        return anchors

    def ecdf_anchors_for(self, platform: str) -> dict[int, float] | None:
        """The rated-population ECDF for one platform's scale, or None if this
        repository holds none. Ratings on different platforms are different
        units; one table for all of them priced a CodeChef 3-star as a
        Codeforces expert."""
        table = self._dist.get(f"{platform}_rated_ecdf")
        if table is None:
            return None
        return {int(k): float(v) for k, v in table["anchors"].items()}

    @property
    def ecdf_status(self) -> str:
        return str(self._dist["codeforces_rated_ecdf"].get("status", "unknown"))

    # ── decay ───────────────────────────────────────────────────────────────
    @property
    def lambda_per_day(self) -> dict[str, float]:
        node = self._raw["decay"]["lambda_per_day"]
        return {tier: float(_value(spec)) for tier, spec in node.items()
                if tier in ("fundamental", "ecosystem", "framework")}

    @property
    def k_h(self) -> float:
        return float(_value(self._raw["decay"]["h_ratio_k"]))

    @property
    def default_tier(self) -> str:
        return str(self._raw["decay"]["skill_tiers"].get("default", "ecosystem"))

    @property
    def skill_tiers(self) -> dict[str, str]:
        """Fallback tier lookup. The ontology is authoritative for skills it
        carries — tier is a property of the skill, and duplicating it here was a
        pre-existing overlap, not a second opinion. A test asserts they agree."""
        node = self._raw["decay"]["skill_tiers"]
        return {skill: tier for tier, skills in node.items()
                if tier != "default" for skill in skills}

    def half_life(self, tier: str) -> float:
        """h_s = k / lambda_s. Mean-reversion tied to volatility rather than set
        independently — one swept constant instead of three."""
        return self.k_h / self.lambda_per_day[tier]

    # ── propagation & display ───────────────────────────────────────────────
    @property
    def gamma(self) -> dict[str, float]:
        return {edge: float(_value(spec))
                for edge, spec in self._raw["propagation"]["gamma_per_edge_type"].items()}

    @property
    def propagation_depth(self) -> int:
        return int(self._raw["propagation"]["depth"])

    @property
    def z(self) -> float:
        return float(_value(self._raw["display"]["z"]))

    # ── job match ───────────────────────────────────────────────────────────
    @property
    def match_weights(self) -> dict[str, float]:
        """How much a must-have and a nice-to-have count in a job match."""
        w = self._raw["job_match"]["weights"]
        return {"must": float(_value(w["must"])), "nice": float(_value(w["nice"]))}

    # ── the sweep's view ────────────────────────────────────────────────────
    def sweepable(self) -> Iterator[Sweepable]:
        """Every parameter declaring a `sweep` range, found by walking the tree.

        Discovered rather than listed, so adding a swept parameter to the YAML
        does not also require remembering to add it here.
        """
        def walk(node: Any, path: tuple[str, ...]) -> Iterator[Sweepable]:
            if isinstance(node, dict):
                if "sweep" in node and "value" in node:
                    low, high = node["sweep"]
                    yield Sweepable("__".join(path), float(node["value"]),
                                    float(low), float(high))
                    return
                for key, child in node.items():
                    yield from walk(child, path + (str(key),))
        yield from walk(self._raw, ())


@functools.lru_cache(maxsize=2)
def default_parameters() -> Parameters:
    return Parameters.load()
