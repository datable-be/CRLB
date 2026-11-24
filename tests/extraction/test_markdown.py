"""Tests for the helpers of the Markdown export."""

import json

from crlb.extraction import markdown
from crlb.extraction.markdown import Piece, Stats


def piece(
    text: str,
    italic: bool = False,
    printed: str | None = "10",
    joined: bool = False,
    paragraph: bool = False,
) -> Piece:
    """Return a piece with defaults for the tests."""
    return Piece(text, italic, printed, joined, paragraph)


def test_escape_markdown_characters_and_list_starts() -> None:
    """Characters with a meaning in Markdown are escaped, and so is a list start."""
    assert markdown.escape("a*b_c #1 [x] <y>") == r"a\*b\_c \#1 \[x\] \<y\>"
    assert markdown.escape_start("1. Liedtke") == r"1\. Liedtke"
    assert markdown.escape_start("- dash") == r"\- dash"
    assert markdown.escape_start("1984, I") == "1984, I"


def test_render_merges_italic_runs_and_marks_page_breaks() -> None:
    """Consecutive italic words form one run; a new printed page gets a comment."""
    stats = Stats()
    out = markdown.render(
        [
            piece("Rooses,"),
            piece("Rubens", italic=True),
            piece("en", italic=True),
            piece("Moretus,", italic=True),
            piece("1884,", printed="11"),
        ],
        stats,
    )
    assert out == ["Rooses, *Rubens en Moretus,* <!-- p. 11 --> 1884,"]
    assert (stats.italic_runs, stats.page_breaks, stats.paragraphs) == (1, 1, 1)


def test_render_joins_broken_words_and_splits_paragraphs() -> None:
    """A word broken at the end of a line is rejoined; a paragraph start closes the italics."""
    out = markdown.render(
        [
            piece("Plantin-", italic=True),
            piece("Moretus", joined=True),
            piece("Next", paragraph=True),
        ],
        Stats(),
    )
    assert out == ["*Plantin-Moretus*", "Next"]


def test_column_starts_and_indents() -> None:
    """Indented lines are recognised against the left edge of their column."""
    xs = [82.2] * 10 + [93.5] * 3 + [289.1] * 10 + [300.5] * 3
    starts = markdown.column_starts(xs)
    assert starts == [82.2, 289.1]
    assert markdown.indented(93.5, starts)
    assert markdown.indented(300.5, starts)
    assert not markdown.indented(289.1, starts)


def test_strip_label() -> None:
    """The printed label is removed, also with an OCR space in it; other text is kept."""
    assert markdown.strip_label(["provenance: Moretus; sale"], "provenance") == [
        "Moretus; sale"
    ]
    assert markdown.strip_label(["C opies: (1) Painting"], "copies") == ["(1) Painting"]
    assert markdown.strip_label(["Moretus; sale"], "provenance") == ["Moretus; sale"]


def test_list_items_keep_the_printed_number() -> None:
    """A list item keeps its printed label, so a missing copy does not renumber the rest."""
    assert markdown.list_item("(12)", ["Drawing,", "Paris"]) == "- (12) Drawing, Paris"
    assert markdown.list_item("1.", ["Liedtke"]) == r"- 1\. Liedtke"
    assert markdown.COPY_LABEL.sub("", "( i ) Painting") == "Painting"


def test_front_matter_values_are_json() -> None:
    """Every front matter value reads back as JSON."""
    values: dict[str, object] = {
        "part": "XIX (4)",
        "rkd": ["https://rkd.nl/images/1"],
        "title": 'A "b"',
    }
    text = markdown.front_matter(values)
    lines = text.strip().split("\n")
    assert lines[0] == lines[-1] == "---"
    for line in lines[1:-1]:
        key, _, value = line.partition(": ")
        assert json.loads(value) == values[key]


def test_a_marker_becomes_a_footnote_reference() -> None:
    """A piece with a footnote gets its reference after the escaped text, inside an italic run."""
    stats = Stats()
    out = markdown.render(
        [
            Piece("in", False, "10", False, False),
            Piece("1630?).", False, "10", False, False, "1"),
            Piece("Moretus*", True, "10", False, False, "2"),
        ],
        stats,
    )
    assert out == [r"in 1630?).[^1] *Moretus\*[^2]*"]
    assert stats.footnotes == 2


def test_note_numbers_are_stripped_with_or_without_a_full_stop() -> None:
    """'1\\. Liedtke' (born-digital) and '1 A search' (OCR) both lose their number."""
    assert markdown.NOTE_NUMBER.sub("", r"1\. Liedtke", count=1) == "Liedtke"
    assert markdown.NOTE_NUMBER.sub("", "1 A search", count=1) == "A search"
