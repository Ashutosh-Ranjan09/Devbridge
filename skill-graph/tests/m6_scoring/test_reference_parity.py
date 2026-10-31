"""The engine must reproduce contracts/reference/m6_model.py exactly.

That file is the executable specification — dependency-free, hard-coded, ~120
lines. This package is the service: same mathematics, every constant read from
m6-parameters.yaml instead. If the two ever disagree, one of them is a bug, and
this is where that shows up rather than in a published number.
"""
from published_trace import published_trace
from datetime import date, timedelta

import m6_model as M
from scoring_fixtures import AS_OF, PUBLISHED, engine, events
from m6_scoring import Filter, State, logit
from m6_scoring.params import default_parameters

TIER = {"algorithms": "fundamental", "problem_solving": "fundamental", "cpp": "fundamental",
        "typescript": "ecosystem", "javascript": "ecosystem", "python": "ecosystem",
        "nextjs": "framework", "react": "framework", "mongodb": "framework",
        "deployment": "framework"}


def test_the_reference_constants_match_the_contract():
    """The reference hard-codes them; the contract owns them. Drift here means
    the specification and the parameters have quietly parted company."""
    p = default_parameters()
    assert (M.THETA_0, M.SIGMA_0, M.S0, M.Z, M.K_H) == (p.theta_0, p.sigma_0, p.s0,
                                                        p.z, p.k_h)
    assert M.LAMBDA == p.lambda_per_day
    assert M.GAMMA == p.gamma
    assert M.DEFAULT_TIER == p.default_tier


def test_the_prior_matches():
    day = date(2025, 1, 1)
    mine = Filter(default_parameters()).initial(day)
    theirs = M.initial(day)
    assert abs(mine.mu - theirs.mu) < 1e-12 and abs(mine.var - theirs.var) < 1e-12


def test_the_update_matches():
    f = Filter(default_parameters())
    day = date(2025, 1, 1)
    for observed, obs_var in ((0.74, 0.3), (0.2, 1.5), (0.95, 0.05)):
        mine = f.updated(f.initial(day), observed, obs_var)
        theirs = M.initial(day).updated(observed, obs_var)
        assert abs(mine.mu - theirs.mu) < 1e-12
        assert abs(mine.var - theirs.var) < 1e-12


def test_the_decay_kernel_matches():
    f = Filter(default_parameters())
    day = date(2025, 1, 1)
    for tier in ("fundamental", "ecosystem", "framework"):
        for days in (1, 100, 787, 3000):
            mine = f.decayed_to(State(logit(0.8), 0.05, day), day + timedelta(days=days), tier)
            theirs = M.State(logit(0.8), 0.05, day).decayed_to(day + timedelta(days=days), tier)
            assert abs(mine.mu - theirs.mu) < 1e-12, (tier, days)
            assert abs(mine.var - theirs.var) < 1e-12, (tier, days)


def test_the_observation_variance_matches():
    om = engine().observation
    for reliability, relevance, strength in ((0.9, 0.95, 0.8), (0.2, 0.5, 0.3),
                                             (0.42, 0.8778, 0.6)):
        mine = om.variance({"reliability": reliability, "strength": strength,
                            "skill_refs": [{"skill_id": "s", "relevance": relevance}]}, "s")
        assert abs(mine - M.observation_variance(reliability, relevance, strength)) < 1e-12


def test_the_fold_matches_on_the_real_events():
    """The engine derives `observed` from the contract; the reference is handed
    it. Same events, same numbers."""
    eng = engine()
    evs = events()
    reference_events = [
        {"event_id": e["event_id"],
         "occurred_at": date.fromisoformat(e["occurred_at"][:10]),
         "strength": e["strength"], "reliability": e["reliability"],
         "observed": eng.observation.observed(e), "skill_refs": e["skill_refs"]}
        for e in evs]
    for skill, tier in TIER.items():
        mine = eng.fold(evs, skill, AS_OF, tier=tier)
        theirs = M.fold(reference_events, skill, tier, AS_OF)
        assert abs(mine.state.mu - theirs.mu) < 1e-9, skill
        assert abs(mine.state.var - theirs.var) < 1e-9, skill


def test_the_explain_shape_matches_the_reference():
    eng = engine()
    st = eng.fold(events(), "typescript", AS_OF, tier="ecosystem")
    mine = eng.explain(st, AS_OF)
    theirs = M.explain(M.State(st.state.mu, st.state.var, AS_OF), "typescript")
    for field in ("skill", "score", "mean", "sigma", "sigma_logit"):
        assert mine[field] == theirs[field], field


def test_the_whole_graph_reproduces_the_published_trace():
    # The published trace was computed with the approximated Codeforces table; see
    # contracts/reference/published_trace.py.
    with published_trace():
        eng = engine()
        evs = events()
        for skill, published in PUBLISHED.items():
            got = eng.fold(evs, skill, AS_OF).state.score(eng.p.z)
            assert abs(got - published) < 0.01, f"{skill}: engine {got:.3f}, published {published}"


def test_the_published_ordering_is_preserved():
    """The ordering is the contract — the scores themselves are calibrated
    guesses, but which skill outranks which is what the product asserts."""
    eng = engine()
    evs = events()
    got = {s: eng.fold(evs, s, AS_OF).state.score(eng.p.z) for s in PUBLISHED}
    assert sorted(got, key=got.get, reverse=True) == \
        sorted(PUBLISHED, key=PUBLISHED.get, reverse=True)


def test_propagation_matches_the_reference():
    eng = engine()
    evs = events()
    direct_mine = eng.fold_all(evs, AS_OF)
    edges = [("cpp", "c", "RELATED_TO")]

    from m6_scoring import Propagator
    mine = Propagator(eng).propagate(direct_mine, edges, AS_OF)["c"]

    direct_ref = {k: M.State(v.state.mu, v.state.var, v.state.at)
                  for k, v in direct_mine.items()}
    theirs = M.propagate(direct_ref, edges, TIER, AS_OF)["c"]
    assert abs(mine.state.mu - theirs.mu) < 1e-9
    assert abs(mine.state.var - theirs.var) < 1e-9
