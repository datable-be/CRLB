"""Small generated PDFs and manifests for the step 1 tests."""

import csv
from collections.abc import Callable
from pathlib import Path

import pymupdf
import pytest

from crlb.database.manifest import (
    DOCUMENT_FIELDS,
    PART_FIELDS,
    DocumentRow,
    read_documents,
)

URI = "https://rkd.nl/images/12345"


def make_pdf(path: Path, creator: str = "Adobe InDesign CC 2015") -> None:
    """Write a 3-page PDF with styled words, a soft hyphen, a URI and a GoTo link, bookmarks and page labels."""
    doc = pymupdf.open()
    first = doc.new_page()
    first.insert_htmlbox(
        pymupdf.Rect(50, 50, 500, 100),
        "<p>Plain <b>Bold</b> <i>Italic</i> note<sup>12</sup></p>",
    )
    # A TrueType font keeps the soft hyphen as U+00AD in the text layer
    first.insert_font(fontname="SoftHyphenFont", fontbuffer=pymupdf.Font("tiro").buffer)
    first.insert_text((50, 200), "soft\xadhyphen searchterm", fontname="SoftHyphenFont")
    first.insert_link(
        {"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(50, 190, 150, 205), "uri": URI}
    )
    second = doc.new_page()
    second.insert_text((50, 100), "Second page", fontname="helv")
    second.insert_link(
        {"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(50, 90, 150, 105), "page": 0}
    )
    doc.new_page()
    doc.set_toc([[1, "Introduction", 1], [2, "Catalogue", 2]])
    doc.set_page_labels(
        [{"startpage": 0, "prefix": "", "style": "D", "firstpagenum": 5}]
    )
    doc.set_metadata(
        {"producer": "Adobe PDF Library 15.0", "creator": creator, "title": "Test"}
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    """Write a manifest CSV."""
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def document(path: str, part: str = "XIX (4)", **fields: str) -> dict:
    """Return a documents.csv row with defaults for a born-digital main file."""
    return {
        "path": path,
        "part": part,
        "section": "main",
        "text_source": "born_digital",
    } | fields


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    """Create a root with a main PDF (with a space in its name), an index excerpt and both manifests."""
    make_pdf(tmp_path / "pdfs" / "CRLB_19_4_links RKD Research.pdf")
    make_pdf(tmp_path / "pdfs" / "CRLB_19_4_index.pdf")
    manifest = tmp_path / "data_manifest"
    manifest.mkdir()
    write_csv(
        manifest / "documents.csv",
        DOCUMENT_FIELDS,
        [
            document("pdfs/CRLB_19_4_links RKD Research.pdf"),
            document(
                "pdfs/CRLB_19_4_index.pdf",
                section="index",
                excerpt_of="pdfs/CRLB_19_4_links RKD Research.pdf",
            ),
        ],
    )
    write_csv(
        manifest / "parts.csv",
        PART_FIELDS,
        [{"part": "XIX (4)", "title": "Portraits", "year": "2016", "authors": "A; B"}],
    )
    return tmp_path


@pytest.fixture
def write_documents(tmp_path: Path) -> Callable[..., list[DocumentRow]]:
    """Return a function that writes documents.csv rows (paths with keyword overrides) and reads them back."""

    def write(*rows: dict) -> list[DocumentRow]:
        """Write the rows, completed with defaults, and read the manifest back."""
        path = tmp_path / "documents.csv"
        write_csv(path, DOCUMENT_FIELDS, [document(**row) for row in rows])
        return read_documents(path)

    return write
