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

import pymupdf

from cvv.models import IngestMethod


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


def read_pdf(path: Path) -> Document:
    """PyMuPDF, one page at a time so page boundaries stay visible."""
    doc = pymupdf.open(path)
    raw = "\n".join(page.get_text() for page in doc)
    text, imap = normalise(raw)
    meta = doc.metadata or {}

    return Document(
        document_id="doc_" + hashlib.sha256(path.read_bytes()).hexdigest()[:12],
        text=text,
        index_map=imap,
        raw=raw,
        pages=len(doc),
        ingest_method=IngestMethod.PDF_TEXT,
        # An institutional generator is itself a provenance signal — rule D4.
        producer=meta.get("producer") or None,
        created_at=meta.get("creationDate") or None,
        modified_at=meta.get("modDate") or None,
    )


def read(path: Path) -> Document:
    """Dispatch on extension. DOCX and OCR land in phase 2."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return read_pdf(path)
    raise NotImplementedError(
        f"{suffix} not supported yet — phase 2 adds python-docx and rapidocr. "
        "A document that cannot be read fails fast rather than being guessed at."
    )
