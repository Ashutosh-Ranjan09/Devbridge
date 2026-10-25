"""The gate: can the filter recover a known ability from synthetic evidence?

The plan is unambiguous — "if the filter cannot recover a known ability from
synthetic evidence, nothing downstream is worth building". These tests are that
check, run every time the suite runs rather than once by hand.
"""
from m6_scoring import recovery
from m6_scoring.params import default_parameters


def test_the_gate_passes():
    report = recovery.run(trials=200, events_per_trial=12)
    assert report.passed, report.render()


def test_the_estimate_is_close_to_the_truth_on_average():
    report = recovery.run(trials=200, events_per_trial=12)
    assert abs(report.bias) < 0.05, f"bias {report.bias:+.4f}"
    assert report.rmse < 0.10, f"rmse {report.rmse:.4f}"


def test_the_bias_is_conservative_not_generous():
    """Any residual bias must point DOWN. The prior is deliberately below median,
    so a filter that overshoots would be manufacturing ability from nothing."""
    report = recovery.run(trials=200, events_per_trial=12)
    assert report.bias < 0.01, f"the estimate runs high: {report.bias:+.4f}"


def test_more_evidence_means_less_error():
    """The single most diagnostic property. If error did not fall with evidence,
    the update would be wrong in a way no single-point check would reveal."""
    curve = recovery.convergence(events=(1, 4, 16, 32), trials=120)
    rmses = [r for _, r in curve]
    assert rmses == sorted(rmses, reverse=True), curve
    assert rmses[-1] < rmses[0] / 2, "thirty-two events should more than halve the error"


def test_coverage_is_near_the_nominal_rate():
    """z=1 is a display choice, not a calibration target, but a filter whose
    credible interval covered 20% or 99% of truths would be misreporting
    uncertainty — and uncertainty is what the score is built on."""
    report = recovery.run(trials=300, events_per_trial=12)
    assert 0.45 <= report.coverage <= 0.95, f"coverage {report.coverage:.3f}"


def test_recovery_is_reproducible():
    """Seeded, so a regression shows up as a changed number rather than a flake."""
    a = recovery.run(trials=100, seed=7)
    b = recovery.run(trials=100, seed=7)
    assert a == b


def test_a_different_seed_gives_a_different_but_passing_run():
    for seed in (1, 99, 12345):
        assert recovery.run(trials=150, seed=seed).passed, f"seed {seed}"


def test_a_single_event_does_not_pin_the_estimate():
    """One observation against a wide prior should leave real uncertainty. If it
    did not, one weak event could manufacture a score."""
    one = recovery.run(trials=150, events_per_trial=1)
    many = recovery.run(trials=150, events_per_trial=16)
    assert one.mean_sigma > many.mean_sigma
    assert one.rmse > many.rmse


def test_a_wider_prior_still_recovers():
    """Robustness to the one prior parameter that is a judgement call."""
    wide = default_parameters().replacing(prior__sigma_0=2.0)
    assert recovery.run(trials=150, params=wide).passed


def test_a_different_s0_still_recovers():
    """S0 is the only free scale constant in the observation model. Recovery must
    not depend on its exact value, or the sweep would be meaningless."""
    for s0 in (0.05, 0.30):
        report = recovery.run(trials=150, params=default_parameters().replacing(
            observation__S0=s0))
        assert report.passed, f"S0={s0}: {report.render()}"


def test_the_report_renders_a_verdict():
    text = recovery.run(trials=50).render()
    assert "parameter recovery" in text
    assert text.strip().endswith(("PASS", "FAIL"))
