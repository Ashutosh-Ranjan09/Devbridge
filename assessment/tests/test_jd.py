"""The JD layer: grounded extraction, a person's confirmation, and an export M6 can read."""

from __future__ import annotations

import json
from typing import Any

import jsonschema
import pytest

from assess.config import REPO
from assess.jd import (
    JobError,
    by_rules,
    chosen_tasks,
    confirm,
    edit,
    extract,
    requirements,
    task_options,
)
from assess.models import JobStatus, Priority
from assess.skills import skill_list
from assess.store import Store

JD = """Backend Engineer — PayFlow

- Build REST services in Python that handle high request volumes.
- Protect our login endpoints from abuse and credential-stuffing bots.
- Strong Python and solid SQL are required.
- Familiarity with Redis is a plus.
- Experience with Kafka event streams is a bonus.
"""


class FakeModel:
    model_id = "fake:1"

    def __init__(self, skills: list[dict[str, Any]] | None = None, *, fail: bool = False) -> None:
        self.skills = skills or []
        self.fail = fail

    def complete_json(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        if self.fail:
            raise ConnectionError("down")
        return {"skills": self.skills}


def item(sid, quote, priority="must", surface=None) -> dict[str, Any]:
    return {"skill_id": sid, "surface": surface or str(sid), "quote": quote, "priority": priority}


def by_id(job):
    return {s.skill_id: s for s in job.skills}


class TestExtraction:
    def test_a_quote_not_in_the_jd_drops_the_skill(self) -> None:
        """A model that invents a requirement invents its quote."""
        job = extract(JD, FakeModel([item("python", "Strong Python and solid SQL are required."),
                                     item("go", "Experience with Go microservices.")]))
        assert "go" not in by_id(job) and "python" in by_id(job)
        assert job.dropped_unquoted == 1

    def test_quotes_are_matched_ignoring_case_and_spacing(self) -> None:
        job = extract(JD, FakeModel([item("redis", "familiarity   with REDIS is a plus.", "nice")]))
        assert by_id(job)["redis"].priority is Priority.NICE

    def test_an_id_off_the_list_keeps_only_the_name(self) -> None:
        job = extract(JD, FakeModel([item("kafka", "Experience with Kafka event streams is a bonus.",
                                          "nice", "Kafka")]))
        row = job.skills[0]
        assert row.skill_id is None and row.surface == "Kafka"
        assert requirements(confirm(edit(job, must={"python": 0.3}), "r"))["not_on_list"] == ["Kafka"]

    def test_an_inferred_skill_is_kept_and_marked_for_review(self) -> None:
        """"protect our login endpoints" never says rate limiting; a person must agree."""
        job = extract(JD, FakeModel([item("rate_limiting", "Protect our login endpoints from abuse")]))
        row = by_id(job)["rate_limiting"]
        assert row.needs_review and row.assessable

    def test_a_named_skill_is_not_marked(self) -> None:
        job = extract(JD, FakeModel([item("python", "Strong Python and solid SQL are required.")]))
        assert not by_id(job)["python"].needs_review

    def test_an_unclear_priority_becomes_nice_and_is_marked(self) -> None:
        job = extract(JD, FakeModel([item("redis", "Familiarity with Redis is a plus.", "critical")]))
        row = by_id(job)["redis"]
        assert row.priority is Priority.NICE and row.needs_review

    def test_a_must_mention_outranks_a_nice_one(self) -> None:
        job = extract(JD, FakeModel([item("python", "Build REST services in Python", "nice"),
                                     item("python", "Strong Python and solid SQL are required.")]))
        assert [s.priority for s in job.skills] == [Priority.MUST]

    def test_a_model_outage_falls_back_to_rules(self) -> None:
        job = extract(JD, FakeModel(fail=True))
        assert job.extracted_by == "rules" and "python" in by_id(job)


class TestRules:
    def test_a_skill_takes_its_most_demanding_mention(self) -> None:
        rows = {s.skill_id: s for s in by_rules(JD, skill_list())}
        assert rows["python"].priority is Priority.MUST
        assert "required" in rows["python"].quote
        assert rows["redis"].priority is Priority.NICE

    def test_every_rule_proposal_is_marked_for_review(self) -> None:
        assert all(s.needs_review for s in by_rules(JD, skill_list()))

    def test_whole_words_only(self) -> None:
        """"go" is in "Good" and "go-getter"; "c" is in every sentence. Neither is a skill there."""
        assert "go" not in {s.skill_id for s in by_rules("Good communication; a go-getter.", skill_list())}
        assert "c" not in {s.skill_id for s in by_rules("Clear code.", skill_list())}


class TestConfirmation:
    def test_edit_sets_priorities_bars_and_adds_from_the_list(self) -> None:
        job = edit(extract(JD, None), must={"python": 0.4, "rate_limiting": None}, nice=["sql"])
        rows = by_id(job)
        assert rows["python"].bar == 0.4 and rows["rate_limiting"].quote == "(added by the reviewer)"
        assert rows["sql"].priority is Priority.NICE and rows["sql"].bar is None

    def test_an_unknown_id_is_refused(self) -> None:
        with pytest.raises(JobError, match="not on the shared skill list"):
            edit(extract(JD, None), must={"fortran77": 0.5})

    def test_a_bar_outside_0_to_1_is_refused(self) -> None:
        """`assess jd edit --must python:5` once stored a bar of 5.0: the edit is a
        model_copy, which does not re-validate."""
        with pytest.raises(JobError, match="between 0 and 1"):
            edit(extract(JD, None), must={"python": 5.0})

    def test_confirming_needs_a_must_have_and_a_name(self) -> None:
        job = edit(extract(JD, None), nice=["python", "sql"])
        job = edit(job, drop=[s.skill_id for s in job.skills if s.skill_id and s.priority is Priority.MUST])
        with pytest.raises(JobError, match="must-have"):
            confirm(job, "r")
        with pytest.raises(JobError, match="who confirmed"):
            confirm(edit(job, must={"python": 0.3}), "  ")

    def test_a_confirmed_job_is_never_edited(self, tmp_path) -> None:
        store = Store(tmp_path / "a.db")
        job = confirm(edit(extract(JD, None), must={"python": 0.3}), "recruiter")
        store.save_job(job)
        with pytest.raises(JobError, match="never edited"):
            edit(job, drop=["python"])
        with pytest.raises(ValueError, match="never edited"):
            store.save_job(job.model_copy(update={"status": JobStatus.PROPOSED}))

    def test_an_unbarred_must_have_nothing_can_test_filters_on_any_evidence(self) -> None:
        job = confirm(edit(extract(JD, None), must={"python": None}), "recruiter")
        assert by_id(job)["python"].bar == 0.0

    def test_an_unbarred_assessable_must_have_is_assessed_not_filtered(self) -> None:
        """Nobody has evidence for a skill before being tested on it; as a filter it
        would shortlist no one."""
        job = confirm(edit(extract(JD, None), must={"python": 0.3, "rate_limiting": None}), "recruiter")
        assert by_id(job)["rate_limiting"].bar is None
        doc = requirements(job)
        assert {m["skill_id"]: m["bar"] for m in doc["must"]}["rate_limiting"] is None


class TestTasks:
    """The recruiter picks the tasks every applicant gets; the same for all of them."""

    def job(self):
        return edit(extract(JD, None), must={"python": 0.3, "rate_limiting": None, "algorithms": None})

    def test_by_default_each_must_have_gets_its_first_pattern(self) -> None:
        job = self.job()
        assert chosen_tasks(job) == ["rate_limiter", "top_k_frequent"]
        assert task_options(job)["python"] == [], "a must-have no pattern tests offers nothing"

    def test_the_recruiter_s_choice_is_what_applicants_get(self) -> None:
        job = edit(self.job(), tasks=["top_k_frequent"])
        assert chosen_tasks(job) == ["top_k_frequent"]
        assert chosen_tasks(edit(job, tasks=[])) == [], "choosing none is a choice"

    def test_a_task_for_no_must_have_is_refused(self) -> None:
        with pytest.raises(JobError, match="tests none of this job's must-haves"):
            edit(edit(extract(JD, None), must={"python": 0.3}), tasks=["rate_limiter"])

    def test_dropping_a_must_have_takes_its_task_with_it(self) -> None:
        job = edit(self.job(), tasks=["rate_limiter", "top_k_frequent"])
        assert chosen_tasks(edit(job, nice=["algorithms"])) == ["rate_limiter"]
        assert chosen_tasks(edit(job, drop=["rate_limiting"])) == ["top_k_frequent"]

    def test_a_new_must_have_starts_with_its_first_task_ticked(self) -> None:
        job = edit(edit(extract(JD, None), must={"python": 0.3, "rate_limiting": None}), tasks=["rate_limiter"])
        assert chosen_tasks(edit(job, must={"algorithms": None})) == ["rate_limiter", "top_k_frequent"]
        assert chosen_tasks(edit(job, must={"algorithms": None}, tasks=[])) == ["top_k_frequent"]

    def test_confirming_writes_the_choice_down(self) -> None:
        assert confirm(self.job(), "r").tasks == ["rate_limiter", "top_k_frequent"]
        assert confirm(edit(self.job(), tasks=["rate_limiter"]), "r").tasks == ["rate_limiter"]

    def test_a_must_have_left_untested_is_filtered_on_any_evidence_not_left_unbarred(self) -> None:
        """Unticked, `algorithms` is never tested: unbarred it would filter nobody."""
        job = confirm(edit(self.job(), tasks=["rate_limiter"]), "r")
        assert by_id(job)["algorithms"].bar == 0.0 and by_id(job)["rate_limiting"].bar is None
        assessable = {m["skill_id"]: m["assessable"] for m in requirements(job)["must"]}
        assert {k: assessable[k] for k in ("rate_limiting", "algorithms")} == {"rate_limiting": True, "algorithms": False}


class TestExport:
    def test_only_a_confirmed_job_is_exported(self) -> None:
        with pytest.raises(JobError, match="not confirmed"):
            requirements(extract(JD, None))

    def test_the_export_validates_against_the_shared_schema(self) -> None:
        job = confirm(edit(extract(JD, None), must={"python": 0.3, "rate_limiting": 0.2}), "recruiter")
        doc = requirements(job)
        schema = json.loads((REPO / "schemas" / "job-requirements.schema.json").read_text())
        jsonschema.validate(doc, schema)
        assert {m["skill_id"]: m["assessable"] for m in doc["must"]}["rate_limiting"] is True
