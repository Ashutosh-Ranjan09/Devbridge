"""Document to normalised text.

The normalised string is what every character offset in the system indexes into, so
this module owns the definition of "the document". The index map lets a span be
traced back to a position in the raw text, and from there to a bounding box.
"""

from __future__ import annotations

import bisect
import datetime
import hashlib
import re
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

import pymupdf

from cvv.models import DocumentInfo, HiddenText, IngestMethod, Reading


@dataclass(frozen=True)
class Document:
    """The result of reading a file. `text` is the normalised string; `index_map[i]`
    is the offset in the raw text that normalised character `i` came from."""

    document_id: str
    sha256: str
    text: str
    index_map: list[int]
    raw: str
    pages: int
    ingest_method: IngestMethod
    producer: str | None = None
    created_at: str | None = None
    modified_at: str | None = None
    ocr_confidence: float | None = None
    # Text the file carries and a reader cannot see — not in `text`, so no model is
    # shown it and no claim grounds in it. D13 reports it.
    hidden: tuple[HiddenText, ...] = ()


def _digest(path: Path) -> str:
    """SHA-256 of the file as received — the contract's `document.sha256`."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalise(raw: str) -> tuple[str, list[int]]:
    """NFKC + whitespace collapse, carrying an index map back to `raw`.

    NFKC folds the things a PDF quietly inserts — ligatures (ﬁ -> fi), non-breaking
    spaces, full-width digits — any of which makes an exact span match fail on text a
    human would call identical. Whitespace collapse handles the line breaks PDFs put
    in the middle of a phrase.

    Both are why the map exists: after folding, offsets no longer line up with the raw
    string, and the provenance endpoint needs to point at the original.
    """
    out: list[str] = []
    imap: list[int] = []
    prev_space = False

    for i, ch in enumerate(raw):
        if ch.isspace():
            if prev_space or not out:
                continue
            out.append(" ")
            imap.append(i)
            prev_space = True
            continue

        folded = unicodedata.normalize("NFKC", ch)
        if not folded:
            continue
        prev_space = False
        for c in folded:
            out.append(c)
            imap.append(i)  # every char of an expansion points at the source char

    while out and out[-1] == " ":
        out.pop()
        imap.pop()

    return "".join(out), imap


def input_hash(text: str) -> str:
    """`ExtractionMeta.input_hash`: which text a claim graph's offsets index into. A
    reading of the same file carries the same value, so a rule can tell the two
    belong together."""
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()[:32]


@dataclass(frozen=True)
class Section:
    """A region of the document under one heading, in NORMALISED offsets."""

    heading: str
    start: int
    end: int


# A heading line: capitals, spaces and ampersands only. Excludes "B.TECH" (a dot) and
# "ASHUTOSH RANJAN | 23CS10004" (a pipe and digits), both of which are shouty but are
# not headings.
_HEADING = re.compile(r"^[A-Z][A-Z &]{3,39}$")


def sections(doc: Document) -> list[Section]:
    """Split the document by its own headings.

    Why this matters more than it looks: given the whole CV, qwen3:1.7b found one
    achievement and stamped its values onto fourteen unrelated sentences. Given the
    achievements section alone, the same model, prompt and seed got all four right.
    A smaller window is the difference between usable extraction and noise.

    Headings are detected in the RAW text, which still has line breaks, then mapped
    into normalised offsets — normalisation collapses newlines, so the structure is
    only visible before it runs.
    """
    found: list[tuple[str, int]] = []
    offset = 0
    for line in doc.raw.splitlines(keepends=True):
        stripped = line.strip()
        if _HEADING.match(stripped):
            raw_pos = offset + line.index(stripped)
            found.append((stripped, bisect.bisect_left(doc.index_map, raw_pos)))
        offset += len(line)

    if not found:
        return []

    out: list[Section] = []
    for i, (heading, start) in enumerate(found):
        end = found[i + 1][1] if i + 1 < len(found) else len(doc.text)
        out.append(Section(heading=heading, start=start, end=end))
    return out


def section_text(doc: Document, keywords: tuple[str, ...]) -> tuple[str, int]:
    """The text under any heading matching one of `keywords`, and where it starts.

    Falls back to the whole document when nothing matches — a CV without recognisable
    headings must still be processed, just with a wider window.
    """
    matched = [
        s for s in sections(doc) if any(k in s.heading for k in keywords)
    ]
    if not matched:
        return doc.text, 0
    start = min(s.start for s in matched)
    end = max(s.end for s in matched)
    return doc.text[start:end], start


def line_spans(doc: Document) -> list[tuple[int, int]]:
    """Every non-empty raw line, as normalised offsets [start, end).

    The same way back through the index map that `sections` and `line_at` take: the
    line structure exists only in `raw`, because normalisation collapses newlines.
    """
    out: list[tuple[int, int]] = []
    offset = 0
    for line in doc.raw.splitlines(keepends=True):
        stripped = line.strip()
        if stripped:
            first = offset + line.index(stripped)
            start = bisect.bisect_left(doc.index_map, first)
            end = min(bisect.bisect_left(doc.index_map, first + len(stripped)), len(doc.text))
            if end > start:
                out.append((start, end))
        offset += len(line)
    return out


def reading(doc: Document) -> Reading:
    """What the rules may know about the file beyond its claims: what was hidden in
    it, and where its lines fall."""
    return Reading(input_hash=input_hash(doc.text), hidden=list(doc.hidden), lines=line_spans(doc))


def line_at(doc: Document, offset: int) -> tuple[int, int]:
    """The normalised span of the raw line containing `offset`.

    Normalisation collapses newlines, so line structure survives only in `raw` and the
    index map is the way back to it. Used for line-level provenance: a claim about a
    single token — a skill name — should cite the line it sits on, because a span
    covering the word "C" tells a reader nothing and highlights nothing useful.
    """
    if not 0 <= offset < len(doc.index_map):
        return offset, offset
    raw_pos = doc.index_map[offset]
    start = doc.raw.rfind("\n", 0, raw_pos) + 1
    end = doc.raw.find("\n", raw_pos)
    if end == -1:
        end = len(doc.raw)

    lo = bisect.bisect_left(doc.index_map, start)
    hi = bisect.bisect_left(doc.index_map, end)
    return lo, min(hi, len(doc.text))


# The PDF date grammar, ISO 32000-1 §7.9.4: D:YYYYMMDDHHmmSS, then +, - or Z and an
# offset written HH'mm'. Declared by the file format, not by a CV, so a pattern is the
# right tool — the same reason GITHUB_REPO is one.
_PDF_DATE = re.compile(
    r"D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?"
    r"(?:(Z)(?:00'?00'?)?|([+-])(\d{2})'?(\d{2})?'?)?"
)


def pdf_date(value: str | None) -> str | None:
    """A PDF metadata date as the ISO 8601 the contract's `date-time` requires.

    `D:20250704194743+05'30'` -> `2025-07-04T19:47:43+05:30`. Version 1 passed the
    PDF string through, and M6 refused the whole report: it dates every uncorroborated
    CV claim at the document's creation, and could not read that date. Needs the day
    at least, because D4 compares days; anything unreadable is None, so D4 abstains
    rather than reading a guess. An offset the file does not state is not invented.
    """
    if not value or not (m := _PDF_DATE.fullmatch(value.strip())):
        return None
    year, month, day, hour, minute, second, utc, sign, off_h, off_m = m.groups()
    try:
        moment = datetime.datetime(
            int(year), int(month), int(day), int(hour or 0), int(minute or 0), int(second or 0)
        )
    except ValueError:
        return None
    if utc:
        return f"{moment.isoformat()}+00:00"
    if sign:
        return f"{moment.isoformat()}{sign}{off_h}:{off_m or '00'}"
    return moment.isoformat()


# --------------------------------------------------------------------------- #
# Hidden text
# --------------------------------------------------------------------------- #

# A PDF span is INVISIBLE when its box on the rendered page holds no ink: the
# lightest and darkest pixels inside it differ by less than this share of the grey
# scale. Measured on the four PDFs in docs/ and tests/fixtures/, 2,857 spans: the
# faintest visible text, a light-grey dash, sits at 0.32, while white on white, text
# under a white box, the invisible text mode and #f7f7f7 on white sit at 0.03 or
# below. Measured on the render rather than inferred from colour, because colour
# gets a dark sidebar wrong: white text on it is visible, and is kept.
INK_CONTRAST = 0.15
# Below this a span is TINY — set too small for anyone to read. The smallest real
# text in the same four documents is a 6 pt footnote.
MIN_POINTS = 4.0
# Coarse on purpose: the question is whether ink exists, not what it says.
INK_DPI = 96


def _ink(pix: Any, bbox: tuple[float, float, float, float], scale: float) -> float:
    """Contrast inside a box on a greyscale render: 0 is flat, 1 is black on white."""
    x0, y0, x1, y1 = bbox
    left, right = max(int(x0 * scale), 0), min(int(x1 * scale) + 1, pix.width)
    top, bottom = max(int(y0 * scale), 0), min(int(y1 * scale) + 1, pix.height)
    samples, stride = pix.samples, pix.stride
    lo, hi = 255, 0
    for y in range(top, bottom):
        row = samples[y * stride + left : y * stride + right]
        if row:
            lo, hi = min(lo, min(row)), max(hi, max(row))
    return (hi - lo) / 255 if hi >= lo else 0.0


def _visible_page(page: Any, number: int) -> tuple[str, list[HiddenText]]:
    """The page's text with its hidden spans left out — otherwise exactly
    `page.get_text()`.

    Rebuilt span by span, which is what `get_text()` does too: on all 41 pages of the
    PDFs in docs/ the two strings are identical when nothing is hidden, and a test
    holds that, because every character offset in the system indexes into this.
    """
    pix = page.get_pixmap(dpi=INK_DPI, colorspace=pymupdf.csGRAY)
    scale = INK_DPI / 72
    out: list[str] = []
    hidden: list[HiddenText] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):  # an image block has none
            kept: list[str] = []
            for span in line["spans"]:
                text = span["text"]
                reason: Literal["invisible", "tiny"] | None = None
                if text.strip():  # whitespace has no ink to find
                    if _ink(pix, span["bbox"], scale) < INK_CONTRAST:
                        reason = "invisible"
                    elif span["size"] < MIN_POINTS:
                        reason = "tiny"
                if reason:
                    hidden.append(HiddenText(page=number, reason=reason, text=text,
                                             size=round(float(span["size"]), 1)))
                else:
                    kept.append(text)
            out.append("".join(kept) + "\n")
    return "".join(out), hidden


def read_pdf(path: Path) -> Document:
    """PyMuPDF, one page at a time so page boundaries stay visible."""
    # pymupdf.open IS Document.__init__ and ships no type information, so mypy
    # resolves it against OUR Document and calls it neither callable nor iterable.
    # Scoped to this one line rather than relaxing the setting for the module.
    pdf: Any = pymupdf.open(path)  # type: ignore[no-untyped-call]
    pages: list[str] = []
    hidden: list[HiddenText] = []
    for number, page in enumerate(pdf, start=1):
        visible, found = _visible_page(page, number)
        pages.append(visible)
        hidden.extend(found)
    raw = "\n".join(pages)
    text, imap = normalise(raw)
    meta = pdf.metadata or {}

    return Document(
        document_id="doc_" + _digest(path)[:12],
        sha256=_digest(path),
        text=text,
        index_map=imap,
        raw=raw,
        pages=len(pdf),
        ingest_method=IngestMethod.PDF_TEXT,
        # An institutional generator is itself a provenance signal — rule D4.
        producer=meta.get("producer") or None,
        created_at=pdf_date(meta.get("creationDate")),
        modified_at=pdf_date(meta.get("modDate")),
        hidden=tuple(hidden),
    )


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_UNSHADED = {None, "auto", "FFFFFF"}


def _fill(element: Any, path: str) -> bool:
    """Does this element set a background fill other than white?"""
    return any(
        shd.get(f"{{{_W}}}fill") not in _UNSHADED
        for shd in element.xpath(path)
    )


def _docx_hidden(run: Any, paragraph: Any, backed: bool) -> Literal["invisible", "tiny"] | None:
    """Why a Word run cannot be seen, or None.

    Word does not render here, so this reads formatting, and stays on the side of
    saying nothing. A run marked hidden is invisible; one set below MIN_POINTS is tiny;
    white text is invisible only where nothing behind it — the run, its paragraph,
    its cell, a table style, the page — could be a colour it shows against.
    """
    styles = [s.font for s in (run.style, paragraph.style) if s is not None]
    if run.font.hidden or any(f.hidden for f in styles):
        return "invisible"
    size = run.font.size or next((f.size for f in styles if f.size), None)
    if size is not None and size.pt < MIN_POINTS:
        return "tiny"
    color = run.font.color
    white = color.type is not None and (
        str(color.rgb) == "FFFFFF" or (color.theme_color is not None and color.theme_color.name in ("BACKGROUND_1", "LIGHT_1"))
    )
    if white and not backed and not _fill(run._r, "./w:rPr/w:shd") and not run._r.xpath("./w:rPr/w:highlight"):
        return "invisible"
    return None


def _visible_paragraph(paragraph: Any, backed: bool, hidden: list[HiddenText]) -> str:
    """`paragraph.text` with hidden runs left out: runs and the runs inside
    hyperlinks, in order — the same elements python-docx joins for `.text`."""
    out: list[str] = []
    for item in paragraph.iter_inner_content():
        for run in item.runs if hasattr(item, "runs") else [item]:
            reason = _docx_hidden(run, paragraph, backed or _fill(paragraph._p, "./w:pPr/w:shd"))
            if reason and run.text.strip():
                size = run.font.size
                hidden.append(HiddenText(page=1, reason=reason, text=run.text,
                                         size=round(size.pt, 1) if size else None))
            else:
                out.append(run.text)
    return "".join(out)


def read_docx(path: Path) -> Document:
    """python-docx, walking the body in document ORDER.

    `Document.paragraphs` silently omits every table, and a CV in a two-column table
    layout — which is most templates that are not LaTeX — then reads as a handful of
    headings with no content under them. Worse, it fails quietly: you get a document,
    it grounds, and half the claims never existed to be extracted. So the body's XML
    children are walked directly and tables are flattened in place, keeping the
    reading order the author wrote.

    DOCX carries no pagination — a page is decided by the renderer, at render time —
    so `pages` is 1 and that is a property of the format, not a measurement.
    """
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    file = docx.Document(str(path))
    lines: list[str] = []
    hidden: list[HiddenText] = []
    # A page colour makes white text possibly visible anywhere in the document.
    paged = any(b.get(f"{{{_W}}}color") not in _UNSHADED for b in file.element.xpath("./w:background"))

    for child in file.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            lines.append(_visible_paragraph(Paragraph(child, file), paged, hidden))
        elif tag == "tbl":
            # A table style can shade its cells, and is not resolved here.
            styled = bool(child.xpath("./w:tblPr/w:tblStyle"))
            for row in Table(child, file).rows:
                # Tab-joined, not newline-joined: a table row is one line of a CV,
                # and splitting it would break `line_at` provenance for skills.
                cells = [
                    "\n".join(
                        _visible_paragraph(p, paged or styled or _fill(c._tc, "./w:tcPr/w:shd"), hidden)
                        for p in c.paragraphs
                    ).strip().replace("\n", " ")
                    for c in row.cells
                ]
                lines.append("\t".join(c for c in cells if c))

    raw = "\n".join(lines)
    text, imap = normalise(raw)
    core = file.core_properties

    return Document(
        document_id="doc_" + _digest(path)[:12],
        sha256=_digest(path),
        text=text,
        index_map=imap,
        raw=raw,
        pages=1,  # DOCX has no pagination; the renderer decides
        ingest_method=IngestMethod.DOCX,
        producer=core.author or None,
        created_at=core.created.isoformat() if core.created else None,
        modified_at=core.modified.isoformat() if core.modified else None,
        # A merged cell is visited once per column it spans; report each run once.
        hidden=tuple({(h.reason, h.text): h for h in hidden}.values()),
    )


# A page with less text than this almost certainly did not have its text extracted —
# a scan, or a PDF whose text layer is images. Not zero: a scanned page often carries
# a few stray characters from a header stamp or a form field.
TEXT_LAYER_FLOOR = 120


def read_scanned_pdf(path: Path, *, dpi: int = 200) -> Document:
    """OCR, for a PDF whose pages are pictures of a CV.

    Opt-in — `pip install 'cvv[ocr]'` — because the model weights are around 100 MB
    and most CVs never need them. The import failure is caught and re-raised with
    that instruction rather than surfacing as a bare ModuleNotFoundError.

    `ocr_confidence` is recorded and travels to the report header. This is the one
    ingest path whose output is a GUESS, and a reviewer looking at a finding built on
    a span recovered from OCR text needs to know the text itself was inferred.

    **Word boundaries are the weak point, not characters.** Measured on the reference
    CV rasterised at 150 dpi: 3,910 characters at 0.981 mean confidence, and inside
    that, `ASHUTOSHRANJAN`, `IITKharagpur`, `KrishnaPublicSchool`. Detection boxes do
    not always preserve the spaces between words. Grounding still holds — a claim's
    verbatim is recovered from this same string, so it is self-consistent — but every
    check that matches text against a REFERENCE table degrades: `department_matches`
    looks for "computer science" and `_same_org` for "iit kharagpur", and neither
    survives the spaces going missing. Those rules abstain rather than contradict,
    which is the correct failure, but the coverage cost is real and belongs in the
    report rather than in a comment.
    """
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on the extra
        raise NotImplementedError(
            "This document has no text layer and needs OCR, which is an optional "
            "extra: install it with `uv sync --extra ocr`. It is not a default "
            "dependency because the model weights are ~100 MB and most CVs are text."
        ) from exc

    engine = RapidOCR()
    pdf: Any = pymupdf.open(path)  # type: ignore[no-untyped-call]
    lines: list[str] = []
    scores: list[float] = []

    for page in pdf:
        pixmap = page.get_pixmap(dpi=dpi)
        result, _ = engine(pixmap.tobytes("png"))
        for box in result or []:
            # (box, text, confidence) — the geometry is dropped here; spans index the
            # normalised string, and OCR geometry is not the PDF's own coordinates.
            lines.append(str(box[1]))
            scores.append(float(box[2]))

    raw = "\n".join(lines)
    text, imap = normalise(raw)

    return Document(
        document_id="doc_" + _digest(path)[:12],
        sha256=_digest(path),
        text=text,
        index_map=imap,
        raw=raw,
        pages=len(pdf),
        ingest_method=IngestMethod.OCR,
        ocr_confidence=round(sum(scores) / len(scores), 3) if scores else None,
    )


def document_info(doc: Document) -> DocumentInfo:
    """The file's own provenance, for D4."""
    return DocumentInfo(
        document_id=doc.document_id,
        sha256=doc.sha256,
        pages=doc.pages,
        ingest_method=doc.ingest_method,
        ocr_confidence=doc.ocr_confidence,
        producer=doc.producer,
        created_at=doc.created_at,
        modified_at=doc.modified_at,
    )


def read(path: Path) -> Document:
    """Dispatch on extension, and on whether a PDF actually carries text."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        document = read_pdf(path)
        # A PDF with no text layer is a scan. Returning it as an empty document would
        # produce a report full of abstentions with no reason a reader could act on —
        # "nothing was claimed" reads as a clean CV rather than as an unread file.
        if len(document.text) < TEXT_LAYER_FLOOR * document.pages:
            # OCR reads only what is visible; what was hidden in the text layer is
            # still worth reporting.
            return replace(read_scanned_pdf(path), hidden=document.hidden)
        return document
    if suffix == ".docx":
        return read_docx(path)
    if suffix == ".doc":
        raise NotImplementedError(
            "Legacy .doc is a different, binary format that python-docx cannot read. "
            "Convert it to .docx or PDF first — guessing at it would produce a "
            "document that grounds cleanly and is missing half its content."
        )
    raise NotImplementedError(
        f"{suffix} not supported — .pdf and .docx are. A scanned PDF is read by OCR "
        "automatically (uv sync --extra ocr). A document that cannot be read fails "
        "fast rather than being guessed at."
    )
