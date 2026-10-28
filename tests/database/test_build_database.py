"""Tests for building the text database from generated PDFs."""

import hashlib
import sqlite3
from pathlib import Path

import pymupdf
import pytest

from crlb import db
from crlb.cli import main
from crlb.database.build import text_source_of

MAIN = "pdfs/CRLB_19_4_links RKD Research.pdf"


@pytest.fixture
def built(corpus: Path, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    """Build the fixture corpus and return a connection with pdfs.sqlite attached."""
    monkeypatch.chdir(corpus)
    main(["build", "data_manifest/documents.csv", "out"])
    conn = db.connect(corpus / "out" / "crlb.sqlite")
    db.attach_pdfs(conn, corpus / "out" / "pdfs.sqlite")
    return conn


def main_id(conn: sqlite3.Connection) -> int:
    """Return the id of the main fixture document."""
    return conn.execute("SELECT id FROM documents WHERE path = ?", (MAIN,)).fetchone()[
        0
    ]


def words_of(conn: sqlite3.Connection, page_index: int = 0) -> dict[str, sqlite3.Row]:
    """Return the words of a page of the main document by text."""
    rows = conn.execute(
        "SELECT w.* FROM words w JOIN pages p ON p.id = w.page_id"
        " WHERE p.document_id = ? AND p.page_index = ?",
        (main_id(conn), page_index),
    )
    return {row["text"]: row for row in rows}


def test_pdf_is_stored_with_original_bytes_and_hash(
    corpus: Path, built: sqlite3.Connection
) -> None:
    """The sqlar row holds the original bytes (a path with spaces works) and the hash matches."""
    original = (corpus / MAIN).read_bytes()
    stored, sz = built.execute(
        "SELECT data, sz FROM pdfs.sqlar WHERE name = ?", (MAIN,)
    ).fetchone()
    assert stored == original and sz == len(original)
    sha256 = built.execute(
        "SELECT sha256 FROM documents WHERE path = ?", (MAIN,)
    ).fetchone()[0]
    assert sha256 == hashlib.sha256(original).hexdigest()


def test_counts_match_the_generated_pdf(built: sqlite3.Connection) -> None:
    """Pages, words, links and bookmarks are all stored."""
    doc_id = main_id(built)

    def count(sql: str) -> int:
        """Return the single value of a query on the main document."""
        return built.execute(sql, (doc_id,)).fetchone()[0]

    assert count("SELECT page_count FROM documents WHERE id = ?") == 3
    assert count("SELECT count(*) FROM pages WHERE document_id = ?") == 3
    assert (
        count(
            "SELECT count(*) FROM words JOIN pages p ON p.id = page_id WHERE document_id = ?"
        )
        == 8
    )
    assert count("SELECT count(*) FROM toc WHERE document_id = ?") == 2
    links = built.execute(
        "SELECT kind, uri, target_page FROM links JOIN pages p ON p.id = page_id"
        " WHERE document_id = ? ORDER BY kind",
        (doc_id,),
    ).fetchall()
    assert [tuple(link) for link in links] == [
        ("goto", None, 0),
        ("uri", "https://rkd.nl/images/12345", None),
    ]


def test_document_metadata_and_page_fields(built: sqlite3.Connection) -> None:
    """Manifest fields, PDF metadata, bookmarks and page labels are stored as expected."""
    doc = built.execute(
        "SELECT * FROM documents WHERE id = ?", (main_id(built),)
    ).fetchone()
    assert (doc["part"], doc["section"], doc["text_source"]) == (
        "XIX (4)",
        "main",
        "born_digital",
    )
    assert doc["creator"] == "Adobe InDesign CC 2015" and doc["title"] == "Test"
    toc = built.execute(
        "SELECT level, title, page_index FROM toc WHERE document_id = ? ORDER BY position",
        (doc["id"],),
    ).fetchall()
    assert [tuple(t) for t in toc][:2] == [(1, "Introduction", 0), (2, "Catalogue", 1)]
    labels = built.execute(
        "SELECT page_label FROM pages WHERE document_id = ? ORDER BY page_index",
        (doc["id"],),
    )
    assert [row[0] for row in labels] == ["5", "6", "7"]
    assert built.execute("SELECT * FROM parts").fetchone()["authors"] == "A; B"


def test_word_coordinates_match_pymupdf(
    corpus: Path, built: sqlite3.Connection
) -> None:
    """Word boxes equal those of page.get_text('words') on the original file."""
    expected = {w[4]: w[:4] for w in pymupdf.open(corpus / MAIN)[0].get_text("words")}
    stored = {
        text: (r["x0"], r["y0"], r["x1"], r["y1"])
        for text, r in words_of(built).items()
    }
    assert stored.keys() == expected.keys()
    for text, box in expected.items():
        assert stored[text] == pytest.approx(box)


def test_typography_per_word(built: sqlite3.Connection) -> None:
    """Bold, italic and superscript are recorded, and a word with two styles has styles = 2."""
    words = words_of(built)
    assert words["Plain"]["flags"] & 16 == 0 and words["Plain"]["styles"] == 1
    assert words["Bold"]["flags"] & 16 and words["Bold"]["font"].endswith("Bold")
    assert words["Italic"]["flags"] & 2
    note = words["note12"]
    assert (
        note["styles"] == 2 and note["flags"] & 1 == 0
    )  # most characters are not superscript


def test_soft_hyphen_is_kept(built: sqlite3.Connection) -> None:
    """Soft hyphens stay unchanged in the words and the page text."""
    assert "soft\xadhyphen" in words_of(built)
    page_text = built.execute(
        "SELECT text FROM pages WHERE document_id = ? AND page_index = 0",
        (main_id(built),),
    ).fetchone()[0]
    assert "soft\xadhyphen" in page_text


def test_excerpt_of_is_resolved(built: sqlite3.Connection) -> None:
    """The index excerpt refers to the id of its main document."""
    excerpt_of = built.execute(
        "SELECT excerpt_of FROM documents WHERE section = 'index'"
    ).fetchone()[0]
    assert excerpt_of == main_id(built)


def test_full_text_search_finds_the_page(built: sqlite3.Connection) -> None:
    """An FTS query finds a word on the right page."""
    hits = built.execute(
        "SELECT p.document_id, p.page_index FROM pages_fts JOIN pages p ON p.id = pages_fts.rowid"
        " WHERE pages_fts MATCH 'searchterm'"
    ).fetchall()
    assert len(hits) == 2 and {tuple(h)[1] for h in hits} == {0}


def test_build_run_records_provenance(built: sqlite3.Connection) -> None:
    """The build run stores the tool version and the extraction options."""
    run = built.execute("SELECT * FROM build_runs").fetchone()
    assert run["tool"] == "pymupdf" and pymupdf.__version__ in run["tool_version"]
    assert '"sort": false' in run["options"]


def test_open_pdf_checks_the_hash(built: sqlite3.Connection) -> None:
    """open_pdf returns the stored document, and raises once the stored bytes differ."""
    assert db.open_pdf(built, main_id(built)).page_count == 3
    built.execute(
        "UPDATE pdfs.sqlar SET data = CAST(data || x'00' AS BLOB) WHERE name = ?",
        (MAIN,),
    )
    with pytest.raises(ValueError, match="does not match"):
        db.open_pdf(built, main_id(built))


def test_build_refuses_existing_output(corpus: Path, built: sqlite3.Connection) -> None:
    """A second build into the same directory is refused."""
    with pytest.raises(SystemExit, match="already exists"):
        main(["build", "data_manifest/documents.csv", "out"])


def test_build_refuses_invalid_manifest(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Manifest problems stop the build before anything is written."""
    monkeypatch.chdir(corpus)
    (corpus / "data_manifest" / "parts.csv").write_text(
        "part,title,year,authors\n", encoding="utf-8"
    )
    with pytest.raises(SystemExit, match="not in parts.csv"):
        main(["build", "data_manifest/documents.csv", "out"])
    assert not (corpus / "out").exists()


def test_text_source_from_metadata() -> None:
    """ABBYY and repaired Paperless files are OCR, InDesign files are born-digital."""
    assert (
        text_source_of({"producer": "ABBYY FineReader 11", "creator": "Paperless"})
        == "ocr"
    )
    assert (
        text_source_of({"producer": "3-Heights(TM) PDF", "creator": "Paperless"})
        == "ocr"
    )
    assert text_source_of({"producer": "", "creator": ""}) == "ocr"
    assert (
        text_source_of(
            {"producer": "Adobe PDF Library", "creator": "Adobe InDesign CC"}
        )
        == "born_digital"
    )
    assert text_source_of({"producer": "Other", "creator": "Other"}) is None
