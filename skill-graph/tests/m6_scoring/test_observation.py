"""The observation model — the boundary the projection deliberately left open.

Two quantities, and keeping them apart is the design: `observed` is what the
evidence says the ability IS, `variance` is how much to believe it. Relevance is
epistemic and belongs only in the variance.
"""
from published_trace import published_trace
from scoring_fixtures import engine, event, raises
from m6_scoring import ObservationModel, UnscoreableEvent, interpolate


def model() -> ObservationModel:
    return engine().observation


# ── observed value, one method at a time ────────────────────────────────────
def test_flat_constants_come_from_the_contract():
    for kind, expected in (("claim_corroborated", 0.68), ("artifact_live", 0.58),
                           ("credential_verified", 0.70), ("claim_contradicted", 0.15)):
        assert model().observed(event(kind)) == expected, kind


def test_substance_bands_are_ordered_and_match_the_contract():
    got = [model().observed(event("repo_artifact", substance_band=b))
           for b in ("trivial", "small", "substantial", "large")]
    assert got == [0.35, 0.50, 0.62, 0.66]
    assert got == sorted(got), "a bigger repository must not observe lower"


def test_an_unknown_substance_band_is_refused_not_defaulted():
    """The projection and the parameters disagreeing is a contract bug. Guessing
    a value would hide it behind a plausible-looking score."""
    exc = raises(UnscoreableEvent, model().observed,
                 event("repo_artifact", substance_band="enormous"))
    assert "enormous" in str(exc)


def test_proficiency_bands_come_from_the_claim_enum():
    for band, expected in (("familiar", 0.30), ("intermediate", 0.45),
                           ("proficient", 0.60), ("expert", 0.75)):
        assert model().observed(event("cv_claim", proficiency=band)) == expected


def test_a_missing_proficiency_takes_the_declared_default():
    """An unstated band is not a low band. Low RELIABILITY, not a low observed
    value, is what keeps an uncorroborated claim from moving a score."""
    assert model().observed(event("cv_claim")) == 0.45
    assert model().observed(event("cv_claim", proficiency="wizard")) == 0.45


def test_platform_rating_reproduces_the_contracts_worked_example():
    """reference-distributions.yaml's measured worked example: a 1495 peak
    interpolates to ECDF 0.834 and observes 0.834 (0.50 + 0.40 x 0.834)."""
    got = model().observed(event("platform_rating", max_rating=1495))
    assert abs(got - 0.8336) < 0.001, got


def test_the_published_trace_used_the_approximated_table():
    """The trace quotes 1495 -> ECDF ~0.60 -> 0.74; under the frozen table it still does."""
    with published_trace():
        got = engine().observation.observed(event("platform_rating", max_rating=1495))
    assert abs(got - 0.74) < 0.005, got


def test_platform_rating_is_monotone_in_rating():
    got = [model().observed(event("platform_rating", max_rating=r))
           for r in (800, 1200, 1495, 1900, 2400, 3000)]
    assert got == sorted(got)
    assert got[0] >= 0.50, "being rated at all clears the general-population floor"


def test_platform_rating_without_a_rating_is_refused():
    raises(UnscoreableEvent, model().observed, event("platform_rating"))


def test_an_unknown_kind_is_refused_with_a_useful_message():
    exc = raises(UnscoreableEvent, model().observed, event("telepathy"))
    assert "m6-parameters.yaml" in str(exc), "the message must say where to fix it"


def test_observed_values_stay_inside_the_open_interval():
    """logit is undefined at 0 and 1, and no single event earns certainty."""
    for kind in ("claim_contradicted", "credential_verified"):
        assert 0.0 < model().observed(event(kind)) < 1.0


# ── the ECDF lookup ─────────────────────────────────────────────────────────
def test_interpolation_is_linear_between_anchors():
    anchors = {0: 0.0, 10: 1.0}
    assert interpolate(anchors, 5) == 0.5
    assert interpolate(anchors, 2.5) == 0.25


def test_a_rating_is_priced_on_its_own_platforms_table():
    """Ratings on different platforms are different units. With one table for all,
    a CodeChef 1810 was priced as a Codeforces 1810."""
    cf = model().observed(event("platform_rating", max_rating=1495, platform="codeforces"))
    unnamed = model().observed(event("platform_rating", max_rating=1495))
    assert cf == unnamed, "an event that names no platform is the Codeforces example"


def test_a_platform_with_no_reference_distribution_is_refused_not_guessed():
    exc = raises(UnscoreableEvent, model().observed,
                 event("platform_rating", max_rating=1810, platform="codechef"))
    assert "codechef" in str(exc) and "rating_reference" in str(exc)


