"""Pins the projection of report-full.json to the table published in
docs/docs/m6-worked-trace.html §02, and carries it through the scoring model to
the skill graph in §06. If either changes, one of the documents is now wrong."""
import math
import pathlib
import sys
from datetime import date

from helpers import ROOT, by_kind, full, skills
from m6_projection import project

sys.path.insert(0, str(ROOT / "contracts" / "reference"))
import m6_model as M  # noqa: E402

# kind, occurred_at, strength, reliability, {skill: relevance}
EXPECTED = [
    ("repo_artifact", "2024-06-28", 0.50, 0.42, {"python": 0.95}),
    ("platform_rating", "2025-01-14", 0.80, 0.90,
     {"algorithms": 0.95, "problem_solving": 0.90, "cpp": 0.70}),
    ("repo_artifact", "2025-04-27", 0.60, 0.42,
     {"typescript": 0.8778, "javascript": 0.5845, "nextjs": 0.80, "react": 0.80, "mongodb": 0.60}),
    ("claim_corroborated", "2025-06-19", 0.70, 0.48, {"typescript": 1.00}),
    ("repo_artifact", "2025-06-19", 0.55, 0.42,
     {"typescript": 0.95, "nextjs": 0.80, "react": 0.80}),
    # Dated at document.created_at, not at valid_as_of: the CV was written on
    # 2025-07-04 and verified on 2026-08-24, so these carry 13.7 months of decay.
    # 0.20 × 0.7 (aggregate_across_sources) × 0.85 (open_bound): "500+ across
    # three platforms" with only Codeforces verified. The confirmed 412 rides in
    # the payload and on the platform_rating event, so it is not counted twice.
    ("cv_claim", "2025-07-04", 0.30, 0.119, {"problem_solving": 1.00}),
    ("cv_claim", "2025-07-04", 0.30, 0.20, {"cpp": 1.00}),
    ("artifact_live", "2026-08-24", 0.40, 0.51, {"deployment": 0.70, "nextjs": 0.60}),
]


def test_golden_batch_matches_the_published_trace():
    events = project(full(), module_version="0.4.1").events
    assert len(events) == len(EXPECTED), f"{len(events)} events, expected {len(EXPECTED)}"
    for got, (kind, when, strength, reliability, expected_skills) in zip(events, EXPECTED):
        label = f"{got.event_id} {kind} {when}"
        assert got.kind == kind, label
        assert str(got.occurred_at)[:10] == when, label
        assert abs(got.strength - strength) < 1e-9, f"{label}: strength {got.strength}"
        assert abs(got.reliability - reliability) < 1e-9, f"{label}: reliability {got.reliability}"
        got_skills = skills(got)
        assert set(got_skills) == set(expected_skills), f"{label}: {set(got_skills)}"
        for name, value in expected_skills.items():
            assert abs(got_skills[name] - value) < 5e-4, f"{label}: {name}={got_skills[name]}"


def test_golden_suppression_count():
    batch = project(full())
    assert len(batch.not_emitted) == 4
    assert {s.reason for s in batch.not_emitted} == {
        "not_a_capability_signal", "no_skill_mapping",
        "institution_disclaimed", "non_scoring_rule"}


# ── end to end: projection → scoring model → the published skill graph ───────

TIER = {"algorithms": "fundamental", "problem_solving": "fundamental", "cpp": "fundamental",
        "typescript": "ecosystem", "javascript": "ecosystem", "python": "ecosystem",
        "nextjs": "framework", "react": "framework", "mongodb": "framework",
        "deployment": "framework"}
# m6-parameters.yaml → observed_value, applied by the scoring engine (not the projection)
OBSERVED = {"platform_rating": 0.74, "claim_corroborated": 0.68, "artifact_live": 0.58,
            "repo_artifact": {"small": 0.50, "substantial": 0.62, "large": 0.66},
            "cv_claim": {"proficient": 0.60, "expert": 0.75, None: 0.45}}
# The published trace's §06 graph. cpp now folds to 0.507 rather than 0.514,
# because its CV claim is dated at the document instead of at verification —
# within the 0.01 tolerance below, so the published figures still stand.
PUBLISHED = {"algorithms": 0.533, "cpp": 0.514, "typescript": 0.381,
             "nextjs": 0.316, "python": 0.189, "mongodb": 0.173}


def _observed(event) -> float:
    if event.kind == "repo_artifact":
        return OBSERVED["repo_artifact"][event.payload["substance_band"]]
    if event.kind == "cv_claim":
        return OBSERVED["cv_claim"][event.payload.get("proficiency")]
    return OBSERVED[event.kind]


def test_projection_feeds_the_model_and_reproduces_the_published_graph():
    """The two modules only meet here. A change in either that breaks the other
    should fail loudly rather than at integration time."""
    events = [{"event_id": e.event_id, "occurred_at": date.fromisoformat(str(e.occurred_at)[:10]),
               "strength": e.strength, "reliability": e.reliability, "observed": _observed(e),
               "skill_refs": [{"skill_id": r.skill_id, "relevance": r.relevance}
                              for r in e.skill_refs]}
              for e in project(full(), module_version="0.4.1").events]
    as_of = date(2026, 8, 24)
    for skill, published in PUBLISHED.items():
        state = M.fold(events, skill, TIER[skill], as_of)
        assert abs(state.score() - published) < 0.01, \
            f"{skill}: model gives {state.score():.3f}, trace published {published}"


def test_scores_are_ordered_as_published():
    events = [{"event_id": e.event_id, "occurred_at": date.fromisoformat(str(e.occurred_at)[:10]),
               "strength": e.strength, "reliability": e.reliability, "observed": _observed(e),
               "skill_refs": [{"skill_id": r.skill_id, "relevance": r.relevance}
                              for r in e.skill_refs]}
              for e in project(full()).events]
    as_of = date(2026, 8, 24)
    scores = {s: M.fold(events, s, TIER[s], as_of).score() for s in PUBLISHED}
    assert list(sorted(scores, key=scores.get, reverse=True)) == \
        list(sorted(PUBLISHED, key=PUBLISHED.get, reverse=True))


def test_stale_evidence_widens_the_band_more_than_it_lowers_the_mean():
    """Python's only evidence is 787 days old. The decay story is that we know
    less, not that the candidate got worse — so most of the loss must be σ."""
    events = [{"event_id": e.event_id, "occurred_at": date.fromisoformat(str(e.occurred_at)[:10]),
               "strength": e.strength, "reliability": e.reliability, "observed": _observed(e),
               "skill_refs": [{"skill_id": r.skill_id, "relevance": r.relevance}
                              for r in e.skill_refs]}
              for e in project(full()).events]
    fresh = M.fold(events, "python", "ecosystem", date(2024, 6, 28))
    stale = M.fold(events, "python", "ecosystem", date(2026, 8, 24))
    assert math.sqrt(stale.var) > math.sqrt(fresh.var), "uncertainty must grow"
    assert stale.score() < fresh.score()
    lost_to_variance = (math.sqrt(stale.var) - math.sqrt(fresh.var))
    assert lost_to_variance > abs(stale.mean - fresh.mean), \
        "most of the fall should be uncertainty, not a downgraded estimate"
