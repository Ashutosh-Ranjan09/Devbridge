"""Malformed input must fail loudly. A silently-skipped claim is
indistinguishable from a claim that produced no evidence."""
from helpers import full, with_github
from m6_projection import MalformedReport, project
from m6_projection.params import Rules


def _expect(exc_type, fn, *, contains: str = ""):
    try:
        fn()
    except exc_type as exc:
        assert contains in str(exc), f"expected {contains!r} in {exc!r}"
        return
    raise AssertionError(f"expected {exc_type.__name__}, nothing raised")


def test_missing_top_level_block_is_reported_not_guessed():
    for key in ("verification_id", "subject", "evidence_bundle"):
        report = full()
        del report[key]
        _expect(MalformedReport, lambda r=report: project(r), contains=key)


def test_unparseable_date_is_reported():
    report = with_github(full(), repos=[{
        "name": "r", "exists": True, "is_fork": False, "owner_matches": True,
        "is_readme_only": False, "commit_count": 60, "size_kb": 500,
        "last_commit": None, "languages": {"Python": 10000}}])
    _expect(MalformedReport, lambda: project(report), contains="date")


def test_a_repo_with_no_resolvable_skill_is_quarantined_not_dropped():
    """An event with no skill_refs would fail schema minItems:1. Rather than
    emit it or silently discard it, the caller is told."""
    report = with_github(full(), repos=[{
        "name": "empty-repo", "exists": True, "is_fork": False, "owner_matches": True,
        "is_readme_only": False, "commit_count": 60, "size_kb": 500,
        "last_commit": "2025-06-01", "languages": {}, "frameworks": []}])
    batch = project(report)
    assert not any(e.payload.get("repo") == "empty-repo" for e in batch.events)
    assert any("empty-repo" in q for q in batch.quarantined)


def test_rules_can_be_swapped_without_touching_code():
    """The sweep changes YAML, never Python. If this stops working the
    parameters are no longer reachable from outside."""
    import copy
    import yaml
    raw = copy.deepcopy(Rules.load()._raw)  # noqa: SLF001 - deliberate, this is the point
    raw["thresholds"]["language_relevance"]["min_bytes_share"] = 0.01
    loosened = Rules(raw)
    tight = {r.skill_id for e in project(full()).events for r in e.skill_refs}
    loose = {r.skill_id for e in project(full(), rules=loosened).events for r in e.skill_refs}
    assert "css" in loose and "css" not in tight
    assert yaml is not None


def test_module_version_is_carried_onto_every_event():
    """Provenance: a report explained months later needs to know which build
    produced its evidence."""
    for e in project(full(), module_version="9.9.9").events:
        assert e.source.module_version == "9.9.9"
        assert e.source.verification_id == "ver_01J9XQ7K2M4N"
