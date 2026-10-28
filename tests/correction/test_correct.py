"""End-to-end tests of a correction run, the effective text and set-active."""

import sqlite3
from pathlib import Path

import pytest

from crlb import text
from crlb.cli import main
from crlb.correction.correct import correct
from crlb.correction.lexicon import build_lexicon
from crlb.correction.rules import Options
from crlb.sample import parse_sample


@pytest.fixture
def corrected_db(corpus_db: sqlite3.Connection, tmp_path: Path) -> sqlite3.Connection:
    """The test database with a lexicon and one correction run."""
    build_lexicon(corpus_db, tmp_path, ["bd.pdf"])
    correct(corpus_db, Options())
    return corpus_db


def page_id(conn: sqlite3.Connection, path: str) -> int:
    """Return the id of the first page of a document."""
    return conn.execute(
        "SELECT p.id FROM pages p JOIN documents d ON d.id = p.document_id WHERE d.path = ?",
        (path,),
    ).fetchone()[0]


def test_ocr_page_is_corrected(corrected_db: sqlite3.Connection) -> None:
    """R2 and R1 repair the OCR page (each line is a block here); the raw text stays available."""
    ocr = page_id(corrected_db, "ocr.pdf")
    assert (
        text.page_text(corrected_db, ocr, run_id=1)
        == "the Museum of Antwerp\n\nProvenance\n\na part of it"
    )
    assert text.page_text(corrected_db, ocr, raw=True).startswith("the M useum")


def test_every_word_has_one_token(corrected_db: sqlite3.Connection) -> None:
    """Every raw word is covered by exactly one corrected token of the run."""
    words = corrected_db.execute("SELECT count(*) FROM words").fetchone()[0]
    covered = corrected_db.execute(
        "SELECT sum(last_word_id - first_word_id + 1) FROM corrected_words WHERE run_id = 1"
    ).fetchone()[0]
    assert covered == words


def test_joins_and_flags_are_stored(corrected_db: sqlite3.Connection) -> None:
    """The OCR page gets one R1 and one R2 join; 'a part' is flagged, since both pieces are words."""
    rules = corrected_db.execute(
        "SELECT rule, count(*) FROM corrected_words WHERE rule IS NOT NULL GROUP BY rule"
    )
    assert dict(rules.fetchall()) == {"R1": 1, "R2": 1}
    flags = corrected_db.execute("SELECT rule, candidate FROM correction_flags")
    assert [tuple(f) for f in flags] == [("R2", "apart")]


def test_sample_limits_the_documents(
    corpus_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """With a sample, only the documents of the sampled parts are corrected."""
    build_lexicon(corpus_db, tmp_path, ["bd.pdf"])
    run_id = correct(corpus_db, Options(), parse_sample("XIX (4)"))
    pages = corpus_db.execute(
        "SELECT DISTINCT page_id FROM corrected_words WHERE run_id = ?", (run_id,)
    ).fetchall()
    assert [row[0] for row in pages] == [page_id(corpus_db, "bd.pdf")]


def test_tokens_crossing_the_range_fall_back_to_raw_words(
    corrected_db: sqlite3.Connection,
) -> None:
    """A range that cuts through a joined token gets the raw words inside the range."""
    museum = corrected_db.execute(
        "SELECT first_word_id, last_word_id FROM corrected_words WHERE rule = 'R2'"
    )
    first, last = museum.fetchone()
    assert [t.text for t in text.tokens(corrected_db, first, last, run_id=1)] == [
        "Museum"
    ]
    assert [t.text for t in text.tokens(corrected_db, last, last + 1, run_id=1)] == [
        "useum",
        "of",
    ]


def test_effective_text_needs_an_active_run(corrected_db: sqlite3.Connection) -> None:
    """Without a run id, the active correction run is used, and there must be one."""
    with pytest.raises(ValueError, match="none is active"):
        text.tokens(corrected_db, 1, 2)


def test_set_active(
    corrected_db: sqlite3.Connection, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """set-active makes an existing run active and refuses an unknown one."""
    path = str(tmp_path / "out" / "crlb.sqlite")
    main(["set-active", path, "2", "1", "--note", "test"])
    assert text.active_run(corrected_db, "2") == 1
    assert [t.text for t in text.tokens(corrected_db, 1, 1)] == ["the"]
    with pytest.raises(SystemExit, match="no run 9"):
        main(["set-active", path, "2", "9"])
    correct(corrected_db, Options())
    main(["set-active", path, "2", "latest"])
    assert text.active_run(corrected_db, "2") == 2


def test_set_active_latest_needs_a_run(
    corpus_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """'latest' is refused before any correction run exists."""
    with pytest.raises(SystemExit, match="no run in correction_runs yet"):
        main(["set-active", str(tmp_path / "out" / "crlb.sqlite"), "2", "latest"])


def test_show_writes_a_side_by_side_page(
    corrected_db: sqlite3.Connection, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """crlb correct show writes an HTML file with both texts and the joins marked, and prints no page text."""
    db_path = str(tmp_path / "out" / "crlb.sqlite")
    main(["correct", "show", db_path, "ocr.pdf", "1", "--run", "1"])
    page = next((tmp_path / "out" / "review").glob("run1_ocr_p0001.html")).read_text(
        encoding="utf-8"
    )
    assert (
        '<span class="R2" title="R2: M|useum' in page and ">Provenance</span>" in page
    )
    assert "R2 (flag)" in page
    assert "useum" not in capsys.readouterr().out
    with pytest.raises(SystemExit, match="matches 2 documents"):
        main(["correct", "show", db_path, ".pdf", "1"])
