"""The M6 projection.

The schema's own description is what these tests are really about: *"M6 does NOT
consume discrepancies — it has no interest in fraud. It consumes corroborated
capability signals."* So most of what a verification produces is deliberately
withheld, and the tests that matter are the ones checking WHAT is left out and
whether the batch says so.

The last test validates real output against `evidence-event.schema.json` itself,
because a projection that pydantic accepts and the contract rejects is worse than
no projection.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import jsonschema
import pytest

from cvv.events import SKILL_GRAPH, project, skill
from cvv.models import (
    Artefact,
    ArtefactType,
    ClaimKind,
    DeploymentEvidence,
    Direction,
    EventKind,
    Ownership,
    SuppressionReason,
)
from tests.cvdata import CF_RATING, DOCUMENT, SKILLS_LINE, make_claim, make_graph
from tests.test_rules import NOW, bundle, codeforces, github, repo

SCHEMA = Path("../schemas/evidence-event.schema.json")


def emitted(graph, evidence, report, *, consent: bool = True):
    return project(
        graph,
        evidence,
        report,
        verification_id="vr_test",
        subject_ref="subject:test",
        consent_scope=[SKILL_GRAPH] if consent else [],
    )


def empty_report(graph):
    from cvv.report import assemble

    return assemble(graph, bundle(graph), report_id="fr_test")


class TestConsent:
    """The schema says M6 must refuse events whose scope does not cover skill-graph
    inclusion. This system holds no consent record, so it asserts none."""

    def test_nothing_is_emitted_without_consent(self) -> None:
        graph = make_graph([], DOCUMENT)
        batch = emitted(graph, bundle(graph), empty_report(graph), consent=False)
        assert batch.events == []
        assert batch.consent_scope == []

    def test_the_batch_still_says_what_was_withheld(self) -> None:
        """An empty batch with no explanation looks like a verification that found
        nothing. A receiver that can see WHY can ask for consent."""
        graph = make_graph([], DOCUMENT)
        batch = emitted(graph, bundle(graph), empty_report(graph), consent=False)
        assert batch.not_emitted[0].reason is SuppressionReason.CONSENT_SCOPE_EXCLUDED

    def test_the_subject_reference_is_never_derived_from_the_cv(self) -> None:
        """Minting an id for a person out of their name or roll number would make
        them linkable across verifications they never connected."""
        graph = make_graph([], DOCUMENT)
        batch = emitted(graph, bundle(graph), empty_report(graph))
        assert batch.subject_ref == "subject:test"
        assert "23CS10004" not in batch.model_dump_json()


class TestTheOwnershipAsymmetry:
    """The schema's own rule: events from claimed_unverified identities may be
    negative at full reliability but are capped when positive."""

    def graph_and_evidence(self):
        graph = make_graph([], DOCUMENT)
        gh = github(repos=(repo("cf-connect", languages=("TypeScript", "CSS")),))
        return graph, bundle(graph, github=gh)

    def test_corroboration_from_an_unproven_account_is_capped(self) -> None:
        graph, evidence = self.graph_and_evidence()
        assert evidence.github is not None
        assert evidence.github.ownership is Ownership.CLAIMED_UNVERIFIED

        event = next(
            e for e in emitted(graph, evidence, empty_report(graph)).events
            if e.kind is EventKind.REPO_ARTIFACT
        )
        assert event.direction is Direction.POSITIVE
        assert event.reliability < 0.75, "the base for a repo artefact"
        assert [f.factor for f in event.reliability_factors] == ["ownership_unverified"]

    def test_every_multiplier_is_named_rather_than_baked_in(self) -> None:
        """A capped value has to be auditable instead of magic — the schema requires
        the factor, the value and a reason."""
        graph, evidence = self.graph_and_evidence()
        event = next(
            e for e in emitted(graph, evidence, empty_report(graph)).events
            if e.reliability_factors
        )
        factor = event.reliability_factors[0]
        assert 0.0 <= factor.value <= 1.0
        assert len(factor.reason) > 40, "a reason a reader can act on"


class TestWhatIsWithheld:
    def test_a_non_scoring_finding_never_becomes_an_event(self) -> None:
        """D2, D3, D11 and the rest describe the extraction, the document or a
        career's shape. None is a capability signal."""
        graph = make_graph([], DOCUMENT)
        report = empty_report(graph)
        batch = emitted(graph, bundle(graph), report)
        reasons = {w.reason for w in batch.not_emitted}
        assert SuppressionReason.NON_SCORING_RULE in reasons or not report.discrepancies

    def test_an_institutional_disclaimer_scopes_the_whole_document(self) -> None:
        """A CDC footer saying "could not verify" is the issuer's own caveat.
        Forwarding those claims as capability signals would launder it."""
        marker = make_claim(
            "Self declared by the student, CDC could not verify the relevant documents",
            DOCUMENT, claim_id="cdecl1", kind=ClaimKind.DECLARATION_MARKER,
        )
        graph = make_graph([marker], DOCUMENT)
        batch = emitted(graph, bundle(graph), empty_report(graph))
        assert SuppressionReason.INSTITUTION_DISCLAIMED in {w.reason for w in batch.not_emitted}

    def test_an_event_with_no_skills_is_withheld_not_invented(self) -> None:
        project_claim = make_claim(
            CF_RATING, DOCUMENT, claim_id="cprj01", kind=ClaimKind.PROJECT, title="X",
            skill_refs=[],  # the model named no technology
            artefacts=[Artefact(type=ArtefactType.DEPLOYMENT, url="https://x.example")],
        )
        graph = make_graph([project_claim], DOCUMENT)
        evidence = bundle(
            graph,
            deployments=[DeploymentEvidence(url="https://x.example", reachable=True, status_code=200)],
        )
        batch = emitted(graph, evidence, empty_report(graph))
        assert not [e for e in batch.events if e.kind is EventKind.ARTIFACT_LIVE]
        assert SuppressionReason.NO_SKILL_MAPPING in {w.reason for w in batch.not_emitted}


