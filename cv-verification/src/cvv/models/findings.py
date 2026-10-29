"""What the system concluded — the FindingsReport.

There is deliberately no `overall_score` field, and there never will be. Collapsing
findings into one number turns an evidence report into an automated judgement, and it
becomes a hiring threshold within a week of shipping.
"""

from __future__ import annotations

import datetime
from typing import Any

from pydantic import Field, model_validator

from cvv.models.claims import Confidence, Frozen, Id, Model
from cvv.models.enums import RuleStatus, Section, Severity, Tier

# The `params` key for text the CANDIDATE wrote, quoted so a person can read it. The
# narrative's model is never shown it (`narrative.facts` drops the key): an
# instruction hidden in a CV, or printed in one, would otherwise reach the next model
# as input by way of the finding that reported it.
CANDIDATE_TEXT = "candidate_text"


class Discrepancy(Model):
    """One finding. `tier` is declared on the rule, not chosen here."""

    finding_id: Id
    rule_id: str  # D7 · G5 · P1 · W1
    rule_version: str
    tier: Tier
    severity: Severity
    confidence: Confidence
    # false means this finding may not move a number: no section-confidence
    # contribution, no evidence event. It is still shown to a human.
    scoring: bool
    claim_refs: list[Id]
    evidence_refs: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    explanation: str
    innocent_explanation: str | None = None

    @model_validator(mode="after")
    def _attention_needs_innocent_explanation(self) -> Discrepancy:
        """An attention finding is unconstructable without its benign reading, so a
        reviewer always sees the innocent explanation alongside the signal."""
        if self.tier is Tier.ATTENTION and not self.innocent_explanation:
            raise ValueError("tier=attention requires innocent_explanation")
        return self


class RuleOutcome(Model):
    """EVERY registered rule appears here, including the ones that did nothing."""

    rule_id: str
    rule_version: str | None = None
    status: RuleStatus
    reason: str | None = None
    # What the rule CONFIRMED. A check that positively corroborates a claim has
    # nowhere else to say it: Discrepancy means discrepancy, and a bare CLEAN
    # renders as "nothing raised", which understates "the employer's own GitHub
    # organisation lists this account publicly".
    note: str | None = None

    @model_validator(mode="after")
    def _abstain_needs_reason(self) -> RuleOutcome:
        """Abstention without a reason is exactly the silence the design forbids."""
        if self.status in (RuleStatus.ABSTAINED, RuleStatus.ERROR) and not self.reason:
            raise ValueError(f"status={self.status} requires a reason")
        return self


class SectionConfidence(Model):
    section: Section
    confidence: Confidence
    basis_finding_ids: list[Id]


class Buckets(Model):
    """The five-bucket human view, derived from tier. A recruiter gives a report about
    sixty seconds; the caps are a design constraint, not a preference."""

    verified: list[str]  # collapses to a count plus one line
    contradicted: list[Id] = Field(max_length=5)  # ranked by confidence
    needs_context: list[Id]  # 3 visible in the UI, rest behind a disclosure
    not_evaluated: list[str]  # every abstention, with its reason
    out_of_scope: list[str]  # the static exclusion list; always present


class VerificationCoverage(Model):
    """A composite confidence about the VERIFICATION, not about the person.

    A high number means "we checked thoroughly", never "they are good" — so it cannot
    become a hiring threshold. That distinction is the whole reason this exists
    separately from anything resembling a score.
    """

    rules_total: int = Field(ge=0)
    rules_evaluated: int = Field(ge=0)
    rules_abstained: int = Field(ge=0)
    coverage: Confidence
    # Optional in the contract and not computed here: C1, the only check that could
    # set attestation_depth, is out of scope, and identity is never proven without
    # OAuth or a challenge. Carried so a partner's report parses; left out of ours
    # rather than written as null, which the contract's enums do not allow.
    attestation_depth: str | None = Field(default=None, exclude_if=lambda v: v is None)
    identity_confidence: str | None = Field(default=None, exclude_if=lambda v: v is None)


class FindingsReport(Frozen):
    report_id: Id
    graph_id: Id
    discrepancies: list[Discrepancy]
    rule_outcomes: list[RuleOutcome]
    section_confidence: list[SectionConfidence] = Field(default_factory=list)
    buckets: Buckets
    evaluated_at: datetime.datetime

    @model_validator(mode="after")
    def _buckets_reference_real_findings(self) -> FindingsReport:
        """A bucket naming a finding that does not exist means the aggregator and the
        rule run disagree — which renders as a blank row and is invisible to a test
        that only counts."""
        known = {d.finding_id for d in self.discrepancies}
        for name, refs in (
            ("contradicted", self.buckets.contradicted),
            ("needs_context", self.buckets.needs_context),
        ):
            missing = [r for r in refs if r not in known]
            if missing:
                raise ValueError(f"buckets.{name} references unknown findings: {missing}")
        return self
