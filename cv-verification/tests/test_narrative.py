"""The second LLM site, and the checks that make it safe to have one.

Every test here uses a fake provider. The point is not what a model says — it is what
happens to what it says, and that is pure Python.
"""

from __future__ import annotations

from typing import Any

import pytest

from cvv.models import (
    Buckets,
    Discrepancy,
    FindingsReport,
    Severity,
    Tier,
)
from cvv.narrative import Narrative, facts, narrate, summarise
from tests.test_rules import NOW


class FakeProvider:
    """Returns whatever it was handed, and records the prompt it was given."""

    model_id = "fake"

    def __init__(self, answer: dict[str, Any] | Exception) -> None:
        self.answer = answer
        self.prompt = ""

    def complete_json(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.prompt = prompt
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def finding(rule_id: str, tier: Tier, explanation: str, **params: object) -> Discrepancy:
    return Discrepancy(
        finding_id=f"fd_{rule_id.lower()}",
        rule_id=rule_id,
        rule_version="1.0",
        tier=tier,
        severity=Severity.HIGH,
        confidence=1.0,
        scoring=True,
        claim_refs=["c001"],
        evidence_refs=[],
        params=params,
        explanation=explanation,
        innocent_explanation="A rating can be a few points stale."
        if tier is Tier.ATTENTION
        else None,
    )


P1 = finding("P1", Tier.DECISIVE, "The CV claims 1495; the API reports 1180.",
             claimed=1495, actual=1180)
G5 = finding("G5", Tier.ATTENTION, "No public contributions in the claimed window.",
             contributions=0)


def report(*findings: Discrepancy) -> FindingsReport:
    return FindingsReport(
        report_id="fr_test",
        graph_id="cg_test",
        discrepancies=list(findings),
        rule_outcomes=[],
        buckets=Buckets(
            verified=["something — checked, no discrepancy"],
            contradicted=[f.finding_id for f in findings if f.tier is Tier.DECISIVE],
            needs_context=[f.finding_id for f in findings if f.tier is Tier.ATTENTION],
            not_evaluated=["codechef — no connector"],
            out_of_scope=["Degree — only the institution can confirm it."],
        ),
        evaluated_at=NOW,
    )


def points(*pairs: tuple[str, str]) -> dict[str, Any]:
    return {"points": [{"ref": r, "sentence": s} for r, s in pairs]}


class TestWhatTheModelIsShown:
    def test_a_finding_carries_no_route_back_to_the_document(self) -> None:
        """The faithfulness guarantee starts at the signature. There is no claim
        text, no document and no evidence bundle in what the model sees, so a fact
        nobody computed cannot be written."""
        seen = facts(P1)
        assert set(seen) == {"ref", "rule", "says", "details"}

    def test_the_prompt_contains_only_the_findings(self) -> None:
        provider = FakeProvider(points(("P1", "Claimed 1495 against 1180.")))
        narrate(report(P1), provider)
        assert "1180" in provider.prompt
        assert "claim_refs" not in provider.prompt
        assert "normalised_text" not in provider.prompt


class TestContainment:
    def test_a_faithful_sentence_is_used(self) -> None:
        provider = FakeProvider(points(("P1", "The CV claims 1495; the API says 1180.")))
        out = narrate(report(P1), provider)
        assert out.faithful
        assert "the API says 1180" in out.text

    def test_an_invented_number_is_rejected(self) -> None:
        """Where a fabrication does damage. "Over 200 commits" in a report about a
        person is a claim about that person and must have come from somewhere."""
        provider = FakeProvider(points(("P1", "Claimed 1495, and over 200 commits.")))
        out = narrate(report(P1), provider)
        assert not out.faithful
        assert "'200'" in (out.rejected_because or "")

    def test_a_number_from_another_finding_is_rejected(self) -> None:
        """Per finding, not per report. P1's number in a sentence about G5 is the
        "one answer pasted onto fourteen sentences" failure arriving at the other end
        of the pipeline, and a report-wide check would pass it."""
        provider = FakeProvider(
            points(("P1", "Claimed 1495 against 1180."), ("G5", "Quiet, and 1495 rated."))
        )
        out = narrate(report(P1, G5), provider)
        assert not out.faithful
        assert "1495" in (out.rejected_because or "")

    def test_a_citation_to_a_rule_that_did_not_fire_is_rejected(self) -> None:
        provider = FakeProvider(points(("D9", "The roll number does not add up.")))
        out = narrate(report(P1), provider)
        assert not out.faithful
        assert "no finding's ref" in (out.rejected_because or "")

    def test_an_omitted_finding_is_rejected(self) -> None:
        """The failure that forced this design. Asked for free prose about four
        attention findings, a real model opened with "the CV does not contradict any
        rules, as all claimed information is verified" — a verdict, in a system whose
        first principle is that it produces none, and every numeral in it was legal
        because there were none."""
        provider = FakeProvider(points(("P1", "Claimed 1495 against 1180.")))
        out = narrate(report(P1, G5), provider)
        assert not out.faithful
        assert "G5" in (out.rejected_because or "")

    def test_a_rule_firing_twice_gets_a_sentence_per_finding(self) -> None:
        """Version 2 keyed sentences by rule id, so the second P2 overwrote the
        first, one finding never got a sentence, and the narrative was rejected for
        omission on every report where any rule fired twice."""
        first = finding("P2", Tier.ATTENTION, "Rank 1106 claimed, 1109 recorded.")
        second = finding("P2", Tier.ATTENTION, "Rank 532 claimed, 540 recorded.")
        second = second.model_copy(update={"finding_id": "fd_p2_b"})
        provider = FakeProvider(points(
            ("P2#1", "Claimed 1106 against 1109."), ("P2#2", "Claimed 532 against 540."),
        ))
        out = narrate(report(first, second), provider)
        assert out.faithful, out.rejected_because
        assert '"ref": "P2#1"' in provider.prompt and '"ref": "P2#2"' in provider.prompt
        assert "Claimed 1106 against 1109." in out.text
        assert "Claimed 532 against 540." in out.text

    def test_one_sentence_for_a_rule_that_fired_twice_is_an_omission(self) -> None:
        first = finding("P2", Tier.ATTENTION, "Rank 1106 claimed, 1109 recorded.")
        second = finding("P2", Tier.ATTENTION, "Rank 532 claimed, 540 recorded.")
        second = second.model_copy(update={"finding_id": "fd_p2_b"})
        provider = FakeProvider(points(("P2#1", "Claimed 1106 against 1109.")))
        out = narrate(report(first, second), provider)
        assert not out.faithful
        assert "P2#2" in (out.rejected_because or "")

    def test_a_model_outage_never_fails_the_report(self) -> None:
        out = narrate(report(P1), FakeProvider(RuntimeError("connection refused")))
        assert not out.faithful
        assert "connection refused" in (out.rejected_because or "")
        assert "P1" in out.text, "the deterministic summary still carries the finding"


class TestTheFramePythonWrites:
    def test_counts_and_ordering_are_never_the_models(self) -> None:
        provider = FakeProvider(
            points(("P1", "Claimed 1495 against 1180."), ("G5", "A quiet window."))
        )
        out = narrate(report(P1, G5), provider)
        assert out.text.startswith("1 contradicted · 1 needing context · 1 corroborated")
        assert "No score is produced" in out.text
        assert out.text.index("[P1]") < out.text.index("[G5]"), "decisive first"

    def test_the_innocent_reading_is_printed_by_python(self) -> None:
        """Guardrail 5: an attention finding is unconstructable without its benign
        reading, and a reader must see them together. Asked to include it, the real
        model copied the headline and dropped it — so this cannot depend on a model
        remembering."""
        provider = FakeProvider(points(("G5", "A quiet window.")))
        out = narrate(report(G5), provider)
        assert out.faithful
        assert "though: A rating can be a few points stale." in out.text

    def test_the_innocent_reading_reaches_the_reader_once(self) -> None:
        """The model is not shown it, so it cannot write it into the sentence as well:
        shown it, it did, and every benign reading was printed twice."""
        provider = FakeProvider(points(("G5", "A quiet window.")))
        out = narrate(report(G5), provider)
        assert "few points stale" not in provider.prompt
        assert out.text.count("A rating can be a few points stale.") == 1

    def test_no_findings_calls_no_model_and_says_what_that_means(self) -> None:
        provider = FakeProvider(RuntimeError("must not be called"))
        out = narrate(report(), provider)
        assert out.faithful
        assert "not the same as a clean CV" in out.text
        assert provider.prompt == ""

    def test_the_fallback_is_assembled_by_counting(self) -> None:
        text = summarise(report(P1, G5))
        assert "[P1]" in text and "[G5]" in text
        assert Narrative(text, faithful=False).faithful is False


class TestTheRuleIdIsNotSaidTwice:
    """The frame prints `[P2]` beside the sentence, so a model naming it again
    renders as "[P2] P2 says the CV claims...".

    Asked in the prompt not to, qwen3:1.7b did it anyway — which is guardrail 11
    landing on this system's own second model call. A prompt is not an enforcement
    mechanism, so the id is stripped by code the model cannot reach.
    """

    @pytest.mark.parametrize(
        "raw",
        ["P2 says the CV claims rank 1106.", "P2: the CV claims rank 1106.",
         "Rule P2 — the CV claims rank 1106.", "p2 states the CV claims rank 1106.",
         "P2 - the CV claims rank 1106."],
    )
    def test_a_leading_mention_is_removed(self, raw: str) -> None:
        from cvv.narrative import strip_rule_prefix

        assert strip_rule_prefix(raw, "P2") == "The CV claims rank 1106."

    def test_a_citation_in_the_body_is_left_alone(self) -> None:
        """Only a LEADING mention is a duplicate of the frame. A rule id inside the
        sentence is a citation and carries meaning."""
        from cvv.narrative import strip_rule_prefix

        body = "Ranks shift, which P2 reports as a three-place gap."
        assert strip_rule_prefix(body, "P2") == body

    def test_an_untouched_sentence_is_unchanged(self) -> None:
        from cvv.narrative import strip_rule_prefix

        plain = "The CV claims rank 1106."
        assert strip_rule_prefix(plain, "P2") == plain

    def test_it_runs_inside_narrate(self) -> None:
        provider = FakeProvider(points(("P1", "P1 says the CV claims 1495 against 1180.")))
        out = narrate(report(P1), provider)
        assert out.faithful
        assert "[P1] The CV claims 1495" in out.text
        assert "P1 says" not in out.text
