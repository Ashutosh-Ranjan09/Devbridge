"""Parameter recovery — the plan's gate on everything downstream.

    "if the filter cannot recover a known ability from synthetic evidence,
     nothing downstream is worth building"

So: invent a developer with a known true ability, generate noisy evidence from
it through the same observation-variance formula the real engine uses, fold it
with the real filter, and ask whether the estimate comes back.

This is a simulation, not a fit. Nothing here trains anything — it measures
whether the closed-form update is doing what the design claims. The RNG is
seeded, so a regression shows up as a changed number rather than a flaky test.
"""
from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass
from datetime import date, timedelta

from .filter import Filter, logit, sigmoid
from .observation import ObservationModel
from .params import Parameters, default_parameters


@dataclass(frozen=True, slots=True)
class Trial:
    true_ability: float
    estimate: float
    lower_bound: float
    sigma_logit: float
    covered: bool
    events: int


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    trials: int
    events_per_trial: int
    bias: float
    rmse: float
    coverage: float
    mean_sigma: float
    worst_error: float

    @property
    def passed(self) -> bool:
        """The gate. Deliberately loose on coverage — z=1 is a display choice,
        not a calibration target — and strict on bias, which is the thing that
        would actually invalidate the ranking."""
        return abs(self.bias) < 0.05 and self.rmse < 0.15 and 0.45 <= self.coverage <= 0.95

    def render(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        return (f"parameter recovery — {self.trials} trials x {self.events_per_trial} events\n"
                f"  bias      {self.bias:+.4f}   (mean estimate - mean truth; want |bias| < 0.05)\n"
                f"  rmse      {self.rmse:.4f}   (want < 0.15)\n"
                f"  coverage  {self.coverage:.3f}    (truth inside mu +/- z*sigma; want 0.45-0.95)\n"
                f"  mean sigma {self.mean_sigma:.4f}  (logit space)\n"
                f"  worst     {self.worst_error:.4f}\n"
                f"{verdict}")


def simulate_trial(true_ability: float, n_events: int, rng: random.Random,
                   params: Parameters, *, tier: str = "ecosystem",
                   span_days: int = 400) -> Trial:
    """One developer, one skill, `n_events` noisy observations of a fixed truth.

    The observation noise is scaled by the SAME variance the engine will assume,
    so the filter is being tested against evidence that genuinely matches its
    model. Testing it against mismatched noise would measure robustness, which is
    a different and later question.
    """
    filt = Filter(params)
    model = ObservationModel(params)
    truth_logit = logit(true_ability)

    start = date(2024, 1, 1)
    when = [start + timedelta(days=rng.randint(0, span_days)) for _ in range(n_events)]
    when.sort()

    state = filt.initial(when[0])
    for moment in when:
        reliability = rng.uniform(0.4, 0.95)
        relevance = rng.uniform(0.5, 1.0)
        strength = rng.uniform(0.3, 0.8)
        obs_var = model.variance(
            {"reliability": reliability, "strength": strength,
             "skill_refs": [{"skill_id": "s", "relevance": relevance}]}, "s")
        observed = sigmoid(rng.gauss(truth_logit, math.sqrt(obs_var)))

        state = filt.decayed_to(state, moment, tier)
        state = filt.updated(state, observed, obs_var)

    z = params.z
    lower = state.mu - z * state.sigma
    return Trial(true_ability=true_ability, estimate=state.mean,
                 lower_bound=sigmoid(lower), sigma_logit=state.sigma,
                 covered=abs(truth_logit - state.mu) <= z * state.sigma,
                 events=n_events)


def run(trials: int = 300, events_per_trial: int = 12, seed: int = 20260901,
        params: Parameters | None = None) -> RecoveryReport:
    """Sweep true ability across the plausible range and see what comes back."""
    p = params or default_parameters()
    rng = random.Random(seed)
    results: list[Trial] = []
    for i in range(trials):
        # Spread truths evenly rather than sampling them, so the report is not
        # also measuring how lucky the draw of abilities was.
        truth = 0.10 + 0.80 * (i / max(trials - 1, 1))
        results.append(simulate_trial(truth, events_per_trial, rng, p))

    errors = [t.estimate - t.true_ability for t in results]
    return RecoveryReport(
        trials=trials, events_per_trial=events_per_trial,
        bias=statistics.fmean(errors),
        rmse=math.sqrt(statistics.fmean(e * e for e in errors)),
        coverage=statistics.fmean(1.0 if t.covered else 0.0 for t in results),
        mean_sigma=statistics.fmean(t.sigma_logit for t in results),
        worst_error=max(abs(e) for e in errors))


def convergence(events: tuple[int, ...] = (1, 2, 4, 8, 16, 32),
                trials: int = 200, seed: int = 20260901,
                params: Parameters | None = None) -> list[tuple[int, float]]:
    """RMSE against evidence count. More evidence must mean less error — if it
    does not, the update is wrong in a way no single-point check would show."""
    p = params or default_parameters()
    out: list[tuple[int, float]] = []
    for n in events:
        rng = random.Random(seed)
        errs = []
        for i in range(trials):
            truth = 0.10 + 0.80 * (i / max(trials - 1, 1))
            errs.append(simulate_trial(truth, n, rng, p).estimate - truth)
        out.append((n, math.sqrt(statistics.fmean(e * e for e in errs))))
    return out
