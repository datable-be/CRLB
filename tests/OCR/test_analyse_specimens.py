"""Tests for the OCR specimen analysis script."""

import csv
from pathlib import Path

from analyse_specimens import analyse, compare, confusions, loosen, normalise


def test_normalise_joins_soft_hyphens_and_whitespace() -> None:
    """Soft-hyphenated line breaks are joined and whitespace is collapsed."""
    assert (
        normalise("Bayerisches National\xad\nmuseum\n\n  Munich")
        == "Bayerisches Nationalmuseum Munich"
    )


def test_loosen_drops_case_and_punctuation() -> None:
    """Loose text ignores case and punctuation."""
    assert loosen("Croce, Susanna (fresco).") == "croce susanna fresco"


def test_compare_counts_character_and_word_errors() -> None:
    """One wrong letter is one character error and one word error."""
    counts = compare("J. van der Biest", "J. van der BieSt")
    assert counts["gt_chars"] == 16
    assert counts["char_errors"] == 1
    assert counts["substitutions"] == 1
    assert counts["word_errors"] == 1
    assert counts["char_errors_loose"] == 0


def test_confusions_merge_adjacent_edits() -> None:
    """A ligature misread spanning several characters is reported as one confusion."""
    assert confusions("tapestry", "tapeäry") == {("st", "ä"): 1}


def write_specimen(root: Path, specimen_id: str, gt: str, ocr: str) -> None:
    """Create a specimen folder with ground truth and OCR text."""
    (root / specimen_id).mkdir(parents=True)
    (root / specimen_id / "gt.txt").write_text(gt, encoding="utf-8")
    (root / specimen_id / "ocr.txt").write_text(ocr, encoding="utf-8")


def test_analyse_skips_uncorrected_and_writes_results(tmp_path: Path) -> None:
    """Uncorrected specimens are skipped; corrected ones end up in the CSV output."""
    write_specimen(tmp_path, "a_p0001", "tapestry", "tapeäry")
    write_specimen(tmp_path, "b_p0002", "unchanged", "unchanged")
    with (tmp_path / "manifest.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["specimen_id", "file", "ocr_year", "section", "page", "words"])
        writer.writerow(["a_p0001", "a.pdf", "2013", "catalogue", "1", "1"])
        writer.writerow(["b_p0002", "b.pdf", "2014", "index", "2", "1"])

    rows, summary, skipped = analyse(tmp_path)

    assert skipped == 1
    assert [r["specimen_id"] for r in rows] == ["a_p0001"]
    assert summary[0]["group"] == "all" and summary[0]["cer"] == 2 / 8
    for name in ("results.csv", "summary.csv", "confusions.csv"):
        assert (tmp_path / name).exists()
