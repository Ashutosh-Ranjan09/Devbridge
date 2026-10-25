"""The pure decision functions, tested in isolation from any report."""
from helpers import repo  # noqa: F401  (path bootstrap)
from m6_projection.params import default_rules
from m6_projection.rules import (apply_factors, event_id, language_relevances,
                                 normalise_skill, repo_strength, substance_band)

R = default_rules()


def test_substance_band_boundaries():
    """Each threshold is exercised on both sides. Off-by-one here silently
    shifts every repo's strength."""
    cases = [
        (dict(commit_count=9, size_kb=5000), "trivial"),      # just under
        (dict(commit_count=10, size_kb=5000), "small"),       # just over -> size_kb<100 fails, commits<50 holds
        (dict(commit_count=49, size_kb=5000), "small"),
        (dict(commit_count=50, size_kb=99), "small"),         # promoted by commits, held by size
        (dict(commit_count=50, size_kb=100), "substantial"),
        (dict(commit_count=119, size_kb=5000), "substantial"),
        (dict(commit_count=120, size_kb=999), "substantial"),  # commits qualify, size does not
        (dict(commit_count=120, size_kb=1000), "large"),
        (dict(commit_count=142, size_kb=3820), "large"),      # ATMA-Final
        (dict(commit_count=97, size_kb=2140), "substantial"), # cf-connect
        (dict(commit_count=31, size_kb=240), "small"),        # Terminal-Chat-Room
    ]
    for spec, expected in cases:
        got, _ = substance_band(spec, R)
        assert got == expected, f"{spec} -> {got}, expected {expected}"


def test_readme_only_is_trivial_however_large():
    """A shell repository is trivial no matter what the counters say — the whole
    point of the check is that volume can be manufactured."""
    band, index = substance_band(dict(is_readme_only=True, commit_count=9999, size_kb=99999), R)
    assert band == "trivial" and index == 0


def test_unmatched_repo_falls_to_the_neutral_middle_not_the_top():
    band, _ = substance_band(dict(commit_count=500, size_kb=10), R)
    assert band in ("small", "substantial")
    assert band != "large"


def test_repo_strength_tracks_band_index():
    strengths = [repo_strength(substance_band(s, R)[1], R) for s in
                 (dict(commit_count=5, size_kb=5), dict(commit_count=31, size_kb=240),
                  dict(commit_count=97, size_kb=2140), dict(commit_count=142, size_kb=3820))]
    assert strengths == [0.45, 0.50, 0.55, 0.60]
    assert strengths == sorted(strengths), "strength must be monotone in substance"


def test_language_relevance_formula_and_floor():
    langs = {"TypeScript": 184320, "JavaScript": 41200, "CSS": 18400}
    got = language_relevances(langs, R)
    assert "css" not in got, "7.5% share is below the 10% floor and must be dropped"
    assert abs(got["typescript"] - 0.8778) < 5e-4
    assert abs(got["javascript"] - 0.5845) < 5e-4
    assert got["typescript"] > got["javascript"]


def test_language_relevance_is_clamped_at_both_ends():
    only = language_relevances({"Python": 1000}, R)
    assert only["python"] == 0.95, "a 100% share must clamp at max, not reach 1.0"
    assert all(0.50 <= v <= 0.95 for v in
               language_relevances({"A": 60, "B": 40}, R).values())


def test_language_relevance_handles_empty_and_zero():
    assert language_relevances({}, R) == {}
    assert language_relevances({"X": 0}, R) == {}


def test_ownership_cap_is_asymmetric():
    """The rule the whole GitHub story rests on: a self-claimed account may
    lower a score at full strength but may not raise one."""
    up, applied = apply_factors(0.70, "positive", ["ownership_unverified"], R)
    down, none_applied = apply_factors(0.95, "negative", ["ownership_unverified"], R)
    assert up == 0.42 and len(applied) == 1
    assert down == 0.95 and none_applied == (), "a contradiction must not be capped"


def test_inert_factors_are_not_recorded():
    """stale_evidence is declared at 1.0 because decay handles staleness at
    scoring time. Recording it would imply a cap that is not happening."""
    value, applied = apply_factors(0.80, "positive", ["stale_evidence"], R)
    assert value == 0.80 and applied == ()


def test_event_id_is_deterministic_and_discriminating():
    a = event_id("ver_1", "repo_artifact", "ATMA-Final")
    assert a == event_id("ver_1", "repo_artifact", "ATMA-Final")
    assert a != event_id("ver_1", "repo_artifact", "cf-connect")
    assert a != event_id("ver_2", "repo_artifact", "ATMA-Final")
    assert a != event_id("ver_1", "cv_claim", "ATMA-Final")
    assert a.startswith("ev_") and len(a) == 15


def test_alias_normalisation():
    assert normalise_skill("Mongoose", R) == "mongodb"
    assert normalise_skill("next", R) == "nextjs"
    assert normalise_skill("C++", R) == "cpp"
    assert normalise_skill("TypeScript", R) == "typescript"
    assert normalise_skill("some new thing", R) == "some_new_thing"
