"""Reading a document, before any model sees it.

The DOCX tests build their fixture at run time rather than committing a binary: the
thing under test is how python-docx's object model is walked, and a checked-in .docx
would hide that behind a file nobody can read in a diff.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cvv.ingest import TEXT_LAYER_FLOOR, pdf_date, read, read_docx, sections
from cvv.models import IngestMethod


def build_docx(path: Path) -> Path:
    """A CV in the shape most templates actually use: headings, and a TABLE."""
    import docx

    d = docx.Document()
    d.add_paragraph("ASHUTOSH RANJAN | 23CS10004")
    d.add_paragraph("EDUCATION")

    table = d.add_table(rows=2, cols=3)
    table.rows[0].cells[0].text = "2027"
    table.rows[0].cells[1].text = "B.Tech in Computer Science"
    table.rows[0].cells[2].text = "IIT Kharagpur"
    table.rows[1].cells[0].text = "2023"
    table.rows[1].cells[1].text = "CBSE Class XII"
    table.rows[1].cells[2].text = "Krishna Public School"

    d.add_paragraph("AWARDS AND ACHIEVEMENTS")
    d.add_paragraph("Achieved a peak Codeforces rating of 1495 (Specialist)")
    d.save(path)
    return path


@pytest.fixture
def docx_cv(tmp_path: Path) -> Path:
    return build_docx(tmp_path / "cv.docx")


class TestDocx:
    def test_table_content_is_not_silently_lost(self, docx_cv: Path) -> None:
        """`Document.paragraphs` omits every table. A CV whose education sits in a
        two-column layout — most non-LaTeX templates — would read as headings with
        nothing under them, ground cleanly, and quietly lose half its claims."""
        doc = read_docx(docx_cv)
        assert "B.Tech in Computer Science" in doc.text
        assert "IIT Kharagpur" in doc.text
        assert "Krishna Public School" in doc.text

    def test_reading_order_is_the_authors(self, docx_cv: Path) -> None:
        """Paragraphs first then tables would put EDUCATION's rows after the
        achievements heading, and every section window would be wrong."""
        t = doc_text = read_docx(docx_cv).text
        assert t.index("EDUCATION") < t.index("B.Tech") < t.index("AWARDS")
        assert doc_text.index("AWARDS") < doc_text.index("1495")

    def test_a_table_row_stays_one_line(self, docx_cv: Path) -> None:
        """`line_at` gives skills and identifiers their provenance. Splitting a row
        into three lines would cite a cell rather than the row a reader sees."""
        doc = read_docx(docx_cv)
        row = [ln for ln in doc.raw.splitlines() if "B.Tech" in ln]
        assert len(row) == 1
        assert "2027" in row[0] and "IIT Kharagpur" in row[0]

    def test_sections_are_detected_the_same_as_in_a_pdf(self, docx_cv: Path) -> None:
        headings = [s.heading for s in sections(read_docx(docx_cv))]
        assert "EDUCATION" in headings
        assert "AWARDS AND ACHIEVEMENTS" in headings

    def test_pagination_is_declared_not_measured(self, docx_cv: Path) -> None:
        """DOCX has no pages — the renderer decides at render time. 1 is a property
        of the format here, not a measurement of this file."""
        doc = read_docx(docx_cv)
        assert doc.pages == 1
        assert doc.ingest_method is IngestMethod.DOCX

    def test_dispatch_by_extension(self, docx_cv: Path) -> None:
        assert read(docx_cv).ingest_method is IngestMethod.DOCX


class TestWhatIsRefused:
    def test_legacy_doc_says_why_rather_than_guessing(self, tmp_path: Path) -> None:
        """A different, binary format. Attempting it would yield a document that
        grounds cleanly and is missing most of its content."""
        path = tmp_path / "cv.doc"
        path.write_bytes(b"\xd0\xcf\x11\xe0")
        with pytest.raises(NotImplementedError, match="Convert it"):
            read(path)

    def test_an_unknown_extension_fails_fast(self, tmp_path: Path) -> None:
        path = tmp_path / "cv.txt"
        path.write_text("hello")
        with pytest.raises(NotImplementedError, match="OCR"):
            read(path)


def rasterise(source: Path, target: Path, *, dpi: int = 150) -> Path:
    """A PDF whose pages are pictures — a scan, in every way that matters here."""
    import pymupdf

    src = pymupdf.open(source)
    out = pymupdf.open()
    for page in src:
        pix = page.get_pixmap(dpi=dpi)
        new = out.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(page.rect, stream=pix.tobytes("png"))
    out.save(target)
    return target


class TestScannedDocuments:
    """A PDF with no text layer must not come back as an empty document.

    Returning one would produce a report full of abstentions with no reason a reader
    could act on: "nothing was claimed" reads as a clean CV rather than as a file
    nobody managed to read.
    """

    def test_the_floor_allows_for_stray_marks_rather_than_demanding_zero(self) -> None:
        """A scanned page usually carries a few stray characters — a header stamp, a
        form field — so "no text layer" cannot mean literally zero."""
        assert TEXT_LAYER_FLOOR > 0

    def test_a_text_pdf_is_never_sent_to_ocr(self) -> None:
        cv = Path("docs/CV-SDE-AR.pdf")
        if not cv.is_file():
            pytest.skip("the reference CV is not present")
        assert read(cv).ingest_method is IngestMethod.PDF_TEXT

    @pytest.mark.live
    def test_a_scanned_pdf_is_read_by_ocr_and_says_so(self, tmp_path: Path) -> None:
        """Marked live because it needs the optional `ocr` extra — ~100 MB of model
        weights that a default install does not carry."""
        pytest.importorskip("rapidocr_onnxruntime")
        cv = Path("docs/CV-SDE-AR.pdf")
        if not cv.is_file():
            pytest.skip("the reference CV is not present")

        doc = read(rasterise(cv, tmp_path / "scanned.pdf"))
        assert doc.ingest_method is IngestMethod.OCR
        assert doc.ocr_confidence is not None and doc.ocr_confidence > 0.8
        assert "23CS10004" in doc.text, "the roll number must survive OCR"
        assert len(doc.text) > 1000


class TestPdfDates:
    """The contract's `document.created_at` is an ISO 8601 date-time, and M6 refuses a
    report it cannot date. A PDF writes `D:YYYYMMDDHHmmSS+HH'mm'`."""

    @pytest.mark.parametrize(
        ("raw", "iso"),
        [
            ("D:20250704194743+05'30'", "2025-07-04T19:47:43+05:30"),
            ("D:20250704194743-08'00", "2025-07-04T19:47:43-08:00"),
            ("D:20250704194743Z", "2025-07-04T19:47:43+00:00"),
            ("D:20250704194743Z00'00'", "2025-07-04T19:47:43+00:00"),
            ("D:20250704", "2025-07-04T00:00:00"),
        ],
    )
    def test_a_pdf_date_becomes_iso(self, raw: str, iso: str) -> None:
        assert pdf_date(raw) == iso

    @pytest.mark.parametrize("raw", ["D:2025", "D:20251399", "yesterday", "", None])
    def test_an_unreadable_date_is_none_not_a_guess(self, raw: str | None) -> None:
        """D4 compares days. A year alone has no day, and 2025-13-99 is not one."""
        assert pdf_date(raw) is None

    @pytest.mark.skipif(not Path("docs/CV-SDE-AR.pdf").is_file(), reason="no reference CV")
    def test_the_reference_cv_is_dated_in_iso(self) -> None:
        import datetime

        doc = read(Path("docs/CV-SDE-AR.pdf"))
        assert doc.created_at is not None
        assert datetime.datetime.fromisoformat(doc.created_at).tzinfo is not None

