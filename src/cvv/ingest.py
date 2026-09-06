"""Document to normalised text.

The normalised string is what every character offset in the system indexes into, so
this module owns the definition of "the document". The index map lets a span be
traced back to a position in the raw text, and from there to a bounding box.
"""

from __future__ import annotations

import bisect
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf

from cvv.models import DocumentInfo, IngestMethod


@dataclass(frozen=True)
class Document:
    """The result of reading a file. `text` is the normalised string; `index_map[i]`
    is the offset in the raw text that normalised character `i` came from."""

    document_id: str
    text: str
    index_map: list[int]
    raw: str
    pages: int
    ingest_method: IngestMethod
    producer: str | None = None
    created_at: str | None = None
    modified_at: str | None = None
    ocr_confidence: float | None = None


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


def read_pdf(path: Path) -> Document:
    """PyMuPDF, one page at a time so page boundaries stay visible."""
    # pymupdf.open IS Document.__init__ and ships no type information, so mypy
    # resolves it against OUR Document and calls it neither callable nor iterable.
    # Scoped to this one line rather than relaxing the setting for the module.
    pdf: Any = pymupdf.open(path)  # type: ignore[no-untyped-call]
    raw = "\n".join(page.get_text() for page in pdf)
    text, imap = normalise(raw)
    meta = pdf.metadata or {}

    return Document(
        document_id="doc_" + hashlib.sha256(path.read_bytes()).hexdigest()[:12],
        text=text,
        index_map=imap,
        raw=raw,
        pages=len(pdf),
        ingest_method=IngestMethod.PDF_TEXT,
        # An institutional generator is itself a provenance signal — rule D4.
        producer=meta.get("producer") or None,
        created_at=meta.get("creationDate") or None,
        modified_at=meta.get("modDate") or None,
    )


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

    for child in file.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            lines.append(Paragraph(child, file).text)
        elif tag == "tbl":
            for row in Table(child, file).rows:
                # Tab-joined, not newline-joined: a table row is one line of a CV,
                # and splitting it would break `line_at` provenance for skills.
                cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                lines.append("\t".join(c for c in cells if c))

    raw = "\n".join(lines)
    text, imap = normalise(raw)
    core = file.core_properties

    return Document(
        document_id="doc_" + hashlib.sha256(path.read_bytes()).hexdigest()[:12],
        text=text,
        index_map=imap,
        raw=raw,
        pages=1,  # DOCX has no pagination; the renderer decides
        ingest_method=IngestMethod.DOCX,
        producer=core.author or None,
        created_at=core.created.isoformat() if core.created else None,
        modified_at=core.modified.isoformat() if core.modified else None,
    )


def document_info(doc: Document) -> DocumentInfo:
    """The file's own provenance, for D4."""
    return DocumentInfo(
        document_id=doc.document_id,
        pages=doc.pages,
        ingest_method=doc.ingest_method,
        ocr_confidence=doc.ocr_confidence,
        producer=doc.producer,
        created_at=doc.created_at,
        modified_at=doc.modified_at,
    )


def read(path: Path) -> Document:
    """Dispatch on extension. OCR for scanned documents is still unbuilt."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return read_pdf(path)
    if suffix == ".docx":
        return read_docx(path)
    if suffix == ".doc":
        raise NotImplementedError(
            "Legacy .doc is a different, binary format that python-docx cannot read. "
            "Convert it to .docx or PDF first — guessing at it would produce a "
            "document that grounds cleanly and is missing half its content."
        )
    raise NotImplementedError(
        f"{suffix} not supported — .pdf and .docx are. Scanned documents need OCR, "
        "which is unbuilt. A document that cannot be read fails fast rather than "
        "being guessed at."
    )