def test_every_platform_the_projection_rates_has_a_table():
    """6.0 sends platform_rating only for rating_reference.platforms; 6.3 prices it
    from `<platform>_rated_ecdf`. The two files are edited separately, so this is
    what keeps a platform from being projected as a rating nobody can price."""
    from m6_projection.params import default_rules
    p = engine().p
    for platform in default_rules().rated_platforms:
        assert p.ecdf_anchors_for(platform), f"{platform} has no reference distribution"


def test_interpolation_clamps_outside_the_table():
    anchors = {100: 0.2, 200: 0.8}
    assert interpolate(anchors, 0) == 0.2
    assert interpolate(anchors, 9999) == 0.8


def test_interpolation_hits_anchors_exactly():
    anchors = engine().p.ecdf_anchors
    for rating, value in anchors.items():
        assert abs(interpolate(anchors, rating) - value) < 1e-12


# ── observation variance ────────────────────────────────────────────────────
def test_variance_is_the_contract_formula():
    """S0 / (reliability x relevance x strength)."""
    p = engine().p
    e = event(reliability=0.5, relevance=0.5, strength=0.5)
    assert abs(model().variance(e, "python") - p.s0 / 0.125) < 1e-9


def test_stronger_evidence_has_lower_variance():
    weak = model().variance(event(reliability=0.2, relevance=0.3, strength=0.3), "python")
    strong = model().variance(event(reliability=0.9, relevance=1.0, strength=0.8), "python")
    assert strong < weak


def test_relevance_lowers_confidence_not_the_observed_value():
    """The central claim of O1/O3. A repository that is 60% TypeScript is not
    evidence of worse ability; it is weaker evidence about that ability."""
    partly = event("repo_artifact", relevance=0.6, substance_band="substantial")
    fully = event("repo_artifact", relevance=1.0, substance_band="substantial")
    assert model().observed(partly) == model().observed(fully)
    assert model().variance(partly, "python") > model().variance(fully, "python")


def test_zero_relevance_does_not_divide_by_zero():
    assert model().variance(event(relevance=0.0), "python") > 0


def test_asking_for_a_skill_the_event_does_not_name_is_refused():
    raises(UnscoreableEvent, model().variance, event(skill="python"), "rust")


def test_measure_returns_both_at_once():
    observed, variance = model().measure(
        event("repo_artifact", substance_band="large"), "python")
    assert observed == 0.66 and variance > 0


def test_negative_direction_is_reported_not_applied_here():
    """Direction is the filter's business; the observation model only reads it."""
    assert model().is_negative(event("claim_contradicted", direction="negative"))
    assert not model().is_negative(event("repo_artifact", substance_band="small"))


def test_interpolation_survives_a_duplicated_anchor():
    """A regenerated ECDF could contain a flat run. Zero width must not divide."""
    assert interpolate({100: 0.5, 100.0: 0.5, 200: 0.9}, 100) == 0.5


def test_a_kind_declaring_no_usable_method_is_refused():
    """A contract entry that names no method is a contract bug, not a licence to
    invent a number."""
    eng = engine()
    broken = eng.p.replacing()
    broken._raw["observed_value"]["repo_artifact"] = {"rationale": "no method here"}
    exc = raises(UnscoreableEvent, ObservationModel(broken).observed,
                 event("repo_artifact", substance_band="small"))
    assert "no usable method" in str(exc)


def test_an_assessment_is_priced_by_level_and_share_passed():
    """floor + (ceiling[level] - floor) * passed / total, from the parameter file."""
    m = model()
    full = m.observed(event("assessment_result", level="medium", passed=6, total=6))
    none = m.observed(event("assessment_result", level="medium", passed=0, total=6))
    half = m.observed(event("assessment_result", level="medium", passed=3, total=6))
    assert abs(full - 0.86) < 1e-9 and abs(none - 0.20) < 1e-9
    assert abs(half - (0.20 + 0.66 / 2)) < 1e-9
    hard = m.observed(event("assessment_result", level="hard", passed=6, total=6))
    assert hard > full, "a harder task fully passed is stronger evidence"


def test_a_fully_passed_task_beats_a_rating_in_its_band():
    """The skill measured directly outranks the proxy: easy above any Pupil peak
    (1200-1399), medium above any Specialist (1400-1599), hard above every rating.
    Pins the relation, so a new rating table or ceiling cannot quietly reverse it."""
    m = model()
    rating = lambda r: m.observed(event("platform_rating", max_rating=r))
    task = lambda level: m.observed(event("assessment_result", level=level, passed=5, total=5))
    assert task("easy") > rating(1399)
    assert task("medium") > rating(1599)
    assert task("hard") > rating(4000)


def test_an_assessment_without_its_facts_is_refused_not_guessed():
    for payload in ({"level": "medium", "passed": 7, "total": 6}, {"level": "expert", "passed": 1, "total": 2},
                    {"level": "medium", "passed": 1, "total": 0}, {}):
        raises(UnscoreableEvent, model().observed, event("assessment_result", **payload))
