"""The skill resolver — which shared skill each name means, against a fake model.

No model is called. The fake answers from a table, and can be made to wander off
the list, skip a name, or fail outright: the three ways a real one goes wrong, and
the three the resolver has to survive without crediting a skill nobody claimed.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from cvv.models import ClaimKind, SkillSource
from cvv.skills import SKILLS_DIR, cached_decisions, names_in, promote, resolve_skills
from tests.cvdata import DOCUMENT, SKILLS_LINE, make_claim, make_graph
from tests.test_rules import bundle, github, repo


class FakeModel:
    """Answers from a table; records every name it was asked about."""

    model_id = "fake:1"

    def __init__(self, answers: dict[str, Any], *, fail: bool = False) -> None:
        self.answers = answers
        self.fail = fail
        self.asked: list[str] = []

    def complete_json(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        if self.fail:
            raise ConnectionError("model is down")
        names = json.loads(prompt.split("Names:\n", 1)[1].split("\n\nReturn", 1)[0])
        self.asked.extend(names)
        return {
            "mappings": [
                {"name": n, "skill_id": self.answers[n]} for n in names if n in self.answers
            ]
        }


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    """A copy of the shared list, so promoting writes nowhere real."""
    copy = tmp_path / "skills"
    shutil.copytree(SKILLS_DIR, copy)
    return copy


def report_naming(*names: str, languages: tuple[str, ...] = (), frameworks: tuple[str, ...] = ()):
    claim = make_claim(SKILLS_LINE, DOCUMENT, claim_id="cskl01", kind=ClaimKind.SKILL,
                       skill_refs=list(names))
    graph = make_graph([claim], DOCUMENT)
    evidence = bundle(graph, github=github(repos=(repo("x", languages=languages,
                                                      frameworks=frameworks),)))
    return graph, evidence


def resolve(graph, evidence, model, tmp_path: Path, skills_dir: Path):
    return resolve_skills(graph, evidence, model, cache=tmp_path / "cache.json",
                          directory=skills_dir)


class TestRulesComeFirst:
    def test_an_id_or_an_alias_never_reaches_the_model(self, tmp_path, skills_dir) -> None:
        model = FakeModel({})
        got = resolve(*report_naming("Python", "Next.js", "C++"), model, tmp_path, skills_dir)
        assert got["Python"].id == "python" and got["Python"].by is SkillSource.RULE
        assert got["Next.js"].id == "nextjs" and got["Next.js"].by is SkillSource.ALIAS
        assert got["C++"].id == "cpp"
        assert model.asked == []

    def test_every_name_in_the_report_is_covered(self) -> None:
        """The census and the manifests are names M6 places too — not only claims."""
        graph, evidence = report_naming("React.js", languages=("TypeScript",),
                                        frameworks=("next", "axios"))
        assert names_in(graph, evidence) == ["React.js", "TypeScript", "next", "axios"]


class TestTheModelIsClosed:
    def test_a_name_the_rules_cannot_place_is_asked(self, tmp_path, skills_dir) -> None:
        model = FakeModel({"Amazon Web Services": "aws", "VS Code": None})
        got = resolve(*report_naming("Amazon Web Services", "VS Code"), model, tmp_path,
                      skills_dir)
        assert got["Amazon Web Services"].id == "aws"
        assert got["Amazon Web Services"].by is SkillSource.MODEL
        assert got["VS Code"].id is None and got["VS Code"].by is SkillSource.MODEL

    def test_an_answer_off_the_list_is_none(self, tmp_path, skills_dir) -> None:
        """The model may not invent a skill: "vscode" is not an id."""
        model = FakeModel({"VS Code": "vscode"})
        got = resolve(*report_naming("VS Code"), model, tmp_path, skills_dir)
        assert got["VS Code"].id is None

    def test_a_skipped_name_is_unresolved_not_guessed(self, tmp_path, skills_dir) -> None:
        model = FakeModel({"Amazon Web Services": "aws"})
        got = resolve(*report_naming("Amazon Web Services", "Kubernetes Engine"), model,
                      tmp_path, skills_dir)
        assert got["Kubernetes Engine"].id is None
        assert got["Kubernetes Engine"].by is SkillSource.UNRESOLVED

    def test_a_model_that_is_down_does_not_fail_the_verification(self, tmp_path,
                                                                 skills_dir) -> None:
        got = resolve(*report_naming("Python", "Amazon Web Services"), FakeModel({}, fail=True),
                      tmp_path, skills_dir)
        assert got["Python"].id == "python", "rules still answer"
        assert got["Amazon Web Services"].by is SkillSource.UNRESOLVED

    def test_no_model_at_all_leaves_the_rest_unresolved(self, tmp_path, skills_dir) -> None:
        got = resolve(*report_naming("Amazon Web Services"), None, tmp_path, skills_dir)
        assert got["Amazon Web Services"].by is SkillSource.UNRESOLVED


class TestAnswersAreRemembered:
    def test_a_name_is_asked_once(self, tmp_path, skills_dir) -> None:
        """The same CV must not map React.js to react on Monday and to none on
        Tuesday. The second run reads the first run's answer."""
        first = FakeModel({"React.js": "react"})
        resolve(*report_naming("React.js"), first, tmp_path, skills_dir)
        second = FakeModel({"React.js": None})
        got = resolve(*report_naming("React.js"), second, tmp_path, skills_dir)
        assert second.asked == []
        assert got["React.js"].id == "react" and got["React.js"].by is SkillSource.MODEL

    def test_a_remembered_id_no_longer_on_the_list_is_not_an_answer(self, tmp_path,
                                                                    skills_dir) -> None:
        resolve(*report_naming("React.js"), FakeModel({"React.js": "react"}), tmp_path,
                skills_dir)
        cache = tmp_path / "cache.json"
        doc = json.loads(cache.read_text())
        for decisions in doc["by_ontology_version"].values():
            decisions["react.js"]["id"] = "removed_skill"
        cache.write_text(json.dumps(doc))
        got = resolve(*report_naming("React.js"), FakeModel({}), tmp_path, skills_dir)
        assert got["React.js"].id is None


class TestPromotion:
    def test_a_promoted_decision_becomes_a_rule(self, tmp_path, skills_dir) -> None:
        cache = tmp_path / "cache.json"
        resolve(*report_naming("Amazon Web Services"),
                FakeModel({"Amazon Web Services": "aws"}), tmp_path, skills_dir)
        assert promote("Amazon Web Services", cache, skills_dir) == "aws"
        got = resolve(*report_naming("Amazon Web Services"), FakeModel({}), tmp_path,
                      skills_dir)
        assert got["Amazon Web Services"].by is SkillSource.ALIAS
        assert "# Other names for skills" in (skills_dir / "aliases.yaml").read_text(), (
            "the file's comments survive an append"
        )
        assert cached_decisions(cache, skills_dir)[0]["promoted"] is True

    def test_nothing_is_promoted_that_maps_to_no_skill(self, tmp_path, skills_dir) -> None:
        cache = tmp_path / "cache.json"
        resolve(*report_naming("VS Code"), FakeModel({"VS Code": None}), tmp_path, skills_dir)
        with pytest.raises(ValueError, match="no skill"):
            promote("VS Code", cache, skills_dir)

    def test_a_name_never_decided_cannot_be_promoted(self, tmp_path, skills_dir) -> None:
        with pytest.raises(KeyError):
            promote("Haskell", tmp_path / "cache.json", skills_dir)
