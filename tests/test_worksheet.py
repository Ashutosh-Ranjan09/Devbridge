"""What a person still has to do, prepared.

The worksheet's whole value is that it invents nothing — every line traces to a claim
or a finding that already exists. These tests are mostly about what it must NOT say.
"""

from __future__ import annotations

import datetime

from cvv.models import (
    Artefact,
    ArtefactType,
    Buckets,
    ClaimKind,
    Discrepancy,
    FindingsReport,
    RuleOutcome,
    RuleStatus,
    Severity,
    Tier,
)
from cvv.reference import institution_contact
from cvv.worksheet import render_worksheet, worksheet
from tests.cvdata import CF_RATING, DOCUMENT, ROLL, make_claim, make_graph
from tests.test_rules import degree, role

NOW = datetime.datetime(2026, 9, 4, tzinfo=datetime.UTC)


def finding(rule_id: str, *, scoring: bool, explanation: str) -> Discrepancy:
    return Discrepancy(
        finding_id=f"fd_{rule_id.lower()}",
        rule_id=rule_id,
        rule_version="1.0",
        tier=Tier.ATTENTION,
        severity=Severity.LOW,
        confidence=0.5,
        scoring=scoring,
        claim_refs=[],
        evidence_refs=[],
        params={},
        explanation=explanation,
        innocent_explanation="There is an ordinary reason for this.",
    )


def report(*findings: Discrepancy, outcomes: list[RuleOutcome] | None = None) -> FindingsReport:
    return FindingsReport(
        report_id="fr_test",
        graph_id="cg_test",
        discrepancies=list(findings),
        rule_outcomes=outcomes or [],
        buckets=Buckets(
            verified=[],
            contradicted=[],
            needs_context=[],
            not_evaluated=[],
            out_of_scope=["Degree — only the institution can confirm it."],
        ),
        evaluated_at=NOW,
    )


class TestWhatNeverBecomesAQuestion:
    def test_a_non_scoring_finding_is_never_put_to_the_candidate(self) -> None:
        """`scoring` is the filter, and it is exactly the right one. A non-scoring
        finding describes the extraction, the document, a career's shape or a naming
        habit — never a claim the candidate made. The first version asked them how
        two of nineteen proposed claims came to be dropped by our extractor."""
        graph = make_graph([], DOCUMENT)
        rep = report(
            finding("D2", scoring=False, explanation="2 of 19 claims were dropped."),
            finding("D3", scoring=False, explanation="The document disclaims itself."),
            finding("P2", scoring=True, explanation="Claimed 1106, the API records 1109."),
        )
        asks = [t.ask for t in worksheet(graph, rep)]
        assert any("1106" in a for a in asks)
        assert not any("dropped" in a for a in asks)
        assert not any("disclaims" in a for a in asks)

    def test_a_gap_in_a_career_is_never_a_question(self) -> None:
        """D11 is non-scoring because a gap can be illness, caregiving or a visa. It
        must not arrive at the candidate as something to account for."""
        graph = make_graph([], DOCUMENT)
        rep = report(finding("D11", scoring=False, explanation="730 days separate two roles."))
        assert worksheet(graph, rep) == []

    def test_no_contact_is_invented_for_an_unknown_institution(self) -> None:
        """A guessed registrar address sends a candidate's details to a stranger."""
        assert institution_contact("Somewhere University") is None
        graph = make_graph([degree("B.Tech", "IIT Kharagpur", "2027")], DOCUMENT)
        task = worksheet(graph, report())[0]
        assert task.of == "IIT Kharagpur — academic / examinations section"


class TestWhatItPrepares:
    def test_the_roll_number_arrives_decoded(self) -> None:
        """D9 already parsed it. A reviewer phoning the institution should not have
        to decode 23CS10004 themselves."""
        roll = make_claim(
            ROLL, DOCUMENT, claim_id="cid001", kind=ClaimKind.IDENTIFIER,
            parsed={"admission_year": 2023, "dept_code": "CS", "serial": 10004},
        )
        graph = make_graph([roll, degree("B.Tech", "IIT Kharagpur", "2027")], DOCUMENT)
        context = " ".join(worksheet(graph, report())[0].context)
        assert "admission year 2023" in context and "department code CS" in context

    def test_a_completion_year_is_not_rendered_as_an_open_range(self) -> None:
        """The CDC template prints the completion year in a leading column. "from
        2027 to ongoing" told a reviewer something the CV never said."""
        graph = make_graph([degree("B.Tech", "IIT Kharagpur", "2027")], DOCUMENT)
        ask = worksheet(graph, report())[0].ask
        assert "the CV states 2027" in ask
        assert "ongoing" not in ask

    def test_an_employer_task_carries_what_the_machine_already_found(self) -> None:
        """So the reviewer does not redo work the connectors already did."""
        graph = make_graph([role("Vercel", "2024")], DOCUMENT)
        note = "Employer corroborated — 'Vercel' matches the GitHub organisation 'vercel'"
        rep = report(outcomes=[
            RuleOutcome(rule_id="G11", status=RuleStatus.CLEAN, note=note)
        ])
        task = next(t for t in worksheet(graph, rep) if t.of == "Vercel")
        assert note in task.context
        assert "never confirms a job" in task.why

    def test_the_ownership_challenge_is_concrete(self) -> None:
        profile = make_claim(
            "github.com/Ashutosh-Ranjan09/ATMA-Final", DOCUMENT + " github.com/Ashutosh-Ranjan09/ATMA-Final",
            claim_id="cpr001", kind=ClaimKind.PROFILE, platform="github",
            handle="Ashutosh-Ranjan09",
        )
        doc = DOCUMENT + " github.com/Ashutosh-Ranjan09/ATMA-Final"
        graph = make_graph([profile], doc)
        rep = report(outcomes=[
            RuleOutcome(rule_id="G3", status=RuleStatus.FIRED)
        ])
        task = next(t for t in worksheet(graph, rep) if t.task_id == "MC-ownership")
        assert "github.com/Ashutosh-Ranjan09" in task.ask
        assert "declining to do it is not a mark against anyone" in task.why

    def test_a_deployment_task_names_the_host_not_a_url_slice(self) -> None:
        project = make_claim(
            CF_RATING, DOCUMENT, claim_id="cprj01", kind=ClaimKind.PROJECT, title="ATMA",
            artefacts=[Artefact(type=ArtefactType.DEPLOYMENT, url="https://atma-ar.vercel.app")],
        )
        graph = make_graph([project], DOCUMENT)
        task = next(t for t in worksheet(graph, report()) if t.section == "Open and look")
        assert task.task_id == "MC-atma-ar.vercel.app"
        assert "W2" in task.why


class TestTheRendering:
    def test_it_says_plainly_that_nothing_in_it_is_a_finding(self) -> None:
        graph = make_graph([degree("B.Tech", "IIT Kharagpur", "2027")], DOCUMENT)
        text = render_worksheet(graph, report())
        assert "Nothing above is a finding" in text

    def test_the_judgement_calls_are_always_listed_with_their_reason(self) -> None:
        """H1-H3 and H6 exist whether or not this CV produced any task at all — a
        reviewer must never be able to read the worksheet as the whole job."""
        text = render_worksheet(make_graph([], DOCUMENT), report())
        for marker in ("H1", "H2", "H3", "H6", "encoding them encodes bias"):
            assert marker in text

    def test_a_clean_document_still_produces_the_judgement_section(self) -> None:
        text = render_worksheet(make_graph([], DOCUMENT), report())
        assert "0 task(s)" in text
        assert "The hiring decision" in text
