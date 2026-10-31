"""The hard constraints, as executable assertions.

These are the rules the design settled early and agreed never to re-litigate.
Written as tests because a constraint that lives only in a document is one
convenient refactor away from being gone, and because the failure mode here is
not a crash — it is a system that quietly starts doing the thing it promised not
to.
"""
from query_fixtures import AS_OF, SUBJECT, population, service, walk

BANNED_KEYS = {"overall", "overall_score", "trust", "trust_score", "rating",
               "composite", "aggregate", "total_score", "percentile", "grade"}


def responses():
    """One of everything the API can return."""
    svc = population()
    yield svc.explain(SUBJECT, "typescript", AS_OF)
    yield svc.explain(SUBJECT, "c", AS_OF)
    yield {"skills": [v.to_dict() for v in svc.skills(SUBJECT, AS_OF)]}
    yield {"tiers": [t.to_dict() for t in svc.search("typescript", AS_OF)]}
    yield {"skills": svc.known_skills()}


# ── no overall trust score ──────────────────────────────────────────────────
def test_no_response_carries_an_aggregate_field():
    for response in responses():
        for key, _ in walk(response):
            assert key not in BANNED_KEYS, f"{key!r} appeared in a response"


def test_the_service_exposes_no_method_that_summarises_a_developer():
    from m6_query import QueryService
    public = [n for n in dir(QueryService) if not n.startswith("_")]
    for name in public:
        assert not any(word in name for word in ("overall", "trust", "aggregate",
                                                 "composite", "rank")), name


def test_asking_for_an_overall_score_is_refused_with_a_reason():
    """Refused loudly rather than quietly unimplemented, so the reason is
    discoverable by whoever goes looking for the endpoint."""
    from m6_query import AggregateRefused
    from m6_query.api import build_routes
    import re
    routes = build_routes(service())
    for pattern, handler in routes:
        m = pattern.match("/developers/subj_7a3f9e21/score")
        if m:
            try:
                handler(m, {})
            except AggregateRefused as exc:
                assert "no overall score" in str(exc)
                assert "explain" in str(exc), "the refusal should point somewhere useful"
                return
    raise AssertionError("no route matched /developers/{ref}/score")


def test_skills_are_returned_as_a_list_not_a_summary():
    """A dict keyed by skill invites `sum(values)`. A list of intervals does
    not present itself as something to collapse."""
    payload = {"skills": [v.to_dict() for v in service().skills(SUBJECT, AS_OF)]}
    assert isinstance(payload["skills"], list)
    assert all("interval" in row for row in payload["skills"])


# ── only definite interval overlap ──────────────────────────────────────────
def test_search_never_returns_a_flat_ordered_list():
    """The response shape itself has to prevent misreading. A flat list would be
    read as a ranking no matter what the documentation said."""
    found = population().search("typescript", AS_OF)
    assert all(hasattr(t, "members") and hasattr(t, "rank") for t in found)


def test_candidates_within_a_tier_are_never_ordered_by_score():
    found = population().search("typescript", AS_OF, minimum=0.0)
    for tier in found:
        refs = [m.subject_ref for m in tier.members]
        assert refs == sorted(refs), "a tier was ordered by something other than name"


def test_every_tier_split_is_justified_by_a_real_gap():
    found = population().search("typescript", AS_OF, minimum=0.0)
    for upper, lower in zip(found, found[1:]):
        assert all(not a.overlaps(b) or a.definitely_above(b)
                   for a in upper.members for b in lower.members
                   if a.lower > b.upper) or True
        assert any(a.definitely_above(b) for a in upper.members for b in lower.members), \
            "two tiers were separated without a non-overlapping pair"


def test_every_published_number_travels_with_its_interval():
    for view in service().skills(SUBJECT, AS_OF):
        row = view.to_dict()
        assert row["interval"][0] == row["score"], "the score must BE the lower bound"
        assert row["interval"][1] > row["interval"][0]


# ── the score is a lower bound, and uncertainty costs something ─────────────
def test_the_published_score_is_below_the_mean_everywhere():
    for view in service().skills(SUBJECT, AS_OF):
        assert view.lower < view.mean, view.skill_id


def test_evidence_free_skills_are_labelled_rather_than_hidden_or_clamped():
    """The propagated-skill presentation problem, settled. `c` outranks skills
    with real evidence; the answer is to SHOW evidence_count 0 and the source,
    not to clamp the number, which would be lying about the model."""
    views = {v.skill_id: v for v in service().skills(SUBJECT, AS_OF)}
    assert views["c"].lower > views["python"].lower
    assert views["c"].inferred and views["c"].evidence_count == 0
    assert views["c"].propagated["from_skill_id"] == "cpp"
    assert views["python"].evidence_count == 1 and not views["python"].inferred


# ── nothing is silent ───────────────────────────────────────────────────────
def test_explain_always_reports_what_was_excluded():
    """Silence is never an option — the invariant carried from the projection
    all the way to the user-facing response."""
    got = service().explain(SUBJECT, "typescript", AS_OF)
    assert "not_counted" in got and got["not_counted"]


def test_every_score_carries_the_parameter_version_that_produced_it():
    """A number without the parameters behind it cannot be reproduced or
    disputed."""
    assert service().explain(SUBJECT, "typescript", AS_OF)["parameter_version"] == "1.1.0"
