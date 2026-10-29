"""The mutation harness — what it measures and what it refuses to count.

The unit tests elsewhere prove each rule does what its author intended. They cannot
prove the system detects a falsified CV, because every fixture in them was built to
exercise the rule it feeds. This file tests the thing that can.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cvv.evaluate import CATALOGUE, Outcome, render_evaluation, run
from cvv.models import ClaimGraph, EvidenceBundle
from cvv.rules import REGISTRY
from tests.cvdata import CF_RANK, CF_RATING, DOCUMENT, make_claim, make_graph
from tests.test_rules import bundle, codeforces

CV = Path("docs/CV-SDE-AR.pdf")


class TestTheCatalogue:
    def test_every_mutation_names_a_registered_rule(self) -> None:
        """A mutation expecting a rule that does not exist can never be caught, and
        would sit in the table as a permanent failure nobody can fix."""
        registered = {r.rule_id for r in REGISTRY}
        for mutation in CATALOGUE:
            assert mutation.expect in registered, mutation.mutation_id

    def test_mutation_ids_are_unique(self) -> None:
        ids = [m.mutation_id for m in CATALOGUE]
        assert len(ids) == len(set(ids))

    def test_every_decisive_platform_and_github_rule_has_one(self) -> None:
        """Coverage of the harness itself. A decisive rule with no mutation is a
        check nobody has ever seen fire on a real document."""
        covered = {m.expect for m in CATALOGUE}
        for rule_id in ("P1", "P2", "P4", "G2", "G4", "G6", "G7", "D5", "D7", "D9", "W1"):
            assert rule_id in covered, rule_id


class TestWhatItMeasures:
    def graph_and_bundle(self) -> tuple[ClaimGraph, EvidenceBundle]:
        claims = [
            make_claim(CF_RATING, DOCUMENT, claim_id="c001", platform="codeforces",
                       metric="max_rating", value=1495),
            make_claim(CF_RANK, DOCUMENT, claim_id="c002", platform="codeforces",
                       metric="contest_rank", value=1106),
        ]
        graph = make_graph(claims, DOCUMENT)
        # The recorded rank is 1109 against a claimed 1106, so P2 fires on the
        # UNMUTATED document — which is the case the excusal logic exists for.
        return graph, bundle(graph, platforms=[codeforces(ranks=(1109,))])

    def test_a_mutation_the_document_cannot_carry_is_skipped_not_failed(self) -> None:
        """A CV with no projects cannot be given an anachronistic one. Counting that
        as a miss would make the detection rate a property of the document rather
        than of the system."""
        graph, b = self.graph_and_bundle()
        _, outcomes = run(graph, b)
        skipped = [o for o in outcomes if o.skipped]
        assert skipped, "this baseline has no repositories or projects to corrupt"
        assert all(not o.caught for o in skipped)

    def test_the_responsible_rule_must_be_the_one_that_notices(self) -> None:
        """"Something fired" is not detection. If P1's mutation were caught only by
        P2, the rating check would be broken and the table would say 100%."""
        graph, b = self.graph_and_bundle()
        _, outcomes = run(graph, b)
        rating = next(o for o in outcomes if o.mutation_id == "rating-inflated")
        assert rating.caught
        assert rating.expect == "P1"

    def test_baseline_findings_are_excused_not_counted_as_collateral(self) -> None:
        """P2 fires on this baseline because the recorded rank differs from the
        claim. Every mutated run would otherwise inherit it as collateral and the
        number would measure the document, not the mutation."""
        graph, b = self.graph_and_bundle()
        baseline, outcomes = run(graph, b)
        assert "P2" in baseline
        applied = [o for o in outcomes if o.skipped is None]
        assert all("P2" not in o.collateral for o in applied)

    def test_a_rule_firing_on_the_baseline_is_caught_only_by_a_different_finding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """P2 already fires here. A mutation that changes nothing must not count as
        P2 noticing it — firing again is what P2 would have done anyway."""
        from cvv import evaluate
        from cvv.evaluate import Mutation

        graph, b = self.graph_and_bundle()
        monkeypatch.setattr(evaluate, "CATALOGUE", [
            Mutation("nothing", "P2", "changes nothing", lambda g, bb: (g, bb)),
            CATALOGUE[1],  # rank-inflated: the rank P2 reads really moves
        ])
        _, outcomes = run(graph, b)
        assert [o.caught for o in outcomes] == [False, True]


class TestTheReport:
    def test_it_states_what_the_baseline_excused(self) -> None:
        """A reader must be able to see what was subtracted before believing the
        collateral figure."""
        text = render_evaluation({"P2", "D2"}, [])
        assert "D2, P2" in text
        assert "excused throughout" in text

    def test_collateral_is_explained_as_the_number_that_matters(self) -> None:
        text = render_evaluation(set(), [Outcome("m", "P1", "d", caught=True)])
        assert "sensitive or merely noisy" in text
        assert "lands" in text


@pytest.mark.live
@pytest.mark.skipif(not CV.is_file(), reason="the reference CV is not present")
def test_every_mutation_is_caught_on_the_reference_cv() -> None:
    """THE THESIS NUMBER, as an executable check.

    Needs Ollama and the network — it runs the real pipeline, then corrupts one fact
    at a time. Both figures are asserted: detection, and collateral, because a system
    that flags six things when one number changes is noisy rather than sensitive.
    """
    from cvv.extract import extract
    from cvv.gather import gather
    from cvv.ingest import read
    from cvv.providers import OllamaProvider

    document = read(CV)
    graph, _ = extract(document, provider=OllamaProvider(), graph_id="cg_eval")
    evidence = gather(graph, bundle_id="eb_eval")

    _, outcomes = run(graph, evidence)
    applied = [o for o in outcomes if o.skipped is None]
    missed = [o.mutation_id for o in applied if not o.caught]
    collateral = {o.mutation_id: o.collateral for o in applied if o.collateral}

    assert not missed, f"undetected: {missed}"
    assert not collateral, f"collateral findings: {collateral}"
