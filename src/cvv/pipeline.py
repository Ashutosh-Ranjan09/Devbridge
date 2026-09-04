"""extract -> gather -> evaluate. The whole verification, in one function."""

from __future__ import annotations

from pathlib import Path

from cvv.extract import extract
from cvv.gather import gather
from cvv.ingest import read
from cvv.models import ClaimGraph, EvidenceBundle, FindingsReport
from cvv.providers import LLMProvider
from cvv.report import assemble


def verify(
    path: Path, *, provider: LLMProvider | None = None
) -> tuple[ClaimGraph, EvidenceBundle, FindingsReport]:
    doc = read(path)
    graph, _ = extract(doc, provider=provider, graph_id=f"cg_{doc.document_id[4:]}")
    bundle = gather(graph, bundle_id=f"eb_{doc.document_id[4:]}")
    report = assemble(graph, bundle, report_id=f"fr_{doc.document_id[4:]}")
    return graph, bundle, report
