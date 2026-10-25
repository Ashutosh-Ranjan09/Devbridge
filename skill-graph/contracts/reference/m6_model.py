"""
DevBridge M6 — reference implementation of the scoring model.

The executable form of contracts/M6-DECISIONS.md. Deliberately dependency-free
and ~120 lines: this is the specification, not the service. The real 6.3
scoring-engine should reproduce these numbers exactly.

No trained models. No optimiser. No labelled data. Closed-form updates only.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from datetime import date

# ── parameters (mirror of m6-parameters.yaml) ────────────────────────────────
THETA_0, SIGMA_0, S0, Z, K_H = 0.25, 1.30, 0.10, 1.0, 0.35
LAMBDA = {"fundamental": 1.0e-4, "ecosystem": 3.0e-4, "framework": 7.5e-4}
GAMMA = {"PREREQUISITE_OF": 0.55, "REQUIRES": 0.65, "RELATED_TO": 0.40}
DEFAULT_TIER = "ecosystem"

logit = lambda p: math.log(p / (1.0 - p))
sigmoid = lambda x: 1.0 / (1.0 + math.exp(-x))


@dataclass
class State:
    """Latent ability for one (developer, skill), in LOGIT space — O2."""
    mu: float
    var: float
    at: date

    def decayed_to(self, t: date, tier: str) -> "State":
        """O6 — uncertainty grows, mu mean-reverts. The score falls because we
        know less, not because the person got worse."""
        dt = max((t - self.at).days, 0)
        if dt == 0:
            return self
        lam = LAMBDA.get(tier, LAMBDA[DEFAULT_TIER])
        mu0 = logit(THETA_0)
        return State(
            mu=self.mu + (mu0 - self.mu) * (1.0 - math.exp(-dt * lam / K_H)),
            var=self.var + lam * dt,
            at=t,
        )

    def updated(self, observed: float, obs_var: float) -> "State":
        """Closed-form Kalman update. No fitting anywhere."""
        k = self.var / (self.var + obs_var)
        return State(mu=self.mu + k * (logit(observed) - self.mu),
                     var=self.var * (1.0 - k), at=self.at)

    def score(self, z: float = Z) -> float:
        """Lower confidence bound, transformed for display. sigmoid is monotone,
        so the transformed bound is still a bound."""
        return sigmoid(self.mu - z * math.sqrt(self.var))

    @property
    def mean(self) -> float:
        return sigmoid(self.mu)


def observation_variance(reliability: float, relevance: float, strength: float) -> float:
    """O1/O3 — relevance is EPISTEMIC. It says how much this observation bears on
    this skill, not that the skill was demonstrated less well, so it belongs in
    the variance and never in the observed value."""
    return S0 / max(reliability * relevance * strength, 1e-6)


def initial(at: date) -> State:
    return State(mu=logit(THETA_0), var=SIGMA_0 ** 2, at=at)


def fold(events: list[dict], skill: str, tier: str, as_of: date) -> State:
    """O4 — recompute from the log, ordered by occurred_at. State is a derived
    cache, never a source of truth; that is what makes as_of queries, ablation
    and the parameter sweep cheap."""
    relevant = sorted(
        (e for e in events
         if e["occurred_at"] <= as_of
         and any(r["skill_id"] == skill for r in e["skill_refs"])),
        key=lambda e: (e["occurred_at"], e["event_id"]),   # total order, deterministic
    )
    if not relevant:
        return initial(as_of)
    st = initial(relevant[0]["occurred_at"])
    for e in relevant:
        st = st.decayed_to(e["occurred_at"], tier)
        rel = next(r["relevance"] for r in e["skill_refs"] if r["skill_id"] == skill)
        st = st.updated(e["observed"],
                        observation_variance(e["reliability"], rel, e["strength"]))
    return st.decayed_to(as_of, tier)


def propagate(direct: dict[str, State], edges: list[tuple[str, str, str]],
              tiers: dict[str, str], as_of: date) -> dict[str, State]:
    """O5/O7 — read time, one hop, from direct-evidence states only.

    A neighbour enters as a pseudo-observation whose variance is inflated by
    1/gamma, so damping reuses the observation mechanism rather than adding one.
    Sourcing only from direct states makes propagation non-iterative and
    loop-free: evidence does not travel arbitrarily far through the ontology.
    """
    out = dict(direct)
    for src, dst, edge_type in edges:
        if src not in direct:
            continue
        near = direct[src]
        far = out.get(dst) or initial(as_of)
        obs_var = near.var / GAMMA[edge_type]
        k = far.var / (far.var + obs_var)
        out[dst] = State(mu=far.mu + k * (near.mu - far.mu),
                         var=far.var * (1.0 - k), at=as_of)
    return out


def explain(st: State, skill: str) -> dict:
    """Response shape is fixed by cv-to-skill-graph.html §06. Note `sigma` is the
    DISPLAY-space half-width, which is what reconciles the published numbers;
    `sigma_logit` carries the actual state."""
    mean, score = st.mean, st.score()
    return {"skill": skill, "score": round(score, 3), "mean": round(mean, 3),
            "sigma": round(mean - score, 3), "sigma_logit": round(math.sqrt(st.var), 3)}
