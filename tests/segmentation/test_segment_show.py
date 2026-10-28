"""End-to-end tests of a segmentation run and its HTML view, on a generated PDF."""

import sqlite3
from pathlib import Path

import pymupdf
import pytest

from crlb import db
from crlb.cli import main
from crlb.database.build import build
from crlb.database.manifest import DocumentRow, PartRow
from crlb.segmentation.config import load_configs
from crlb.segmentation.segment import segment
from crlb.segmentation.show import segment_text

CONFIG = """part = "XIX (4)"

[[furniture]]
label = "page_number"
top = 0.9
bottom = 1.0

[sections]
source = "bookmarks"

[heading]
pattern = '^No\\.\\s*(?P<number>\\d+)\\.'
"""


@pytest.fixture
def segmented(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    """Build a two-page catalogue with three entries, segment it and return the database path."""
    doc = pymupdf.open()
    for page_no, lines in enumerate(
        [
            ["No. 1. Augustus: Painting", "Oil on panel.", "No. 2. Tiberius: Painting"],
            ["continued text", "No. 3. Caligula: Drawing"],
        ]
    ):
        page = doc.new_page()
        for i, line in enumerate(lines):
            page.insert_text((50, 100 + 40 * i), line, fontname="helv")
        page.insert_text((280, 800), str(page_no + 10), fontname="helv")
    doc.set_toc([[1, "Catalogue", 1]])
    doc.save(tmp_path / "test.pdf")
    build(
        [DocumentRow("test.pdf", "XIX (4)", None, "main", "born_digital", None, None)],
        [PartRow("XIX (4)", None, None, None)],
        tmp_path,
        tmp_path / "out",
    )
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "defaults.toml").write_text(
        (Path("data_manifest/segmentation/defaults.toml")).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (configs / "test.toml").write_text(CONFIG, encoding="utf-8")
    conn = db.connect(tmp_path / "out" / "crlb.sqlite")
    segment(conn, load_configs(configs))
    conn.commit()
    capsys.readouterr()
    return tmp_path / "out" / "crlb.sqlite"


def test_segmentation_finds_entries_furniture_and_page_numbers(segmented: Path) -> None:
    """The three headings become entries; an entry continues past the page number; page numbers are read."""
    conn = sqlite3.connect(segmented)
    entries = conn.execute(
        "SELECT label FROM segments WHERE kind = 'entry' ORDER BY first_word_id"
    ).fetchall()
    assert [e[0] for e in entries] == ["1", "2", "3"]
    furniture = conn.execute(
        "SELECT count(*) FROM segments WHERE kind = 'furniture'"
    ).fetchone()[0]
    assert furniture == 2
    second = conn.execute(
        "SELECT first_word_id, last_word_id FROM segments WHERE kind = 'entry' AND label = '2'"
    ).fetchone()
    pages = conn.execute(
        "SELECT count(DISTINCT page_id) FROM words WHERE id BETWEEN ? AND ?", second
    ).fetchone()[0]
    assert pages == 2
    printed = conn.execute(
        "SELECT printed FROM printed_pages ORDER BY page_id"
    ).fetchall()
    assert [p[0] for p in printed] == ["10", "11"]


def test_show_writes_the_entry_with_its_pages(
    segmented: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """crlb segment show writes an HTML file with both views of the pages and the segment tree, and prints no text."""
    main(["segment", "show", str(segmented), "test.pdf", "2"])
    page = next(
        (segmented.parent / "review").glob("segment_run1_test_No2.html")
    ).read_text(encoding="utf-8")
    # Two pages, each in the fields view and the inside-the-fields view
    assert page.count("<img") == 4 and "Tiberius" in page
    assert "Tiberius" not in capsys.readouterr().out
    with pytest.raises(SystemExit, match="no entry 9"):
        main(["segment", "show", str(segmented), "test.pdf", "9"])


def test_entry_text_leaves_out_furniture(segmented: Path) -> None:
    """The text of an entry that runs over a page break does not contain the page number."""
    conn = db.connect(segmented)
    first, last = conn.execute(
        "SELECT first_word_id, last_word_id FROM segments WHERE kind = 'entry' AND label = '2'"
    ).fetchone()
    raw = [
        r[0]
        for r in conn.execute(
            "SELECT text FROM words WHERE id BETWEEN ? AND ?", (first, last)
        )
    ]
    text = [t.text for t in segment_text(conn, first, last, None, 1)]
    assert "10" in raw and "10" not in text and "continued" in text
