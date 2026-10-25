"""The Bayesian filter: state, decay, update, score.

Everything runs in LOGIT space (O2), where ability is unbounded and the Kalman
update is therefore exact. Display space is sigmoid of that. sigmoid is
monotone, so a lower bound in logit space is still a lower bound after the
transform — which is what makes the displayed score a real confidence bound
rather than a decorated point estimate.

No fitting anywhere. Closed-form updates only.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date

from .params import Parameters, default_parameters

# Guards for the display<->logit transform, which diverges at 0 and 1.
_EPS = 1e-9


def logit(p: float) -> float:
    p = min(max(p, _EPS), 1.0 - _EPS)
    return math.log(p / (1.0 - p))


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)                     # avoids overflow for large negative x
    return e / (1.0 + e)


@dataclass(frozen=True, slots=True)
class State:
    """Latent ability for one (developer, skill), in logit space."""
    mu: float
    var: float
    at: date

    @property
    def mean(self) -> float:
        """The point estimate, in display space."""
        return sigmoid(self.mu)

    @property
    def sigma(self) -> float:
        return math.sqrt(self.var)

    def score(self, z: float) -> float:
        """Lower confidence bound. The published number is deliberately NOT the
        mean: a wide, uncertain estimate should not present as a confident one."""
        return sigmoid(self.mu - z * self.sigma)

    def upper(self, z: float) -> float:
        """Upper confidence bound. Only meaningful alongside `score`, which is
        the lower one — the pair is the interval, and the interval is the only
        thing two candidates may be compared on."""
        return sigmoid(self.mu + z * self.sigma)

    def interval(self, z: float) -> tuple[float, float]:
        return self.score(z), self.upper(z)

    def band(self, z: float) -> float:
        """Display-space half-width, mean - score. This is the `sigma` the
        explain response reports; `sigma_logit` carries the actual state."""
        return self.mean - self.score(z)


class Filter:
    """Decay and update, parameterised by m6-parameters.yaml."""

    def __init__(self, params: Parameters | None = None) -> None:
        self.p = params or default_parameters()
        self._mu_0 = logit(self.p.theta_0)

    def initial(self, at: date) -> State:
        """O6 — absent evidence, assume below median. A developer with no
        evidence is not an average developer; they are an unknown one."""
        return State(mu=self._mu_0, var=self.p.sigma_0 ** 2, at=at)

    def lam(self, tier: str) -> float:
        return self.p.lambda_per_day.get(tier, self.p.lambda_per_day[self.p.default_tier])

    def decayed_to(self, state: State, when: date, tier: str) -> State:
        """O6 — variance grows linearly, mu mean-reverts toward the prior.

        The story the numbers tell has to be "we know less now", not "they got
        worse". Both happen, but the variance term must dominate — asserted by
        test_most_of_the_lost_score_is_uncertainty_not_a_downgrade.
        """
        dt = max((when - state.at).days, 0)
        if dt == 0:
            return state
        lam = self.lam(tier)
        pull = 1.0 - math.exp(-dt * lam / self.p.k_h)
        return State(mu=state.mu + (self._mu_0 - state.mu) * pull,
                     var=state.var + lam * dt,
                     at=when)

    def updated(self, state: State, observed: float, obs_var: float) -> State:
        """Closed-form Kalman update on a Gaussian in logit space.

        k is the fraction of the way the estimate moves toward the observation.
        It falls out of the two variances; nothing is tuned.
        """
        k = state.var / (state.var + obs_var)
        return replace(state,
                       mu=state.mu + k * (logit(observed) - state.mu),
                       var=state.var * (1.0 - k))

    def gain(self, state: State, obs_var: float) -> float:
        """Exposed because /explain shows per-event contribution, and a reader
        deserves to see why one event moved the score and another did not."""
        return state.var / (state.var + obs_var)
