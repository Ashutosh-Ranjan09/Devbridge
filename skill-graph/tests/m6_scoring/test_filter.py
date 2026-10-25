"""The Bayesian filter: properties rather than magic numbers.

A Kalman update has structural guarantees — variance never rises on an update,
the estimate never overshoots the observation, a precise observation dominates a
vague one. Asserting those catches a wrong sign or a swapped variance in a way
that comparing against one hand-computed number does not.
"""
import math
from datetime import date, timedelta

from scoring_fixtures import engine
from m6_scoring import Filter, State, logit, sigmoid
from m6_scoring.params import default_parameters

DAY = date(2025, 1, 1)


def filt() -> Filter:
    return Filter(default_parameters())


# ── the transform ───────────────────────────────────────────────────────────
def test_logit_and_sigmoid_invert_each_other():
    for p in (0.01, 0.25, 0.5, 0.74, 0.99):
        assert abs(sigmoid(logit(p)) - p) < 1e-12


def test_the_transform_survives_the_endpoints():
    """logit diverges at 0 and 1; clamping there beats raising in a filter that
    runs over user data. sigmoid must saturate rather than overflow — far out in
    the tail it underflows to exactly 0.0, which is correct, not a bug."""
    assert math.isfinite(logit(0.0)) and math.isfinite(logit(1.0))
    assert logit(0.0) < 0 < logit(1.0)
    assert sigmoid(-800) == 0.0 and sigmoid(800) == 1.0
    assert 0.0 < sigmoid(-30) < sigmoid(0) < sigmoid(30) < 1.0


def test_sigmoid_does_not_overflow_on_large_negative_input():
    assert sigmoid(-1000) >= 0.0


# ── the prior ───────────────────────────────────────────────────────────────
def test_the_prior_is_below_median():
    """O6 — a developer with no evidence is not an average developer, they are an
    unknown one. The system must not reward silence."""
    prior = filt().initial(DAY)
    assert abs(prior.mean - 0.25) < 1e-9
    assert prior.score(1.0) < prior.mean < 0.5


def test_the_prior_is_wide_enough_that_one_weak_event_cannot_carry_it():
    f = filt()
    prior = f.initial(DAY)
    weak = f.updated(prior, observed=0.95, obs_var=10.0)
    assert weak.score(1.0) < 0.45, "a single vague observation manufactured a score"


# ── the update ──────────────────────────────────────────────────────────────
def test_an_update_never_increases_variance():
    f = filt()
    state = f.initial(DAY)
    for obs_var in (0.01, 0.5, 5.0, 100.0):
        assert f.updated(state, 0.7, obs_var).var <= state.var + 1e-12


def test_the_estimate_moves_toward_the_observation_and_never_past_it():
    f = filt()
    state = f.initial(DAY)
    for observed in (0.05, 0.4, 0.9):
        moved = f.updated(state, observed, 0.3)
        low, high = sorted((state.mu, logit(observed)))
        assert low - 1e-12 <= moved.mu <= high + 1e-12


def test_a_precise_observation_dominates_a_vague_one():
    f = filt()
    state = f.initial(DAY)
    precise = f.updated(state, 0.9, obs_var=0.01)
    vague = f.updated(state, 0.9, obs_var=100.0)
    assert precise.mean > vague.mean
    assert abs(vague.mean - state.mean) < 0.02, "a vague observation moved the estimate a lot"


def test_gain_is_between_zero_and_one():
    f = filt()
    state = f.initial(DAY)
    for obs_var in (1e-6, 0.1, 1.0, 1e6):
        assert 0.0 <= f.gain(state, obs_var) <= 1.0


def test_repeated_identical_evidence_converges_on_it():
    f = filt()
    state = f.initial(DAY)
    for _ in range(60):
        state = f.updated(state, 0.80, obs_var=0.5)
    assert abs(state.mean - 0.80) < 0.01
    assert state.var < 0.05, "sixty observations should leave little uncertainty"


