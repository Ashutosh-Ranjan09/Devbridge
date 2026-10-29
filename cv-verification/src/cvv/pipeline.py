"""extract -> gather -> evaluate, and the one place the contract's report is built."""

from __future__ import annotations

from pathlib import Path

from cvv import __version__
from cvv.extract import extract
from cvv.gather import gather
from cvv.ingest import document_info, read, reading
from cvv.models import (
    ClaimGraph,
    DocumentInfo,
    EvidenceBundle,
    FindingsReport,
    GapReason,
    Narrative,
    ReportProvenance,
    ReportStatus,
    SkillDecision,
    Subject,
    VerificationReport,
)
from cvv.providers import LLMProvider
from cvv.report import assemble, coverage
from cvv.rules import REGISTRY

CONTRACT_VERSION = "1.0.0"

# Transient. A source that was unreachable or throttled would have answered on a
# better day, and re-running the verification may produce more coverage.
TRANSIENT = (GapReason.UNREACHABLE, GapReason.RATE_LIMITED)


def verify(
    path: Path, *, provider: LLMProvider | None = None
) -> tuple[ClaimGraph, EvidenceBundle, FindingsReport]:
    doc = read(path)
    graph, _ = extract(doc, provider=provider, graph_id=f"cg_{doc.document_id[4:]}")
    bundle = gather(graph, bundle_id=f"eb_{doc.document_id[4:]}")
    report = assemble(
        graph,
        bundle,
        report_id=f"fr_{doc.document_id[4:]}",
        document=document_info(doc),
        reading=reading(doc),
    )
    return graph, bundle, report


def status(graph: ClaimGraph, bundle: EvidenceBundle) -> ReportStatus:
    """`completed_degraded` has to MEAN something, or every report carries it.

    Any gap at all was the first definition and it was useless: before its scraper
    existed, CodeChef was a gap on every run, so every report was degraded. A missing
    connector is a permanent property of this system, not a degradation of this run —
    and a NOT_FOUND account is a FINDING (G2), not a failure to look.

    What is left is the honest meaning: something transient stopped a check that
    could otherwise have run, so running it again may return more. That, plus an
    extraction that dropped more claims than it kept.
    """
    if graph.extraction_meta.degraded:
        return ReportStatus.COMPLETED_DEGRADED
    if any(gap.reason in TRANSIENT for gap in bundle.gaps):
        return ReportStatus.COMPLETED_DEGRADED
    return ReportStatus.COMPLETED


def default_subject(document: DocumentInfo) -> Subject:
    """A reference to the DOCUMENT, never to the person. A name or a roll number
    would make someone linkable across verifications they never connected; the
    file's own hash links only re-runs of the same file."""
    return Subject(subject_ref=f"subject:{document.document_id}")


def verification_report(
    *,
    verification_id: str,
    document: DocumentInfo,
    graph: ClaimGraph,
    bundle: EvidenceBundle,
    findings: FindingsReport,
    subject: Subject | None = None,
    narrative: Narrative | None = None,
    skill_resolution: dict[str, SkillDecision] | None = None,
) -> VerificationReport:
    """The contract's VerificationReport, from the stages that produced it.

    Built here and only here, so the CLI's file and the API's response are the same
    object — the one M6 reads. Nothing is computed that the stages did not already
    compute: status, coverage and provenance are read off them.
    """
    prompts = {"extract": graph.extraction_meta.prompt_version}
    if narrative is not None:
        prompts["narrate"] = narrative.prompt_version
    return VerificationReport(
        verification_id=verification_id,
        status=status(graph, bundle),
        subject=subject or default_subject(document),
        document=document,
        claim_graph=graph,
        evidence_bundle=bundle,
        findings=findings,
        narrative=narrative,
        coverage=coverage(findings),
        provenance=ReportProvenance(
            cvv_version=__version__,
            contract_version=CONTRACT_VERSION,
            model_id=graph.extraction_meta.model_id,
            prompt_versions=prompts,
            rule_versions={rule.rule_id: rule.rule_version for rule in REGISTRY},
        ),
        valid_as_of=findings.evaluated_at,
        skill_resolution=skill_resolution or {},
    )
