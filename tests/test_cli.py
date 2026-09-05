"""The command line.

Thin by design, so these tests are thin too: they check that each command wires up
and that the two with no model dependency say the right thing. Anything needing
Ollama or the network is marked `live` and excluded by default.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from cvv.cli import app
from cvv.rules import REGISTRY

runner = CliRunner()
CV = Path("docs/CV-SDE-AR.pdf")


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "cvv" in result.stdout


class TestRules:
    """`cvv rules` is the live, introspectable catalogue.

    A reviewer should be able to see what the system checks without reading the
    source — and in particular see which rules declare `scoring=false`, so a rule
    that is displayed but structurally barred from moving a number is visible rather
    than buried.
    """

    def test_lists_every_registered_rule(self) -> None:
        result = runner.invoke(app, ["rules"])
        assert result.exit_code == 0
        for rule in REGISTRY:
            assert rule.rule_id in result.stdout

    def test_shows_tier_and_whether_it_scores(self) -> None:
        result = runner.invoke(app, ["rules"])
        assert "decisive" in result.stdout
        assert "attention" in result.stdout
        assert "SCORES" in result.stdout


class TestInspect:
    """Reading a document without calling a model separates "the document was read
    badly" from "the model read it badly" — different problems, different fixes."""

    @pytest.mark.skipif(not CV.is_file(), reason="the reference CV is not present")
    def test_reports_sections_and_provenance_metadata(self) -> None:
        result = runner.invoke(app, ["inspect", str(CV)])
        assert result.exit_code == 0
        assert "EDUCATION" in result.stdout
        assert "AWARDS AND ACHIEVEMENTS" in result.stdout
        # The PDF producer is itself a provenance signal — rule D4 reads it.
        assert "iText" in result.stdout

    def test_a_missing_file_fails_cleanly(self) -> None:
        result = runner.invoke(app, ["inspect", "nope.pdf"])
        assert result.exit_code == 2


def test_verify_rejects_a_missing_file() -> None:
    result = runner.invoke(app, ["verify", "nope.pdf"])
    assert result.exit_code == 2


@pytest.mark.live
@pytest.mark.skipif(not CV.is_file(), reason="the reference CV is not present")
def test_offline_verify_abstains_everywhere_with_reasons() -> None:
    """THE INVARIANT, as an executable check.

    A CV verified with no external source at all still produces a complete report:
    every check that needed a source abstains, each with its reason attached, and
    nothing goes silent. The document-only path is a real path, not a failure mode.

    "Accounted for" is the assertion, and it has two forms. A rule that FIRED shows
    its finding, cited as `[D2]`; a rule that did not shows its summary, under
    verified, "nothing raised", or "not evaluated" with the reason. Requiring the
    summary in both cases was the earlier version of this test, and it failed the
    moment a document-intrinsic rule started firing on the reference CV — which is
    the rule working, not the report losing it.
    """
    result = runner.invoke(app, ["verify", str(CV), "--offline"])
    assert result.exit_code == 0
    assert "NOT EVALUATED" in result.stdout
    assert "no external source was consulted" in result.stdout
    assert "OUT OF SCOPE" in result.stdout
    assert "No overall score is produced" in result.stdout
    for rule in REGISTRY:
        accounted = f"[{rule.rule_id}]" in result.stdout or rule.summary in result.stdout
        assert accounted, f"{rule.rule_id} vanished from the report"
