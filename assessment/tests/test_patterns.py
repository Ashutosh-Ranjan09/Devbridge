"""Patterns load, render and validate — and a broken one is refused, with the reason."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from assess.config import settings
from assess.patterns import (
    PatternError,
    combinations,
    for_skill,
    load,
    mutant_applies,
    requirements,
    template_story,
)
from assess.skills import skill_list
from assess.validation import validate


@pytest.fixture
def copy(tmp_path: Path) -> Path:
    """A private copy of the patterns folder, safe to break."""
    shutil.copytree(settings.patterns_dir, tmp_path / "patterns")
    return tmp_path / "patterns"


def edit_yaml(root: Path, change) -> None:
    path = root / "rate_limiter" / "pattern.yaml"
    doc = yaml.safe_load(path.read_text())
    change(doc)
    path.write_text(yaml.safe_dump(doc))


class TestLoading:
    def test_the_shipped_pattern_loads(self) -> None:
        p = load("rate_limiter")
        assert p.skill == "rate_limiting" and skill_list().knows(p.skill)
        assert p.combinations == len(combinations(p)) == 108

    def test_the_dsa_pattern_loads(self) -> None:
        p = load("top_k_frequent")
        assert p.skill == "algorithms" and skill_list().knows(p.skill)
        assert p.combinations == len(combinations(p)) == 27

    def test_patterns_are_found_by_skill(self) -> None:
        assert [p.id for p in for_skill("rate_limiting")] == ["rate_limiter"]
        assert [p.id for p in for_skill("algorithms")] == ["top_k_frequent"]
        assert for_skill("python") == []

    def test_unequal_twists_are_refused(self, copy: Path) -> None:
        """Equal difficulty is a property of the pattern, not a hope."""
        edit_yaml(copy, lambda d: d["twists"]["retry_after"].update(rating=2))
        with pytest.raises(PatternError, match="one rating"):
            load("rate_limiter", copy)

    def test_a_skill_off_the_shared_list_is_refused(self, copy: Path) -> None:
        edit_yaml(copy, lambda d: d.update(skill="throttling"))
        with pytest.raises(PatternError, match="not on the shared skill list"):
            load("rate_limiter", copy)

    def test_declared_and_defined_tests_must_agree(self, copy: Path) -> None:
        edit_yaml(copy, lambda d: d["tests"]["core"].append("handles_bursts"))
        with pytest.raises(PatternError, match="handles_bursts"):
            load("rate_limiter", copy)

    def test_visible_examples_are_required_and_must_match_their_names(self, copy: Path) -> None:
        """The Run button needs examples, declared like the hidden tests."""
        edit_yaml(copy, lambda d: d["tests"]["visible"].append("example_burst"))
        with pytest.raises(PatternError, match=r"tests_visible\.py defines"):
            load("rate_limiter", copy)
        (copy / "rate_limiter" / "tests_visible.py").unlink()
        with pytest.raises(PatternError, match=r"missing tests_visible\.py"):
            load("rate_limiter", copy)

    def test_a_reference_failing_a_visible_example_is_caught(self, copy: Path) -> None:
        """An example the reference fails would show a right answer as wrong."""
        f = copy / "rate_limiter" / "tests_visible.py"
        f.write_text(f.read_text().replace('expected 429"', 'expected 429"\n    assert r.status == 200'))
        report = validate(load("rate_limiter", copy))
        assert not report.ok and report.visible_failures

    def test_a_pattern_without_mutants_is_refused(self, copy: Path) -> None:
        shutil.rmtree(copy / "rate_limiter" / "mutants")
        (copy / "rate_limiter" / "mutants").mkdir()
        with pytest.raises(PatternError, match="no mutants"):
            load("rate_limiter", copy)


class TestRendering:
    def test_requirements_carry_exactly_the_variant_s_numbers(self) -> None:
        p = load("rate_limiter")
        params = {"key_kind": "api_key", "limit": 15, "window": 3600, "twist": "retry_after"}
        text = requirements(p, params)
        assert "RateLimiter(15, 3600)" in text and "15 requests per API key" in text
        assert "(1 hour)" in text and "`Retry-After`" in text and "plus 3600" in text
        assert "{" not in text.replace('{"error"', ""), "no placeholder left unrendered"

    def test_every_combination_renders(self) -> None:
        p = load("rate_limiter")
        for params in combinations(p):
            assert str(params["limit"]) in requirements(p, params)
            assert template_story(p, params)

    def test_every_dsa_combination_renders(self) -> None:
        p = load("top_k_frequent")
        for params in combinations(p):
            text = requirements(p, params)
            assert f"`k = {params['k']}`" in text and "{" not in text
            assert template_story(p, params)

    def test_twist_mutants_apply_only_to_their_twist(self) -> None:
        params = {"key_kind": "ip_address", "limit": 3, "window": 60, "twist": "remaining"}
        assert mutant_applies("off_by_one", params)
        assert mutant_applies("twist_remaining__before_counting", params)
        assert not mutant_applies("twist_retry_after__rounds_down", params)


class TestValidation:
    def test_the_shipped_pattern_is_valid_in_every_combination(self) -> None:
        report = validate(load("rate_limiter"))
        assert report.ok, (report.reference_failures[:3], {m: e[:2] for m, e in report.escapes.items() if e})
        assert report.reference_cases == 108 * 6

    def test_the_dsa_pattern_is_valid_once_per_twist(self) -> None:
        """Every combination takes over a minute — the quadratic mutant must run out
        its time in each — so the default run takes one combination per twist."""
        p = load("top_k_frequent")
        cases = [{"item_kind": kind, "k": k, "twist": twist}
                 for kind, k, twist in zip(p.parameters["item_kind"], p.parameters["k"], p.twists, strict=True)]
        report = validate(p, cases)
        assert report.ok, (report.reference_failures[:3], {m: e for m, e in report.escapes.items() if e})
        assert report.reference_cases == 3 * 8
        assert report.caught_by["rescans_per_item"] == {"large_input"}

    @pytest.mark.slow
    def test_the_dsa_pattern_is_valid_in_every_combination(self) -> None:
        report = validate(load("top_k_frequent"))
        assert report.ok, (report.reference_failures[:3], {m: e[:2] for m, e in report.escapes.items() if e})
        assert report.reference_cases == 27 * 8

    def test_the_lru_pattern_is_valid_once_per_twist(self) -> None:
        """Every combination takes about a minute — the list-scanning mutant must run out
        its time in each — so the default run takes one combination per twist."""
        p = load("lru_cache")
        cases = [{"item_kind": kind, "capacity": c, "twist": twist}
                 for kind, c, twist in zip(p.parameters["item_kind"], p.parameters["capacity"], p.twists, strict=True)]
        report = validate(p, cases)
        assert report.ok, (report.reference_failures[:3], {m: e for m, e in report.escapes.items() if e})
        assert report.reference_cases == 3 * 8
        assert report.caught_by["list_scan"] == {"many_operations_fast"}, "only the timing test sees linear time"

    @pytest.mark.slow
    def test_the_lru_pattern_is_valid_in_every_combination(self) -> None:
        report = validate(load("lru_cache"))
        assert report.ok, (report.reference_failures[:3], {m: e[:2] for m, e in report.escapes.items() if e})
        assert report.reference_cases == 27 * 8

    def test_a_wrong_reference_is_caught(self, copy: Path) -> None:
        """A test the reference fails would fail a candidate for the test's mistake."""
        ref = copy / "rate_limiter" / "reference.py"
        ref.write_text(ref.read_text().replace("<= now - self.window", "< now - self.window"))
        report = validate(load("rate_limiter", copy))
        assert not report.ok and report.reference_failures

    def test_a_weak_suite_is_caught(self, copy: Path) -> None:
        """Remove the one test that catches a fixed-window counter: it now escapes."""
        tests = copy / "rate_limiter" / "tests_hidden.py"
        src = tests.read_text()
        start = src.index("@each\ndef test_exact_boundary")
        end = src.index("@each\ndef test_window_slides")
        tests.write_text(src[:start] + src[end:])
        edit_yaml(copy, lambda d: d["tests"]["core"].remove("exact_boundary"))
        report = validate(load("rate_limiter", copy))
        assert not report.ok
        assert report.escapes["counts_rejected"], "a mutant only exact_boundary caught now escapes"
