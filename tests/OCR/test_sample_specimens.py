"""Tests for the OCR specimen sampling script."""

from pathlib import Path

import pymupdf

from crlb.ocr.sample_specimens import catalogue_pages, sample_document, short_name


def test_catalogue_runs_to_end_when_last_bookmark() -> None:
    """A catalogue bookmark without a successor extends to the last page."""
    toc = [[1, "Contents", 1], [1, "CATALOGUE RAISONNE", 4]]
    assert catalogue_pages(toc, 6) == [4, 5, 6]


def test_catalogue_ends_before_next_bookmark_at_same_level() -> None:
    """Deeper bookmarks stay inside the catalogue; the next sibling ends it."""
    toc = [
        [1, "VOLUME ONE", 1],
        [2, "Catalogue Raisonné", 3],
        [3, "No. 1", 4],
        [2, "Rejected Attributions", 6],
    ]
    assert catalogue_pages(toc, 8) == [3, 4, 5]


def test_no_catalogue_bookmark_gives_no_pages() -> None:
    """Files without a catalogue bookmark yield nothing."""
    assert catalogue_pages([[1, "Introduction", 1]], 5) == []


def test_short_name() -> None:
    """The random suffix and CRLB prefix are dropped."""
    assert (
        short_name("CRLB_26_2_I_1_querylink-j2ZTGXhbVOWdKmsVUit4WHHJ.pdf")
        == "26_2_I_1_querylink"
    )


def test_sample_document_writes_specimens(tmp_path: Path) -> None:
    """Only catalogue pages with enough words are sampled and written to disk."""
    pdf_path = tmp_path / "CRLB_99_links-abc.pdf"
    doc = pymupdf.open()
    for i in range(6):
        page = doc.new_page()
        if i != 4:  # page 5 is a plate without text
            page.insert_text((50, 72), " ".join(f"word{i}_{n}" for n in range(10)))
    doc.set_toc([[1, "Introduction", 1], [1, "Catalogue", 3]])
    doc.save(pdf_path)

    out_dir = tmp_path / "out"
    rows = sample_document(
        pdf_path, "catalogue", out_dir, pages=10, seed=1, dpi=50, min_words=5
    )

    assert [r["page"] for r in rows] == [3, 4, 6]
    specimen = out_dir / "99_links_p0003"
    assert (specimen / "page.png").exists()
    assert "word2_0" in (specimen / "ocr.txt").read_text(encoding="utf-8")
    assert (specimen / "gt.txt").read_text(encoding="utf-8") == (
        specimen / "ocr.txt"
    ).read_text(encoding="utf-8")
