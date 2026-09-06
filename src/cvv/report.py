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
    DocumentInfo,
    EvidenceBundle,
    FindingsReport,
    IngestMethod,
    RuleStatus,
    Tier,
    VerificationCoverage,
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
    graph: ClaimGraph,
    bundle: EvidenceBundle,
    *,
    report_id: str = "fr_001",
    document: DocumentInfo | None = None,
) -> FindingsReport:
    ctx = Context(graph=graph, bundle=bundle, report_id=report_id, document=document)
    findings, outcomes = run_all(ctx)
    by_id = {r.rule_id: r for r in REGISTRY}

    verified: list[str] = []
    contradicted: list[str] = []
    needs_context: list[str] = []
    not_evaluated: list[str] = []

    for outcome in outcomes:
        rule = by_id[outcome.rule_id]
        if outcome.status is RuleStatus.CLEAN and outcome.note:
            verified.append(outcome.note)
        elif outcome.status is RuleStatus.CLEAN and rule.tier is Tier.DECISIVE:
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


def coverage(report: FindingsReport) -> VerificationCoverage:
    """How much of the catalogue actually ran.

    A composite confidence about the VERIFICATION, not about the person. A high number
    means "we checked thoroughly", never "they are good" — so it cannot become a
    hiring threshold.

    This is also where a check that ran cleanly but raised nothing becomes visible.
    The `verified` bucket holds decisive passes only, by design, so an attention rule
    coming back clean lands in no bucket at all — and silence there reads as "not
    checked" rather than "checked, nothing found", which understates the work done.
    """
    evaluated = sum(
        1
        for o in report.rule_outcomes
        if o.status in (RuleStatus.FIRED, RuleStatus.CLEAN, RuleStatus.NOT_APPLICABLE)
    )
    abstained = sum(
        1 for o in report.rule_outcomes if o.status in (RuleStatus.ABSTAINED, RuleStatus.ERROR)
    )
    total = len(report.rule_outcomes)
    return VerificationCoverage(
        rules_total=total,
        rules_evaluated=evaluated,
        rules_abstained=abstained,
        coverage=round(evaluated / total, 2) if total else 0.0,
    )


def quietly_clean(report: FindingsReport) -> list[str]:
    """Checks that ran, found nothing, and appear in no bucket.

    An attention-tier rule coming back clean is a real result — "portfolio
    composition: looked, nothing to raise" — but `verified` is decisive-only by
    design, so it would otherwise vanish. A reader must be able to tell the
    difference between a check that passed and one that never ran.
    """
    by_id = {r.rule_id: r for r in REGISTRY}
    return [
        f"{by_id[o.rule_id].summary} — checked, nothing raised"
        for o in report.rule_outcomes
        if o.status is RuleStatus.CLEAN
        and not o.note  # already printed, in full, under verified
        and o.rule_id in by_id
        and by_id[o.rule_id].tier is not Tier.DECISIVE
    ]


def render(
    report: FindingsReport,
    graph: ClaimGraph,
    bundle: EvidenceBundle,
    document: DocumentInfo | None = None,
) -> str:
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
    cov = coverage(report)
    out.append(
        f"  {cov.rules_total} checks registered   ·   {cov.rules_evaluated} evaluated"
        f"   ·   {cov.rules_abstained} could not run   ·   coverage {cov.coverage:.0%}"
    )
    out.append("  Coverage describes the VERIFICATION, not the candidate.")
    if document and document.ingest_method is IngestMethod.OCR:
        # Everything below rests on text that was INFERRED from an image. Grounding
        # still holds — a verbatim is recovered from the same string — but reference
        # matching degrades where OCR drops the spaces between words, and a reader
        # must know that before weighing an abstention.
        confidence = (
            f"{document.ocr_confidence:.0%}" if document.ocr_confidence else "unreported"
        )
        out.append("")
        out.append(f"  READ BY OCR — mean character confidence {confidence}.")
        out.append("  The text every finding below quotes was inferred from an image.")
        out.append("  Word boundaries are the weak point: checks that match against a")
        out.append("  reference table abstain more often here, and that is the correct")
        out.append("  failure rather than a contradiction.")
    head("=")

    head("-", "✓ VERIFIED")
    if report.buckets.verified:
        out.extend(f"    {v}" for v in report.buckets.verified)
    else:
        out.append("    (nothing)")
    if also := quietly_clean(report):
        out.append("")
        out.append("    also checked, nothing raised — weaker than the above, not decisive:")
        out.extend(f"      {line}" for line in also)

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