class TestSkillIdentifiers:
    def test_a_surface_form_is_never_passed_off_as_canonical(self) -> None:
        """`skill_id` is meant to be ESCO-seeded and there is no resolver here.
        The namespace says so in the identifier, and the relevance says it again."""
        ref = skill("Next.js")
        assert ref.skill_id.startswith("surface:")
        assert ref.relevance < 1.0

    @pytest.mark.parametrize(
        ("name", "expected"),
        [("Next.js", "surface:next.js"), ("C++", "surface:c++"), ("C#", "surface:c#"),
         ("Tailwind CSS", "surface:tailwind-css")],
    )
    def test_the_characters_that_distinguish_languages_survive(
        self, name: str, expected: str
    ) -> None:
        """Stripping `+` and `#` collapses C, C++ and C# onto each other."""
        assert skill(name).skill_id == expected


class TestSelfReportedSkills:
    def test_a_cv_claim_is_weak_and_says_why(self) -> None:
        """Self-reported, and undated — a CV dates a job, never a skill. M6's decay
        kernel would otherwise read it as having happened today."""
        claim = make_claim(
            SKILLS_LINE, DOCUMENT, claim_id="cskl01", kind=ClaimKind.SKILL,
            skill_refs=["c", "c++", "python"],
        )
        graph = make_graph([claim], DOCUMENT)
        event = next(
            e for e in emitted(graph, bundle(graph), empty_report(graph)).events
            if e.kind is EventKind.CV_CLAIM
        )
        assert event.reliability < 0.25
        assert "undated_observation" in [f.factor for f in event.reliability_factors]


class TestPlatformRatings:
    def rating_event(self, *, dated: bool):
        graph = make_graph([], DOCUMENT)
        cf = codeforces()
        if dated:
            cf = cf.model_copy(update={
                "contests": [c.model_copy(update={"date": datetime.date(2025, 1, 21)})
                             for c in cf.contests]
            })
        else:
            cf = cf.model_copy(update={"contests": []})
        return next(
            e for e in emitted(graph, bundle(graph, platforms=[cf]), empty_report(graph)).events
            if e.kind is EventKind.PLATFORM_RATING
        )

    def test_a_dated_rating_from_an_authoritative_api_is_the_strongest_signal(self) -> None:
        """Nothing caps it. The handle resolved on the platform's own API, so account
        ownership is not in question the way it is for a repository."""
        event = self.rating_event(dated=True)
        assert event.reliability >= 0.85
        assert event.reliability_factors == []

    def test_the_date_is_when_the_contest_happened(self) -> None:
        """`occurred_at` is when the activity happened, not when it was observed —
        that is what M6's decay kernel reads."""
        event = self.rating_event(dated=True)
        assert event.occurred_at.date() == datetime.date(2025, 1, 21)
        assert event.occurred_at < NOW

    def test_a_peak_with_no_contest_history_is_capped_and_says_so(self) -> None:
        """A peak rating is a fact as of NOW, but the peak was reached at some point
        nobody recorded. Dating it today would tell the decay kernel this ability was
        demonstrated this morning."""
        event = self.rating_event(dated=False)
        assert event.reliability < 0.85
        assert [f.factor for f in event.reliability_factors] == ["undated_observation"]


@pytest.mark.skipif(not SCHEMA.is_file(), reason="the contract schema is not present")
class TestAgainstTheContract:
    """A projection pydantic accepts and the schema rejects is worse than none."""

    def batch_json(self, *, consent: bool) -> dict:
        claim = make_claim(
            SKILLS_LINE, DOCUMENT, claim_id="cskl01", kind=ClaimKind.SKILL,
            skill_refs=["python", "rust"],
        )
        graph = make_graph([claim], DOCUMENT)
        gh = github(repos=(repo("x", languages=("Python",)),))
        evidence = bundle(graph, github=gh, platforms=[codeforces()])
        batch = emitted(graph, evidence, empty_report(graph), consent=consent)
        return json.loads(batch.model_dump_json())

    def test_a_populated_batch_validates(self) -> None:
        schema = json.loads(SCHEMA.read_text())
        payload = self.batch_json(consent=True)
        assert payload["events"], "this fixture must produce events to be worth validating"
        jsonschema.validate(payload, schema)

    def test_an_empty_withheld_batch_validates_too(self) -> None:
        jsonschema.validate(self.batch_json(consent=False), json.loads(SCHEMA.read_text()))
