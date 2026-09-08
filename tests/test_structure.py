"""The structural rules CLAUDE.md states, enforced rather than asserted.

CLAUDE.md has claimed for some time that `rules/` importing only pure modules is
"enforced by a test that walks the imports". No such test existed. The rule held
anyway — but it held by luck, and a rule nothing checks is a comment.

Writing it also showed the stated rule was already wrong: `rules.py` imports
`filters`, `ids`, `logs` and `reference` as well as `models` and `intervals`. All are
pure, so the SPIRIT — a rule reaches no network and no gathered evidence — is intact.
The letter is what is enforced here, against a list that names each and says why.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path("src/cvv")

# What a rule may import, and the reason each is safe. The test is that nothing else
# appears; adding to this list is a deliberate act.
PURE = {
    "cvv.models",      # the contract
    "cvv.intervals",   # the date algebra
    "cvv.ids",         # stable identifiers, no I/O
    "cvv.filters",     # pure predicates over claims
    "cvv.reference",   # curated tables loaded from data/
    "cvv.logs",        # writes to stderr, gathers nothing
}

# Anything that reaches the outside world. A rule importing one of these could gather
# evidence at evaluation time, which is the thing the EvidenceBundle exists to prevent.
IMPURE = {"httpx", "psycopg", "cvv.gather", "cvv.github", "cvv.leetcode", "cvv.api",
          "cvv.store", "cvv.providers", "cvv.ingest"}


def imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


class TestRulesStayPure:
    def test_rules_import_nothing_that_reaches_the_world(self) -> None:
        """If a rule needs data it arrives in the EvidenceBundle or the rule
        abstains. An import of httpx here would let a check gather evidence at
        evaluation time, and abstention would stop meaning anything."""
        reached = imports_of(SRC / "rules.py") & IMPURE
        assert not reached, f"rules.py reaches {sorted(reached)}"

    def test_every_cvv_import_in_rules_is_on_the_pure_list(self) -> None:
        cvv_imports = {i for i in imports_of(SRC / "rules.py") if i.startswith("cvv")}
        assert not (cvv_imports - PURE), (
            f"rules.py imports {sorted(cvv_imports - PURE)}, which is not on the pure "
            "list. Either it is pure and belongs on the list with a reason, or a rule "
            "is about to gather its own evidence."
        )

    def test_the_pure_list_has_no_dead_entries(self) -> None:
        stale = PURE - imports_of(SRC / "rules.py")
        assert not stale, f"{sorted(stale)} is on the pure list and no longer imported"


class TestNarrativeCannotReachTheDocument:
    """The faithfulness guarantee is the signature, not the prompt. `narrate` takes a
    FindingsReport; if it could import the ingest or the graph it could quote text no
    rule ever found."""

    def test_narrative_imports_no_document_source(self) -> None:
        reached = imports_of(SRC / "narrative.py") & {
            "cvv.ingest", "cvv.extract", "cvv.gather", "cvv.github", "cvv.leetcode"
        }
        assert not reached, f"narrative.py reaches {sorted(reached)}"


class TestTheAdvertisedEntryPoint:
    """`cvv.pipeline.verify` is what CLAUDE.md and the README tell a library caller to
    use, and nothing imported it or tested it — so it could have rotted silently while
    the CLI moved on."""

    def test_it_exists_with_the_documented_signature(self) -> None:
        import inspect

        from cvv.pipeline import verify

        sig = inspect.signature(verify)
        assert list(sig.parameters) == ["path", "provider"]
        assert sig.parameters["provider"].default is None, "a caller may omit the model"

    def test_it_returns_the_three_documented_artefacts(self) -> None:
        import typing

        from cvv.models import ClaimGraph, EvidenceBundle, FindingsReport
        from cvv.pipeline import verify

        hints = typing.get_type_hints(verify)
        assert hints["return"] == tuple[ClaimGraph, EvidenceBundle, FindingsReport]


class TestIdentifiersAreStable:
    """An unstable claim_id silently breaks the `supersedes` diff between two runs of
    the same document: every claim looks new, and a reviewer comparing versions sees
    a rewrite where nothing changed."""

    def test_the_same_inputs_give_the_same_claim_id(self) -> None:
        from cvv.ids import claim_id

        a = claim_id("cg_1", 42, "achievement", "AR009")
        b = claim_id("cg_1", 42, "achievement", "AR009")
        assert a == b and a.startswith("c")

    @pytest.mark.parametrize(
        "changed",
        [("cg_2", 42, "achievement", "AR009"), ("cg_1", 43, "achievement", "AR009"),
         ("cg_1", 42, "employment", "AR009"), ("cg_1", 42, "achievement", "ar009")],
    )
    def test_any_input_changing_changes_the_id(self, changed: tuple) -> None:
        from cvv.ids import claim_id

        assert claim_id(*changed) != claim_id("cg_1", 42, "achievement", "AR009")

    def test_the_discriminator_separates_claims_sharing_a_span(self) -> None:
        """One skills line yields several claims with the same span and kind. Without
        the discriminator they collide onto one id and all but one vanish."""
        from cvv.ids import claim_id

        assert claim_id("cg_1", 10, "skill", "python") != claim_id("cg_1", 10, "skill", "go")

    def test_a_finding_id_does_not_depend_on_claim_order(self) -> None:
        from cvv.ids import finding_id

        assert finding_id("fr_1", "D5", ["ca1", "cb2"]) == finding_id("fr_1", "D5", ["cb2", "ca1"])
