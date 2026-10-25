"""docs/design.html -> docs/design.pdf, with the fonts the page actually uses.

    uv run python scripts/render-pdf.py

Two things make this more than a `--print-to-pdf` one-liner, and both cost a
debugging round:

**Google serves IBM Plex Sans as a VARIABLE font, and headless Chrome will not embed
one.** It falls back to Noto Sans silently — the PDF renders, nobody is warned, and
the body text is simply the wrong face. Spectral and IBM Plex Mono are served as
static instances and embed fine, which is what made the failure look random. The fix
is to drop that one family from the stylesheet request and inline a static WOFF of it
instead; requesting the CSS with an old Safari user agent is what gets a static file
rather than the variable one.

**The sticky 212px rail would leave an empty gutter on every page after the first.**
Print collapses to the single-column layout the page already defines for narrow
viewports, so the contents list appears once at the top — which is what a PDF should
open with anyway.
"""

from __future__ import annotations

import base64
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/design.html"
TARGET = ROOT / "docs/design.pdf"

# Old enough that Google Fonts serves a static WOFF rather than a variable WOFF2.
STATIC_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_6_8) AppleWebKit/534.30 "
    "(KHTML, like Gecko) Version/5.1 Safari/534.30"
)
VARIABLE_FAMILY = "IBM+Plex+Sans"
WEIGHTS = (400, 500, 600)

PRINT_CSS = """
html{color-scheme:light}
body{margin:0;font:14px system-ui,sans-serif;background:#faf9f7}
img{max-width:100%}
[hidden]{display:none!important}
@page{size:A4;margin:14mm 13mm}
@media print{
  .shell{grid-template-columns:1fr!important;gap:0!important;max-width:none!important;padding:0!important}
  .rail{position:static!important;max-height:none!important;padding:0 0 18px!important;
    border-bottom:1px solid var(--rule);break-after:avoid}
  .rail ol{columns:2;column-gap:24px;margin-bottom:0!important}
  .rail a{border-left:0!important;padding-left:0!important}
  .masthead-in{max-width:none!important;padding:0 0 26px!important}
  main{padding:22px 0 0!important}
  body{background:#fff!important}
  /* Nothing that reads as one object may be split across a page. */
  pre,table,.pair,.bk,.note,blockquote,.fig{break-inside:avoid}
  tr{break-inside:avoid}
  h2.sec,h3,.stage>h3{break-after:avoid}
  p,li{orphans:3;widows:3}
  a{text-decoration:none}
}
"""


def static_faces() -> str:
    """The variable family, fetched as static WOFF and inlined as data URIs."""
    faces = []
    with httpx.Client(headers={"User-Agent": STATIC_UA}, follow_redirects=True) as client:
        for weight in WEIGHTS:
            css = client.get(
                "https://fonts.googleapis.com/css",
                params={"family": f"{VARIABLE_FAMILY.replace('+', ' ')}:{weight}"},
            ).text
            url = css.split("url(")[1].split(")")[0].strip("'\"")
            payload = base64.b64encode(client.get(url).content).decode()
            faces.append(
                "@font-face{font-family:'IBM Plex Sans';font-style:normal;"
                f"font-weight:{weight};font-display:block;"
                f"src:url(data:font/woff;base64,{payload}) format('woff')}}"
            )
    return "\n".join(faces)


def main() -> int:
    if not SOURCE.is_file():
        print(f"no such file: {SOURCE}", file=sys.stderr)
        return 2

    page = SOURCE.read_text()
    # Leave Spectral and Plex Mono on the Google request — both are static and embed.
    page = page.replace(f"&family={VARIABLE_FAMILY}:wght@400;500;600", "")

    document = (
        '<!doctype html>\n<html lang="en" data-theme="light">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<style>{PRINT_CSS}</style>\n<style>\n{static_faces()}\n</style>\n"
        f"</head>\n<body>\n{page}\n</body>\n</html>\n"
    )

    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "print.html"
        source.write_text(document)
        subprocess.run(
            [
                "google-chrome", "--headless=new", "--disable-gpu", "--no-sandbox",
                "--no-pdf-header-footer", "--virtual-time-budget=45000",
                f"--print-to-pdf={TARGET}", source.as_uri(),
            ],
            check=True,
            capture_output=True,
        )

    import pymupdf

    with pymupdf.open(TARGET) as pdf:
        embedded = {f[3].split("+")[-1] for page_ in pdf for f in page_.get_fonts()}
        print(f"{TARGET.relative_to(ROOT)}  ·  {len(pdf)} pages  ·  {TARGET.stat().st_size // 1024} KB")
        print("  fonts:", ", ".join(sorted(embedded)))
        if not any("PlexSans" in name for name in embedded):
            print("  WARNING: IBM Plex Sans did not embed — the body text is a fallback.")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
