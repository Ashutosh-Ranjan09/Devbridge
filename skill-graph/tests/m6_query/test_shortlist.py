"""The shortlist: a confirmed job's must-haves as filters, never a ranking."""
from query_fixtures import AS_OF, population, raises, walk
from m6_query.errors import BadRequirements


def requirements(must, nice=(), not_on_list=()):
    return {"schema_version": "1.0.0", "job_id": "job_t", "confirmed_at": "2026-08-24T00:00:00+00:00",
            "confirmed_by": "recruiter", "skill_list_version": "0.3.0",
            "must": [{"skill_id": s, "bar": b} for s, b in must],
            "nice": list(nice), "not_on_list": list(not_on_list)}


def test_every_must_have_must_clear_its_bar():
    svc = population()
    everyone = svc.shortlist(requirements([("typescript", 0.0)]), AS_OF)
    assert everyone["qualified"] >= 2
    strict = svc.shortlist(requirements([("typescript", 0.0), ("cpp", 0.99)]), AS_OF)
    assert strict["qualified"] == 0, "nobody's interval clears 0.99"


def test_a_must_have_needs_direct_evidence_not_an_inferred_interval():
    """`c` reaches the golden subject only by propagation from cpp — a hint, not a
    demonstration, so it qualifies nobody."""
    svc = population()
    found = svc.shortlist(requirements([("c", 0.0)]), AS_OF)
    assert found["qualified"] == 0


def test_nice_to_haves_are_shown_and_filter_nobody():
    svc = population()
    without = svc.shortlist(requirements([("typescript", 0.0)]), AS_OF)
    with_nice = svc.shortlist(requirements([("typescript", 0.0)], nice=["rust", "cpp"]), AS_OF)
    assert with_nice["qualified"] == without["qualified"]
    first = with_nice["candidates"][0]
    assert set(first["nice"]) == {"rust", "cpp"}


def test_alphabetical_never_ranked():
    """Ordering by skills would need a weighted sum — an overall score by another name."""
    found = population().shortlist(requirements([("typescript", 0.0)]), AS_OF)
    refs = [c["subject_ref"] for c in found["candidates"]]
    assert refs == sorted(refs)
    assert "not ranked" in found["note"]
    for key, _value in walk(found):
        assert key not in {"score", "overall", "rank", "total"}, f"aggregate-shaped key {key!r}"


def test_reaching_is_looser_than_clearing():
    svc = population()
    clear = svc.shortlist(requirements([("typescript", 0.5)]), AS_OF)
    reach = svc.shortlist(requirements([("typescript", 0.5)]), AS_OF, definite=False)
    assert reach["qualified"] >= clear["qualified"]


def test_unknown_and_unlisted_skills_are_reported_not_dropped():
    found = population().shortlist(
        requirements([("typescript", 0.0), ("cobol", 0.1)], not_on_list=["Kafka"]), AS_OF)
    assert found["unknown_skills"] == ["cobol"] and found["qualified"] == 0
    assert found["not_on_list"] == ["Kafka"]


def test_requirements_are_checked_against_the_shared_schema():
    exc = raises(BadRequirements, population().shortlist, {"job_id": "x"}, AS_OF)
    assert "schema_version" in str(exc)
    bad = requirements([("typescript", 1.5)])
    assert "must/0/bar" in str(raises(BadRequirements, population().shortlist, bad, AS_OF))


def test_a_must_have_without_a_bar_is_shown_and_filters_nobody():
    """Required, but to be assessed: nobody has evidence for it before the test."""
    svc = population()
    base = svc.shortlist(requirements([("typescript", 0.0)]), AS_OF)
    doc = requirements([("typescript", 0.0)])
    doc["must"].append({"skill_id": "rate_limiting", "bar": None})
    found = svc.shortlist(doc, AS_OF)
    assert found["qualified"] == base["qualified"]
    assert found["candidates"][0]["must"]["rate_limiting"] is None
    assert [m["filters"] for m in found["must"]] == [True, False]


def test_with_nothing_to_filter_on_everyone_is_listed_and_told_why():
    """Every must-have is to be assessed: the shortlist is the whole pool, said plainly."""
    doc = requirements([])
    doc["must"].append({"skill_id": "rate_limiting", "bar": None})
    found = population().shortlist(doc, AS_OF)
    assert found["qualified"] == found["considered"] > 0
    assert "nothing filtered" in found["note"]


def test_applicants_are_each_answered_for_qualified_or_not():
    """A job's applicants: everyone asked about appears once, in `candidates` or
    `others`, so a reader sees why someone did not qualify, not only that they are gone."""
    asked = ["subj_weak", "subj_strong", "subj_thin"]
    found = population().shortlist(requirements([("typescript", 0.0), ("cpp", 0.99)]), AS_OF, subjects=asked)
    listed = [c["subject_ref"] for c in found["candidates"]] + [c["subject_ref"] for c in found["others"]]
    assert sorted(listed) == sorted(asked) and found["considered"] == 3
    assert found["qualified"] == 0, "nobody's interval clears 0.99"
    assert [c["subject_ref"] for c in found["others"]] == sorted(asked), "alphabetical, never ranked"


def test_clears_is_the_filter_s_own_decision_per_must_have():
    doc = requirements([("typescript", 0.0), ("cpp", 0.99)])
    doc["must"].append({"skill_id": "rate_limiting", "bar": None})
    found = population().shortlist(doc, AS_OF, subjects=["subj_strong"])
    assert found["others"][0]["clears"] == {"typescript": True, "cpp": False, "rate_limiting": None}
    passed = population().shortlist(requirements([("typescript", 0.0)]), AS_OF, subjects=["subj_strong"])
    assert passed["candidates"][0]["clears"] == {"typescript": True}


def test_an_applicant_with_no_evidence_is_said_not_dropped():
    """No evidence is not a low score, and must not read as one: it has its own list."""
    found = population().shortlist(requirements([("typescript", 0.0)]), AS_OF,
                                   subjects=["subj_strong", "subj_nobody"])
    assert found["no_evidence"] == ["subj_nobody"]
    assert "subj_nobody" not in [c["subject_ref"] for c in found["candidates"] + found["others"]]


def test_without_subjects_the_near_misses_of_everyone_are_not_listed():
    """Asked about the whole population, the answer is who qualifies, as before."""
    found = population().shortlist(requirements([("typescript", 0.0), ("cpp", 0.99)]), AS_OF)
    assert "others" not in found and "no_evidence" not in found
    assert found["considered"] == 4