def test_update_order_does_not_change_the_result():
    """Gaussian updates commute. If they did not, the fold's ordering rule would
    be hiding a bug rather than merely making runs reproducible."""
    f = filt()
    a, b = (0.8, 0.2), (0.4, 1.5)
    forward = f.updated(f.updated(f.initial(DAY), *a), *b)
    backward = f.updated(f.updated(f.initial(DAY), *b), *a)
    assert abs(forward.mu - backward.mu) < 1e-9
    assert abs(forward.var - backward.var) < 1e-9


# ── decay ───────────────────────────────────────────────────────────────────
def test_decay_grows_variance_and_pulls_the_mean_toward_the_prior():
    f = filt()
    confident = State(mu=logit(0.9), var=0.05, at=DAY)
    later = f.decayed_to(confident, DAY + timedelta(days=1000), "framework")
    assert later.var > confident.var
    assert later.mean < confident.mean
    assert later.mean > 0.25, "mean-reversion must not overshoot the prior"


def test_decay_raises_a_low_estimate_toward_the_prior_too():
    """Mean reversion is toward the prior, not downward. A very low estimate must
    drift UP as it goes stale, or 'we know less' has become 'they got worse'."""
    f = filt()
    low = State(mu=logit(0.05), var=0.05, at=DAY)
    later = f.decayed_to(low, DAY + timedelta(days=3000), "framework")
    assert later.mean > low.mean


def test_most_of_the_lost_score_is_uncertainty_not_a_downgrade():
    """The story the numbers tell must be 'we know less', not 'they got worse'."""
    f = filt()
    fresh = State(mu=logit(0.8), var=0.05, at=DAY)
    stale = f.decayed_to(fresh, DAY + timedelta(days=800), "ecosystem")
    lost_to_variance = math.sqrt(stale.var) - math.sqrt(fresh.var)
    assert lost_to_variance > abs(stale.mean - fresh.mean)


def test_tiers_decay_at_the_declared_rates():
    f = filt()
    state = State(mu=logit(0.8), var=0.05, at=DAY)
    later = DAY + timedelta(days=500)
    variances = [f.decayed_to(state, later, t).var
                 for t in ("fundamental", "ecosystem", "framework")]
    assert variances == sorted(variances), "a framework must go stale faster than a fundamental"


def test_zero_and_negative_elapsed_time_are_no_ops():
    f = filt()
    state = State(mu=0.5, var=0.4, at=DAY)
    assert f.decayed_to(state, DAY, "ecosystem") == state
    assert f.decayed_to(state, DAY - timedelta(days=30), "ecosystem") == state


def test_decay_is_continuous_in_time():
    """No step change at any horizon — a discontinuity would make as_of queries
    jump for no reason a candidate could be told about."""
    f = filt()
    state = State(mu=logit(0.8), var=0.05, at=DAY)
    a = f.decayed_to(state, DAY + timedelta(days=365), "ecosystem")
    b = f.decayed_to(state, DAY + timedelta(days=366), "ecosystem")
    assert abs(b.mean - a.mean) < 0.01 and abs(b.var - a.var) < 0.01


def test_an_unknown_tier_falls_back_rather_than_raising():
    f = filt()
    assert f.lam("nonsense") == f.p.lambda_per_day[f.p.default_tier]


# ── display ─────────────────────────────────────────────────────────────────
def test_the_score_is_a_lower_bound_below_the_mean():
    state = State(mu=logit(0.7), var=0.3, at=DAY)
    assert state.score(1.0) < state.mean
    assert state.band(1.0) > 0


def test_a_wider_state_scores_lower_at_the_same_mean():
    """Uncertainty must cost something, or the bound is decoration."""
    narrow = State(mu=logit(0.7), var=0.05, at=DAY)
    wide = State(mu=logit(0.7), var=0.80, at=DAY)
    assert narrow.mean == wide.mean
    assert wide.score(1.0) < narrow.score(1.0)


def test_z_zero_makes_the_score_the_mean():
    state = State(mu=logit(0.7), var=0.3, at=DAY)
    assert abs(state.score(0.0) - state.mean) < 1e-12


def test_the_engine_uses_the_contracts_z():
    assert engine().p.z == 1.0
