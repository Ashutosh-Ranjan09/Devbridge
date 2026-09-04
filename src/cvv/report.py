"""Findings to the five buckets, and the buckets to a terminal.

The bucket a finding lands in is derived from its rule's tier, mechanically. There is
no per-rule branching here and there must never be, because that is the only thing
stopping a judgement being presented as a fact.

There is deliberately no overall score.
"""

from __future__ import annotations

import datetime

from cvv.models import (
    Buckets,
    ClaimGraph,
    EvidenceBundle,
    FindingsReport,
    RuleStatus,
    Tier,
)
from cvv.rules import REGISTRY, Context, run_all

# Named explicitly so a reader never infers that an unmentioned thing was checked.
OUT_OF_SCOPE = [
    "Degree and CGPA — only the awarding institution can confirm these. Not checked.",
    "Employment history — not verifiable without the employer.",
    "Identity — the system cannot confirm a person exists and does not try.",
    "Entrance-exam rank (JEE) — deliberately excluded: cutoffs vary by reservation "
    "category, and a category-blind comparison would flag valid ranks.",
]


def assemble(
    graph: ClaimGraph, bundle: EvidenceBundle, *, report_id: str = "fr_001"
) -> FindingsReport:
    ctx = Context(graph=graph, bundle=bundle, report_id=report_id)
    findings, outcomes = run_all(ctx)
    by_id = {r.rule_id: r for r in REGISTRY}

    verified: list[str] = []
    contradicted: list[str] = []
    needs_context: list[str] = []
    not_evaluated: list[str] = []

    for outcome in outcomes:
        rule = by_id[outcome.rule_id]
        if outcome.status is RuleStatus.CLEAN and rule.tier is Tier.DECISIVE:
            verified.append(f"{rule.summary} — checked, no discrepancy")
        elif outcome.status in (RuleStatus.ABSTAINED, RuleStatus.ERROR):
            not_evaluated.append(f"{rule.summary} — not evaluated: {outcome.reason}")

    for f in findings:
        # Tier decides the bucket. Nothing else does.
        if f.tier is Tier.DECISIVE:
            contradicted.append(f.finding_id)
        elif f.tier is Tier.ATTENTION:
            needs_context.append(f.finding_id)

    for gap in bundle.gaps:
        if gap.detail:
            not_evaluated.append(f"{gap.source} — {gap.detail}")

    return FindingsReport(
        report_id=report_id,
        graph_id=graph.graph_id,
        discrepancies=findings,
        rule_outcomes=outcomes,
        buckets=Buckets(
            verified=verified,
            # Capped at five, ranked by confidence: a reviewer gives a report about
            # sixty seconds, and this is a design constraint rather than a preference.
            contradicted=sorted(
                contradicted,
                key=lambda fid: -next(f.confidence for f in findings if f.finding_id == fid),
            )[:5],
            needs_context=needs_context,
            not_evaluated=not_evaluated,
            out_of_scope=OUT_OF_SCOPE,
        ),
        evaluated_at=datetime.datetime.now(datetime.UTC),
    )


def render(report: FindingsReport, graph: ClaimGraph, bundle: EvidenceBundle) -> str:
    """What the CLI prints."""
    findings = {f.finding_id: f for f in report.discrepancies}
    out: list[str] = []
    w = 78

    def head(char: str, title: str = "") -> None:
        out.append(f"\n{title}\n{char * w}" if title else char * w)

    head("=")
    out.append("  CV VERIFICATION REPORT")
    out.append(f"  document {graph.source.document_id}   ·   {len(graph.claims)} claims extracted")
    out.append(f"  model {graph.extraction_meta.model_id}   ·   "
               f"{graph.extraction_meta.span_failures} claims dropped at grounding")
    head("=")

    head("-", "✓ VERIFIED")
    if report.buckets.verified:
        out.extend(f"    {v}" for v in report.buckets.verified)
    else:
        out.append("    (nothing)")

    head("-", "✗ CONTRADICTED")
    if report.buckets.contradicted:
        for fid in report.buckets.contradicted:
            f = findings[fid]
            out.append(f"    [{f.rule_id}] {f.explanation}")
            for c in graph.claims:
                if c.claim_id in f.claim_refs:
                    out.append(f"          source: {c.provenance.verbatim[:66]!r}")
    else:
        out.append("    (nothing)")

    head("-", "? NEEDS CONTEXT")
    if report.buckets.needs_context:
        for fid in report.buckets.needs_context:
            f = findings[fid]
            out.append(f"    [{f.rule_id}] {f.explanation}")
            out.append(f"          benign reading: {f.innocent_explanation}")
    else:
        out.append("    (nothing)")

    head("-", "\u2013 NOT EVALUATED")
    out.extend(f"    {n}" for n in report.buckets.not_evaluated)

    head("-", "□ OUT OF SCOPE")
    out.extend(f"    {o}" for o in report.buckets.out_of_scope)

    head("=")
    out.append("  No overall score is produced, by design. This report states what was")
    out.append("  checked, what was not, and why. A person decides what it means.")
    head("=")
    return "\n".join(out)
