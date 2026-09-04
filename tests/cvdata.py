"""Fixtures built from the real CV the spike ran against.

The verbatims below are copied from a genuine CDC-template CV. That matters: every
filter in the system exists because a real model failed on one of these exact strings,
and a synthetic test string would not reproduce the failure.
"""

from __future__ import annotations

import datetime

from cvv.models import (
    Claim,
    ClaimGraph,
    ClaimKind,
    ExtractionMeta,
    Recovery,
    SourceInfo,
    SpanProvenance,
)

# The achievements section, verbatim.
ACHIEVEMENTS = (
    "AWARDS AND ACHIEVEMENTS "
    "• Secured an All India Rank of 873 in JEE Advanced 2023, placing in the top 0.5% "
    "among 1,80,000+ eligible candidates across the nation "
    "• Attained an All India Rank of 809 in JEE Main 2023, ranking in the top 0.07% "
    "among 1,110,000+ registered participants across India "
    "• Achieved a peak Codeforces rating of 1495 (Specialist) through consistent "
    "problem-solving and contest participation (handle: AR009) "
    "• Reached a peak CodeChef rating of 1733 (3-Star) by competing in rated contests "
    "and improving problem-solving skills (handle: ar009) "
    "• Ranked 1106 globally in Codeforces Round 998 (Div. 3), placing in the top 3% "
    "among 38,000+ competitve programmers worldwide "
    "• Solved 500+ problems on platforms like LeetCode, Codeforces, and GeeksforGeeks, "
    "demonstrating a diverse problem-solving skillset"
)

CF_RATING = "Achieved a peak Codeforces rating of 1495 (Specialist)"
CC_RATING = "Reached a peak CodeChef rating of 1733 (3-Star)"
# The full sentences, as the pipeline grounds them — these carry the handles.
CF_RATING_FULL = (
    "Achieved a peak Codeforces rating of 1495 (Specialist) through consistent "
    "problem-solving and contest participation (handle: AR009)"
)
CC_RATING_FULL = (
    "Reached a peak CodeChef rating of 1733 (3-Star) by competing in rated contests "
    "and improving problem-solving skills (handle: ar009)"
)
CF_RANK = "Ranked 1106 globally in Codeforces Round 998 (Div. 3)"
AGGREGATE = "Solved 500+ problems on platforms like LeetCode, Codeforces, and GeeksforGeeks"
JEE = "Secured an All India Rank of 873 in JEE Advanced 2023"
SKILLS_LINE = (
    "Programming Languages : Proficient - C | C++ Intermediate - Python | CSS | HTML | "
    "JavaScript Familiar - TypeScript | Bash | Gawk"
)


DOCUMENT = ACHIEVEMENTS + " " + SKILLS_LINE


def make_claim(
    verbatim: str,
    document: str,
    *,
    kind: ClaimKind = ClaimKind.ACHIEVEMENT,
    claim_id: str = "c001",
    **fields: object,
) -> Claim:
    """A claim whose span genuinely indexes `document` — anything else would be
    rejected by the ClaimGraph validator, which is the point."""
    start = document.index(verbatim)
    return Claim(
        claim_id=claim_id,
        kind=kind,
        provenance=SpanProvenance(
            char_start=start,
            char_end=start + len(verbatim),
            verbatim=verbatim,
            recovery=Recovery.EXACT,
        ),
        **fields,  # type: ignore[arg-type]
    )


def make_graph(claims: list[Claim], document: str, *, graph_id: str = "cg_test") -> ClaimGraph:
    return ClaimGraph(
        graph_id=graph_id,
        source=SourceInfo(document_id="doc_test", normalised_text=document),
        claims=claims,
        extraction_meta=ExtractionMeta(
            model_id="test",
            prompt_version="test/v1",
            input_hash="sha256:test",
            extracted_at=datetime.datetime.now(datetime.UTC),
        ),
    )
