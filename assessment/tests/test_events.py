"""A result as evidence for M6: schema-valid, facts only, and only when something was measured."""

from __future__ import annotations

import datetime

import pytest

from assess.events import NotEvidenceError, batch
from assess.models import Outcome, SandboxInfo, Session
from assess.patterns import load
from assess.sandbox import Run
from assess.scoring import build_result
from assess.variants import generate
from tests.test_sandbox import rows

NOW = datetime.datetime(2026, 10, 26, 12, 0, tzinfo=datetime.UTC)


def result(outcome=Outcome.TESTS_FAILED, failed=frozenset({"exact_boundary"})):
    p = load("rate_limiter")
    v = generate(p, 1)
    s = Session(session_id="as_ev", variant_id=v.variant_id, candidate_ref="subject:asha",
                started_at=NOW - datetime.timedelta(minutes=20), deadline=NOW)
    run = Run(outcome, rows(failed) if outcome.scored and outcome is not Outcome.IMPORT_ERROR else [],
              SandboxInfo(image="i", wall_seconds=0.5, exit_code=1))
    return build_result(p, v, s, run, NOW)


def test_the_batch_is_valid_against_the_shared_schema() -> None:
    doc = batch(result())          # batch() validates before returning
    event = doc["events"][0]
    assert event["kind"] == "assessment_result" and event["source"]["module"] == "assessment"
    assert doc["subject_ref"] == "subject:asha"
    assert event["skill_refs"] == [{"skill_id": "rate_limiting", "relevance": 1.0}]


def test_it_carries_facts_not_an_ability() -> None:
    """What 5/6 on a medium task is WORTH is M6's call, in its parameter file."""
    payload = batch(result())["events"][0]["payload"]
    assert (payload["level"], payload["passed"], payload["total"]) == ("medium", 5, 6)
    assert not {"observed", "ability", "score"} & set(payload)


def test_replaying_the_same_result_gives_the_same_ids() -> None:
    a, b = batch(result()), batch(result())
    assert a["batch_id"] == b["batch_id"] and a["events"][0]["event_id"] == b["events"][0]["event_id"]


def test_a_run_the_sandbox_never_made_is_not_evidence() -> None:
    with pytest.raises(NotEvidenceError, match="measured nothing"):
        batch(result(Outcome.SANDBOX_UNAVAILABLE))


def test_code_that_does_not_import_is_evidence_of_zero() -> None:
    payload = batch(result(Outcome.IMPORT_ERROR))["events"][0]["payload"]
    assert payload["passed"] == 0 and payload["outcome"] == "import_error"
