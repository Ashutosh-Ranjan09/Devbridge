"""Span recovery — the guardrail everything else depends on.

The model returns a `verbatim`: the stretch of CV text it says a claim came from.
This module verifies that text really is in the document and returns where. If it is
not, the claim is dropped and `span_failures` increments.

Without this, a model that reads "rating of 1495" and returns 1595 produces a decisive
contradiction against a claim the CV never made — an accusation manufactured entirely
by the extractor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from cvv.ingest import normalise
from cvv.models import Recovery

FUZZY_THRESHOLD = 0.92
# Slack around a pass's section, for a claim that straddles a heading boundary.
WINDOW_MARGIN = 64

_NUMERALS = re.compile(r"\d+")


@dataclass(frozen=True)
class Span:
    char_start: int
    char_end: int
    recovery: Recovery
    score: float = 1.0

    @property
    def text_slice(self) -> slice:
        return slice(self.char_start, self.char_end)


def numerals_present(verbatim: str, text: str) -> bool:
    """Every digit sequence in the verbatim must occur in the document.

    This is the guard on the fuzzy tier, and it is not optional. Measured against a
    real CV: a hallucinated "rating of 1800" where the document says 1495 scores
    0.944 on partial_ratio and sails through a bare 0.92 threshold — three characters
    out of fifty-three. Similarity is blind to precisely the character that matters,
    and numbers are where the decisive checks live: ratings, ranks, problem counts,
    roll numbers, years.
    """
    return all(n in text for n in _NUMERALS.findall(verbatim))


def recover_span(
    verbatim: str,
    text: str,
    *,
    threshold: float = FUZZY_THRESHOLD,
    window: tuple[int, int] | None = None,
) -> Span | None:
    """Locate `verbatim` in `text`. Returns None when it is not there.

    Two tiers. Exact wins outright. Fuzzy catches the near-misses a model produces
    when it drops a bullet character or re-spaces a phrase — but only with every
    numeral verified present.

    `window` scopes the search to the section the claim was extracted from, so a
    phrase occurring in two sections resolves inside its own. Offsets returned are
    always into the full document.
    """
    query, _ = normalise(verbatim)
    if not query:
        return None

    # A margin, not a fallback. A heading can sit just outside its own section and a
    # claim can straddle a boundary, so a little slack is right — but searching the
    # WHOLE document is not. Given a 180-character education section, qwen3:1.7b
    # returned "SKILLS AND EXPERTISE" and "EXTRA CURRICULAR ACTIVITIES" as degrees;
    # a document-wide search found that text elsewhere and grounded both. Text that
    # is not in a pass's own section does not belong to that pass.
    if window is None:
        lo, hi = 0, len(text)
    else:
        lo = max(0, window[0] - WINDOW_MARGIN)
        hi = min(len(text), window[1] + WINDOW_MARGIN)
    scoped = text[lo:hi]

    start = scoped.find(query)
    if start != -1:
        return Span(lo + start, lo + start + len(query), Recovery.EXACT)

    alignment = fuzz.partial_ratio_alignment(query, scoped)
    if alignment is None:
        return None

    score = alignment.score / 100.0
    if score < threshold:
        return None
    if not numerals_present(query, scoped):
        return None  # a digit this region does not contain — reject at any score

    start, end = lo + alignment.dest_start, lo + alignment.dest_end
    if end <= start:
        return None
    return Span(start, end, Recovery.FUZZY, score)


def recover_token(token: str, text: str, *, within: Span | None = None) -> str | None:
    """Recover a token-shaped field — a handle, repo owner, credential id, roll number.

    Returns the document's own casing, or None if the token is not in the document at
    all. Never trust the model's transcription of these: it works in tokens and
    normalises, so it will return `ar-009` for `AR009`, the API 404s, and the report
    says a real account does not exist.

    `within` is the claim's own span, and passing it matters. A real CV carried both
    `handle: AR009` (Codeforces) and `handle: ar009` (CodeChef) two lines apart; a
    document-wide search returns whichever appears first, so the CodeChef handle came
    back upper-cased. Search the claim's own span first, and only fall back to the
    whole document when the token sits just outside it.

    Prose fields — org, title, degree — are exempt. The model may legitimately
    normalise those, and there is no single correct string to recover.
    """
    if not token:
        return None
    needle = token.lower()

    if within is not None:
        # No fallback to the whole document. The same hazard as the span window: a
        # token absent from the claim's own sentence gets rescued from somewhere
        # else, and comes back with that other occurrence's casing. The CV carries
        # `handle: AR009` and `handle: ar009` two lines apart, and some APIs care.
        window = text[within.text_slice]
        i = window.lower().find(needle)
        return window[i : i + len(token)] if i != -1 else None

    i = text.lower().find(needle)
    return text[i : i + len(token)] if i != -1 else None
