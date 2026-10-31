"""What a shared file really is, from its bytes.

The name and the browser's claimed type are not believed: an HTML page renamed .pdf is
still HTML, and served inline it would run in the site's origin. Only four types are
accepted, each recognised by its own signature; anything else is refused. The web serves
every file as a download besides, so even a file that slipped past is never rendered.
"""

from __future__ import annotations

import io
import zipfile

PDF = "application/pdf"
PNG = "image/png"
JPEG = "image/jpeg"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ACCEPTED = "PDF, PNG, JPG or DOCX"


def sniff(data: bytes) -> str | None:
    if data.startswith(b"%PDF-"):
        return PDF
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG
    if data.startswith(b"PK\x03\x04"):
        # Any zip starts like this; a Word document is a zip holding these two parts.
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = set(z.namelist())
        except zipfile.BadZipFile:
            return None
        if {"[Content_Types].xml", "word/document.xml"} <= names:
            return DOCX
    return None


def clean_name(name: str) -> str:
    """A name to show, nothing more (the file is stored under its id): no path, no control
    characters, at most 120 characters."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in base if ch.isprintable()).strip()
    return base[:120] or "file"
