"""Variants: unique per candidate, equal in what is tested, and the model only chooses."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from assess.config import settings
from assess.patterns import PatternError, combinations, load
from assess.validation import ValidationReport
from assess.variants import (
    VariantError,
    ensure_validated,
    generate,
    model_choice,
    params_key,
    remember_valid,
    seeded,
    story_is_safe,
)

JD = "Backend developer for PayFlow, a payments company. Protect our login endpoint."


class FakeModel:
    model_id = "fake:1"

    def __init__(self, reply: dict[str, Any] | None = None, *, fail: bool = False) -> None:
        self.reply = reply or {}
        self.fail = fail
        self.calls = 0

    def complete_json(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if self.fail:
            raise ConnectionError("down")
        return self.reply


@pytest.fixture
def pattern():
    return load("rate_limiter")


class TestSeeded:
    def test_the_same_seed_gives_the_same_task(self, pattern) -> None:
        assert generate(pattern, 11).variant_id == generate(pattern, 11).variant_id

    def test_every_value_comes_from_the_allowed_lists(self, pattern) -> None:
        for seed in range(50):
            p = seeded(pattern, seed)
            assert p["twist"] in pattern.twists
            assert all(p[name] in values for name, values in pattern.parameters.items())

    def test_requirements_are_the_variant_s_own(self, pattern) -> None:
        v = generate(pattern, 3)
        assert f"RateLimiter({v.params['limit']}, {v.params['window']})" in v.requirements
        assert v.starter.startswith('"""Your solution.')

    def test_a_task_already_issued_for_the_job_is_not_issued_again(self, pattern) -> None:
        first = generate(pattern, 5)
        again = generate(pattern, 5, avoid={first.variant_id})
        assert again.variant_id != first.variant_id

    def test_running_out_of_variants_says_so(self, pattern) -> None:
        every = {params_key(pattern, p) for p in combinations(pattern)}
        with pytest.raises(VariantError, match="already issued"):
            generate(pattern, 1, avoid=every)


class TestValidationGate:
    def test_an_unvalidated_broken_pattern_is_refused(self, tmp_path: Path) -> None:
        """A wrong reference means the tests cannot be trusted: no task is issued."""
        shutil.copytree(settings.patterns_dir, tmp_path / "patterns")
        ref = tmp_path / "patterns" / "rate_limiter" / "reference.py"
        ref.write_text(ref.read_text().replace("<= now - self.window", "< now - self.window"))
        broken = load("rate_limiter", tmp_path / "patterns")
        with pytest.raises(PatternError, match="failed validation"):
            ensure_validated(broken, tmp_path / "cache")


    def test_a_validation_already_run_is_remembered_so_a_first_task_does_not_wait(self, monkeypatch, tmp_path: Path) -> None:
        """`assess validate` records a full pass; issuing then trusts it instead of proving
        the pattern again — a minute or more a recruiter's first Send would wait through."""
        p = load("lru_cache")
        n = len(combinations(p))
        remember_valid(p, ValidationReport(p.id, p.version, n, expected_cases=n * 8, reference_cases=n * 8), tmp_path)
        monkeypatch.setattr("assess.variants.validate", lambda _p: pytest.fail("validated again"))
        ensure_validated(p, tmp_path)

    def test_only_a_full_passing_validation_is_remembered(self, tmp_path: Path) -> None:
        p = load("lru_cache")
        n = len(combinations(p))
        partial = ValidationReport(p.id, p.version, 3, expected_cases=3 * 8, reference_cases=3 * 8)   # one per twist
        failing = ValidationReport(p.id, p.version, n, expected_cases=n * 8, reference_cases=n * 8,
                                   escapes={"list_scan": ["dns_lookup-2-peek"]})
        for report in (partial, failing):
            remember_valid(p, report, tmp_path)
        assert not list(tmp_path.glob("*.json")), "a partial or failing run must never vouch for a pattern"


class TestTheModelOnlyChooses:
    def test_choices_on_the_list_are_used(self, pattern) -> None:
        model = FakeModel({"params": {"key_kind": "user_email", "limit": 5, "window": 900,
                                      "twist": "retry_after"},
                           "story": "PayFlow's login endpoint is being probed by credential-stuffing bots."})
        c = model_choice(pattern, seeded(pattern, 1), JD, model)
        assert c.params == {"key_kind": "user_email", "limit": 5, "window": 900, "twist": "retry_after"}
        assert c.chosen_by == "model" and c.story_by == "model"

    def test_a_value_off_the_list_is_replaced_by_the_seeded_one(self, pattern) -> None:
        """Invented constraints are how candidates end up with unequal tasks."""
        fallback = seeded(pattern, 1)
        model = FakeModel({"params": {"key_kind": "device_id", "limit": 7, "window": 900,
                                      "twist": "lockout_webhook"}, "story": "A bank's login page."})
        c = model_choice(pattern, fallback, JD, model)
        assert c.params["key_kind"] == fallback["key_kind"]
        assert c.params["limit"] == fallback["limit"]
        assert c.params["twist"] == fallback["twist"]
        assert c.params["window"] == 900

    def test_a_story_with_a_number_not_in_the_task_is_discarded(self, pattern) -> None:
        """"10 attempts" over a limit of 5 would contradict the graded requirements."""
        model = FakeModel({"params": {"key_kind": "user_email", "limit": 5, "window": 900,
                                      "twist": "remaining"},
                           "story": "Allow 10 login attempts before blocking."})
        c = model_choice(pattern, seeded(pattern, 1), JD, model)
        assert c.story_by == "template"

    def test_a_model_outage_gives_a_seeded_task(self, pattern) -> None:
        fallback = seeded(pattern, 1)
        c = model_choice(pattern, fallback, JD, FakeModel(fail=True))
        assert c.params == fallback and c.chosen_by == "seed" and c.story_by == "template"

    def test_the_model_is_asked_once_even_when_its_choice_is_taken(self, pattern) -> None:
        reply = {"params": {"key_kind": "user_email", "limit": 5, "window": 900, "twist": "remaining"},
                 "story": "PayFlow needs its login endpoint protected."}
        taken = params_key(pattern, reply["params"])
        model = FakeModel(reply)
        v = generate(pattern, 1, context=JD, provider=model, avoid={taken})
        assert model.calls == 1 and v.variant_id != taken and v.chosen_by == "seed"

    def test_safe_story_check(self) -> None:
        params = {"limit": 5, "window": 900}
        assert story_is_safe("A service limited to 5 calls.", params)
        assert not story_is_safe("A service limited to 6 calls.", params)
        assert not story_is_safe("   ", params)


@pytest.mark.live
def test_the_real_model_fits_a_task_from_the_allowed_values(pattern) -> None:
    """Needs the configured backend. `pytest -m live`."""
    from assess.providers import default_provider

    c = model_choice(pattern, seeded(pattern, 1), JD, default_provider())
    assert c.chosen_by == "model"
    assert all(c.params[n] in v for n, v in pattern.parameters.items())
    assert c.params["twist"] in pattern.twists
    assert c.story_by == "model" and story_is_safe(c.story, c.params)
