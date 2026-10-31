"""Patterns: load, check, list, and render their text.

A pattern is a folder written by a person. Loading checks everything that can be
checked without running code — its skill is on the shared list, its files exist, and
the test names it declares are exactly the tests its hidden file defines. Running the
tests is validation's job.
"""

from __future__ import annotations

import itertools
import re
from pathlib import Path

import yaml

from assess.config import settings
from assess.models import Pattern, Scalar
from assess.skills import skill_list

FILES = ("pattern.yaml", "starter.py", "requirements.md", "story.md", "tests_hidden.py", "tests_visible.py",
         "reference.py")


class PatternError(ValueError):
    """A pattern that must not be used. The message says what to fix."""


def load(pattern_id: str, root: Path | None = None) -> Pattern:
    directory = (root or settings.patterns_dir) / pattern_id
    missing = [f for f in FILES if not (directory / f).is_file()]
    if missing:
        raise PatternError(f"{pattern_id}: missing {', '.join(missing)}")
    raw = yaml.safe_load((directory / "pattern.yaml").read_text())
    try:
        pattern = Pattern.model_validate({**raw, "directory": directory})
    except ValueError as exc:
        raise PatternError(str(exc)) from exc
    if pattern.id != pattern_id:
        raise PatternError(f"{pattern_id}: pattern.yaml says id {pattern.id!r}")
    if not skill_list().knows(pattern.skill):
        raise PatternError(f"{pattern_id}: skill {pattern.skill!r} is not on the shared skill list")
    for file, declared in (("tests_hidden.py", {*pattern.tests.core, *pattern.tests.twist}),
                           ("tests_visible.py", set(pattern.tests.visible))):
        defined = set(re.findall(r"^def test_(\w+)\(", (directory / file).read_text(), re.M))
        if defined != declared:
            raise PatternError(
                f"{pattern_id}: pattern.yaml declares {sorted(declared)} but {file} defines {sorted(defined)}"
            )
    if not pattern.tests.visible:
        raise PatternError(f"{pattern_id}: no visible examples — the candidate's Run button would test nothing")
    if not list((directory / "mutants").glob("*.py")):
        raise PatternError(f"{pattern_id}: no mutants — nothing shows the tests reject a wrong answer")
    return pattern


def all_patterns(root: Path | None = None) -> list[Pattern]:
    base = root or settings.patterns_dir
    return [load(d.name, base) for d in sorted(base.iterdir()) if (d / "pattern.yaml").is_file()]


def for_skill(skill_id: str, root: Path | None = None) -> list[Pattern]:
    return [p for p in all_patterns(root) if p.skill == skill_id]


def combinations(pattern: Pattern) -> list[dict[str, Scalar]]:
    """Every variant the pattern can produce, twist included."""
    names = list(pattern.parameters)
    out: list[dict[str, Scalar]] = []
    for values in itertools.product(*(pattern.parameters[n] for n in names)):
        for twist in pattern.twists:
            out.append({**dict(zip(names, values, strict=True)), "twist": twist})
    return out


def _fields(pattern: Pattern, params: dict[str, Scalar]) -> dict[str, Scalar]:
    """Placeholders for the text templates: each parameter, and `<name>_label`."""
    fields: dict[str, Scalar] = {**params, "time_limit": pattern.time_limit_minutes}
    for name, value in params.items():
        fields[f"{name}_label"] = pattern.labels.get(name, {}).get(str(value), str(value))
    fields["twist_rule"] = " ".join(pattern.twists[str(params["twist"])].rule.split()).format(**fields)
    return fields


def requirements(pattern: Pattern, params: dict[str, Scalar]) -> str:
    """The text a candidate is graded against. Rendered by code, never by a model, so
    the numbers in it are exactly the numbers the hidden tests use."""
    return (pattern.directory / "requirements.md").read_text().format(**_fields(pattern, params))


def template_story(pattern: Pattern, params: dict[str, Scalar]) -> str:
    return " ".join((pattern.directory / "story.md").read_text().split()).format(**_fields(pattern, params))


def mutants(pattern: Pattern) -> dict[str, Path]:
    return {p.stem: p for p in sorted((pattern.directory / "mutants").glob("*.py"))}


def mutant_applies(name: str, params: dict[str, Scalar]) -> bool:
    """`twist_<twist>__*` mutants break one twist; the rest break core behaviour."""
    if name.startswith("twist_"):
        return name.removeprefix("twist_").split("__", 1)[0] == params["twist"]
    return True
