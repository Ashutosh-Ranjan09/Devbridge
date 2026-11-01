"""The shortlist: a confirmed job's must-haves as filters, never a ranking."""
from query_fixtures import AS_OF, SUBJECT, population, raises, walk
from m6_query import QueryService, SkillView
from m6_query.errors import BadRequirements
from m6_query.service import job_match
from m6_scoring import ScoringEngine


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


# ── the job match: one applicant against one confirmed job ──────────────────
def view(lower, mean, upper, evidence=1):
    return SkillView(skill_id="", lower=lower, upper=upper, mean=mean, tier="fundamental",
                     evidence_count=evidence, days_since_newest_evidence=None, propagated=None)


PRIOR = view(0.083, 0.25, 0.55, evidence=0)
WEIGHTS = {"must": 2.0, "nice": 1.0}


def test_a_job_match_counts_a_must_have_twice_a_nice_to_have():
    """The worked example: algorithms a must-have at 0.6, data structures a nice-to-have
    at 0.2. Both ends of the range are averaged the same way as the middle."""
    views = {"algorithms": view(0.45, 0.6, 0.73), "data_structures": view(0.08, 0.2, 0.42)}
    got = job_match(views, ["algorithms"], ["data_structures"], WEIGHTS, PRIOR)
    assert got == {"interval": [0.327, 0.627], "mean": 0.467, "evidence_for": 2, "of": 2}


def test_a_skill_without_evidence_counts_at_the_prior_not_at_zero():
    """Absence is not inability: a skill nobody has shown counts at "nothing known"."""
    got = job_match({"algorithms": view(0.45, 0.6, 0.73)}, ["algorithms"], ["data_structures"], WEIGHTS, PRIOR)
    assert got["mean"] == round((2 * 0.6 + 0.25) / 3, 3)
    assert got["interval"][0] > round(2 * 0.45 / 3, 3), "the missing skill counted as zero"
    assert (got["evidence_for"], got["of"]) == (1, 2), "the match must say it rests on one skill"


def test_no_weighted_skill_is_no_match():
    assert job_match({}, [], ["rust"], {"must": 2.0, "nice": 0.0}, PRIOR) is None


def test_the_shortlist_s_nothing_known_is_m6_s_prior():
    found = population().shortlist(requirements([("typescript", 0.0)], nice=["rust"]), AS_OF, subjects=[SUBJECT])
    assert found["job_match_basis"] == {"weights": WEIGHTS, "left_out": [],
                                        "without_evidence": {"interval": [0.083, 0.55], "mean": 0.25}}
    entry = found["candidates"][0]
    assert entry["nice"]["rust"] is None
    assert (entry["job_match"]["evidence_for"], entry["job_match"]["of"]) == (1, 2)


def test_an_inferred_skill_counts_at_its_range_but_not_as_evidence():
    """On the golden subject data_structures is reached only by propagation."""
    svc = population()
    views = {v.skill_id: v for v in svc.skills(SUBJECT, AS_OF)}
    a, d = views["algorithms"], views["data_structures"]
    assert d.inferred and not a.inferred
    found = svc.shortlist(requirements([("algorithms", 0.0)], nice=["data_structures"]), AS_OF, subjects=[SUBJECT])
    got = found["candidates"][0]["job_match"]
    assert got["mean"] == round((2 * a.mean + d.mean) / 3, 3)
    assert got["interval"] == [round((2 * a.lower + d.lower) / 3, 3), round((2 * a.upper + d.upper) / 3, 3)]
    assert (got["evidence_for"], got["of"]) == (1, 2)


def test_the_weights_are_the_parameters_not_the_code():
    svc = population()
    p = svc.engine.p.replacing(job_match__weights__nice=0.0)
    musts_only = QueryService(svc.log, ScoringEngine(p, ontology=svc.ontology), ontology=svc.ontology)
    doc = requirements([("typescript", 0.0)], nice=["rust"])
    weighted = svc.shortlist(doc, AS_OF, subjects=[SUBJECT])["candidates"][0]["job_match"]
    unweighted = musts_only.shortlist(doc, AS_OF, subjects=[SUBJECT])["candidates"][0]["job_match"]
    typescript = {v.skill_id: v for v in svc.skills(SUBJECT, AS_OF)}["typescript"]
    assert unweighted["mean"] == round(typescript.mean, 3) and unweighted["of"] == 1
    assert weighted["mean"] != unweighted["mean"]


def test_the_match_moves_nobody_and_orders_nobody():
    """The bars alone decide who qualifies, and both lists stay alphabetical whatever
    the matches are."""
    doc = requirements([("typescript", 0.3)], nice=["cpp", "python"])
    asked = ["subj_weak", "subj_strong", "subj_thin", SUBJECT]
    found = population().shortlist(doc, AS_OF, subjects=asked)
    for group, qualifies in (("candidates", True), ("others", False)):
        assert [c["subject_ref"] for c in found[group]] == sorted(c["subject_ref"] for c in found[group])
        assert all((False not in c["clears"].values()) == qualifies for c in found[group])
    everyone = found["candidates"] + found["others"]
    means = [c["job_match"]["mean"] for c in everyone]
    assert len(set(means)) > 1, "the fixture must give different matches, or this proves nothing"
    assert means != sorted(means, reverse=True), "an alphabetical list that happens to be in match order proves nothing"


def test_each_skill_counts_once_and_a_must_have_wins_over_a_nice_to_have():
    """A requirements file the assessment module never writes, but M6 must not double-count."""
    views = {"algorithms": view(0.45, 0.6, 0.73), "data_structures": view(0.08, 0.2, 0.42)}
    once = job_match(views, ["algorithms"], ["data_structures"], WEIGHTS, PRIOR)
    assert job_match(views, ["algorithms", "algorithms"], ["data_structures", "data_structures", "algorithms"],
                     WEIGHTS, PRIOR) == once
    both = population().shortlist(requirements([("algorithms", 0.0)], nice=["algorithms"]), AS_OF, subjects=[SUBJECT])
    alone = population().shortlist(requirements([("algorithms", 0.0)]), AS_OF, subjects=[SUBJECT])
    assert both["candidates"][0]["job_match"] == alone["candidates"][0]["job_match"]
    assert both["candidates"][0]["job_match"]["of"] == 1


def test_a_skill_the_list_lacks_is_left_out_of_every_match_and_named():
    """Counted at the prior it would drag every applicant's match down alike."""
    svc = population()
    asked = ["subj_strong", "subj_thin", SUBJECT]
    with_cobol = svc.shortlist(requirements([("algorithms", 0.0), ("cobol", None)], nice=["fortran"]), AS_OF, subjects=asked)
    without = svc.shortlist(requirements([("algorithms", 0.0)]), AS_OF, subjects=asked)
    matches = lambda found: {e["subject_ref"]: e["job_match"] for e in found["candidates"] + found["others"]}
    assert matches(with_cobol) == matches(without)
    assert with_cobol["job_match_basis"]["left_out"] == ["cobol", "fortran"] == with_cobol["unknown_skills"]
