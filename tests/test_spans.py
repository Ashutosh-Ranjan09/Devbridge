"""Span recovery is the guardrail everything downstream depends on.

If a claim can be grounded that the document does not contain, every finding built on
it is an accusation the system manufactured by itself.
"""

from __future__ import annotations

import pytest

from cvv.ingest import normalise
from cvv.models import Recovery
from cvv.spans import numerals_present, recover_span, recover_token
from tests.cvdata import (
    CC_RATING_FULL,
    CF_RANK,
    CF_RATING,
    CF_RATING_FULL,
    DOCUMENT,
)


class TestExactTier:
    def test_finds_a_verbatim_copied_exactly(self) -> None:
        span = recover_span(CF_RATING, DOCUMENT)
        assert span is not None
        assert span.recovery is Recovery.EXACT
        assert DOCUMENT[span.text_slice] == CF_RATING

    def test_whitespace_differences_still_match_exactly(self) -> None:
        """A PDF breaks a line mid-phrase and the model re-spaces it. Normalisation
        makes both sides comparable, so this is an exact match, not a fuzzy one."""
        span = recover_span("Achieved  a  peak   Codeforces rating of 1495", DOCUMENT)
        assert span is not None
        assert span.recovery is Recovery.EXACT


class TestNumeralGuard:
    """Changing one digit barely moves a similarity score, and numbers are exactly
    where the decisive checks live."""

    @pytest.mark.parametrize("fake", [1595, 1800, 2100])
    def test_a_hallucinated_number_is_rejected_at_any_fuzzy_score(self, fake: int) -> None:
        """Measured: "rating of 1800" against a document saying 1495 scores 0.944 on
        partial_ratio and would sail through a bare 0.92 threshold."""
        verbatim = f"Achieved a peak Codeforces rating of {fake} (Specialist)"
        assert recover_span(verbatim, DOCUMENT) is None

    def test_an_invented_claim_is_rejected(self) -> None:
        assert recover_span("Software Engineer Intern at Google, Summer 2024", DOCUMENT) is None

    def test_numerals_present_checks_every_digit_run(self) -> None:
        assert numerals_present("rating of 1495", DOCUMENT)
        assert not numerals_present("rating of 1595", DOCUMENT)


class TestTokenRecovery:
    """A model works in tokens and normalises. It will return `ar-009` for `AR009`,
    the API 404s, and the report says a real account does not exist."""

    def test_the_documents_casing_wins(self) -> None:
        span = recover_span(CF_RATING_FULL, DOCUMENT)
        assert recover_token("ar009", DOCUMENT, within=span) == "AR009"

    def test_a_token_is_recovered_from_its_own_span(self) -> None:
        """The real CV carries `handle: AR009` and `handle: ar009` two lines apart.
        A document-wide search returns whichever comes first, so the CodeChef handle
        came back upper-cased."""
        cf = recover_span(CF_RATING_FULL, DOCUMENT)
        cc = recover_span(CC_RATING_FULL, DOCUMENT)
        assert recover_token("ar009", DOCUMENT, within=cf) == "AR009"
        assert recover_token("ar009", DOCUMENT, within=cc) == "ar009"

    def test_a_mangled_token_is_rejected(self) -> None:
        assert recover_token("ar-009", DOCUMENT) is None
        assert recover_token("NotInTheCV", DOCUMENT) is None


class TestWindow:
    """The window is a boundary, not a hint.

    Given a 180-character education section, qwen3:1.7b returned "SKILLS AND
    EXPERTISE" as a degree. With a document-wide fallback that text was found
    elsewhere and grounded. Text outside a pass's own section does not belong to it.
    """

    def test_text_outside_the_window_is_not_grounded(self) -> None:
        rank_at = DOCUMENT.index(CF_RANK)
        window = (0, 200)  # a section that ends long before the rank claim
        assert rank_at > 200 + 64, "test assumes the claim is outside window + margin"
        assert recover_span(CF_RANK, DOCUMENT, window=window) is None

    def test_text_inside_the_window_is_grounded(self) -> None:
        rank_at = DOCUMENT.index(CF_RANK)
        span = recover_span(CF_RANK, DOCUMENT, window=(rank_at - 10, rank_at + 200))
        assert span is not None
        assert span.char_start == rank_at


class TestNormalise:
    def test_index_map_has_one_entry_per_normalised_character(self) -> None:
        text, imap = normalise("  hello\n\n  world  ")
        assert text == "hello world"
        assert len(imap) == len(text)

    def test_ligatures_fold_and_still_map_back(self) -> None:
        """NFKC expands ﬁ to two characters; both point at the source character."""
        text, imap = normalise("ofﬁce")
        assert text == "office"
        assert imap[2] == imap[3] == 2
