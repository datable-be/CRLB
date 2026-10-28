"""A small database with one born-digital and one OCR document, for the step 2 tests."""

import sqlite3
from pathlib import Path

import pymupdf
import pytest

from crlb import db
from crlb.database.build import build
from crlb.database.manifest import DocumentRow, PartRow

BORN_DIGITAL = [
    "the Museum of Antwerp",
    "Provenance: the Museum",
    "apart from a part of it",
]
OCR = ["the M useum of Antwerp", "P r o v e n a n c e", "a part of it"]


def make_pdf(path: Path, lines: list[str], producer: str, creator: str) -> None:
    """Write a one-page PDF with one text line per string."""
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate(lines):
        page.insert_text((50, 100 + 20 * i), line, fontname="helv")
    doc.set_metadata({"producer": producer, "creator": creator})
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


@pytest.fixture
def corpus_db(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> sqlite3.Connection:
    """Build crlb.sqlite from a born-digital and an OCR PDF and return a connection to it."""
    make_pdf(
        tmp_path / "bd.pdf", BORN_DIGITAL, "Adobe PDF Library", "Adobe InDesign CC"
    )
    make_pdf(tmp_path / "ocr.pdf", OCR, "ABBYY FineReader 11", "Paperless")
    documents = [
        DocumentRow("bd.pdf", "XIX (4)", None, "main", "born_digital", None, None),
        DocumentRow("ocr.pdf", "II (1)", None, "main", "ocr", None, None),
    ]
    parts = [PartRow("XIX (4)", None, None, None), PartRow("II (1)", None, None, None)]
    build(documents, parts, tmp_path, tmp_path / "out")
    capsys.readouterr()
    return db.connect(tmp_path / "out" / "crlb.sqlite")
