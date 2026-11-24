"""Tests for the note markers of step 3."""

from crlb.segmentation.markers import Candidate, find_markers


def candidates(*words: tuple[str, bool]) -> list[Candidate]:
    """Return candidate words with consecutive ids."""
    return [Candidate(i, text, mixed) for i, (text, mixed) in enumerate(words, 1)]


def test_markers_in_sequence_with_their_style() -> None:
    """Digits after a word in another style are markers, in sequence; a missed one does not stop it."""
    words = candidates(
        ("1630?).1", True),
        ("1953.2", False),  # same style: a number, not a marker
        ("stage.2", True),
        ("Brussels,4", True),  # 3 was missed
        ("emperors.1", True),  # out of sequence
    )
    found = find_markers(words, {"1", "2", "3", "4"}, requires_style=True)
    assert [(m.word_id, m.number) for m in found] == [(1, "1"), (3, "2"), (4, "4")]


def test_ocr_markers_without_style_but_not_after_a_bracket() -> None:
    """In OCR text the style is not required, but '(3' and '11-1' are not markers; a marker needs its note."""
    words = candidates(
        ("given.1", False),
        ("(2", False),
        ("11-2", False),
        ("sketch.2", False),
        ("it.3", False),
    )
    found = find_markers(words, {"1", "2"}, requires_style=False)
    assert [m.number for m in found] == ["1", "2"]
