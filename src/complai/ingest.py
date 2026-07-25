"""Stage 1 — regulation source documents into normalised, committed text."""
from __future__ import annotations

import re
import urllib.request
from pathlib import Path

PS04_URL = (
    "https://www.cysec.gov.cy/CMSPages/GetFile.aspx"
    "?guid=2489c262-ffc6-4f64-ab57-90667c953d45"
)
SOURCES_DIR = Path("data/sources")

_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_PAGE_NUMBER = re.compile(r"\n\s*\d{1,3}\s*\n")
_MULTI_BLANK = re.compile(r"\n{3,}")
_INLINE_WS = re.compile(r"[ \t]+")

# Restore the document's own structure: numbered paragraphs (3.5.12.) and the
# lettered warning-template headings (SECTION B) each start a new block. Without
# this the whole policy statement collapses into a few unreadable walls of text,
# which costs rule-extraction quality and makes the committed artifact unreviewable.
# Both require real whitespace before the marker. A zero-width match would fire
# *inside* "3.5.12." (at the boundary before "5.12.") and split the numbering.
_PARA_MARKER = re.compile(r"\s+(?=\d{1,2}\.\d{1,2}(?:\.\d{1,2})?\.[ \t])")
_SECTION_HEADING = re.compile(r"\s+(?=SECTION [A-G]\b)")


def normalise(raw: str) -> str:
    """Repair PDF text extraction artefacts without altering wording.

    Mandated warning text is quoted verbatim in rules, so this must not
    rewrite words — only rejoin hyphenated breaks, restore paragraph
    boundaries, and collapse whitespace.
    """
    text = _HYPHEN_BREAK.sub(r"\1\2", raw)
    text = _PAGE_NUMBER.sub("\n\n", text)
    text = _SECTION_HEADING.sub("\n\n", text)
    text = _PARA_MARKER.sub("\n\n", text)
    text = _MULTI_BLANK.sub("\n\n", text)
    paragraphs = [
        _INLINE_WS.sub(" ", para.replace("\n", " ")).strip()
        for para in text.split("\n\n")
    ]
    return "\n\n".join(p for p in paragraphs if p)


def extract_pdf_text(path: Path) -> str:
    """Extract with pypdf's layout mode.

    Layout mode is not cosmetic here: the default mode inserts stray spaces
    inside words in this document's justified narrative text ("fon t size",
    "lose mo ney"), and rules quote those passages verbatim.
    """
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return normalise(
        "\n\n".join(page.extract_text(extraction_mode="layout") or "" for page in reader.pages)
    )


def fetch_pdf(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response:
        dest.write_bytes(response.read())
    return dest


def ingest_primary(dest_dir: Path = SOURCES_DIR) -> Path:
    """Fetch PS-04-2019 and write normalised text beside the PDF."""
    pdf_path = dest_dir / "PS-04-2019.pdf"
    if not pdf_path.exists():
        fetch_pdf(PS04_URL, pdf_path)
    text_path = dest_dir / "PS-04-2019.txt"
    text_path.write_text(extract_pdf_text(pdf_path), encoding="utf-8")
    return text_path
