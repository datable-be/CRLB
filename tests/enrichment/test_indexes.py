"""Tests for the index terms of step 5a: labels, page references and catalogue numbers."""

from crlb.enrichment.indexes import (
    WORK_TEXT,
    Reference,
    entry_number,
    page_numbers,
    parse_references,
    split_references,
)


def test_label_and_references_are_split_at_the_first_page() -> None:
    """The references are the tail that starts with a page; a regnal number stays in the label."""
    assert split_references("Bellori, Giovanni Pietro 11 n. 4, 16, 46") == (
        "Bellori, Giovanni Pietro",
        "11 n. 4, 16, 46",
    )
    assert split_references("Moretus, Jan I 57, 58") == ("Moretus, Jan I", "57, 58")
    assert split_references("Bath") == ("Bath", "")


def test_page_references_with_notes_and_figures() -> None:
    """Notes are numbers below their page after 'n.' or 'nn.'; figures follow 'fig.'."""
    assert parse_references("57–58, 132 nn. 8, 11, 156, fig. 6") == [
        Reference("57–58"),
        Reference("132", note="8"),
        Reference("132", note="11"),
        Reference("156"),
        Reference(None, figure="6"),
    ]
    assert parse_references("11 n. 4, 16") == [
        Reference("11", note="4"),
        Reference("16"),
    ]
    assert page_numbers("57–58") == {57, 58}
    assert page_numbers("I25".translate(str.maketrans("I", "1"))) == {125}


def test_catalogue_numbers_of_the_collections_index() -> None:
    """'No. 2, Copy' and 'Cat. 12c' are read; an OCR number counts only if one entry of the part fits."""
    known = {"2", "4", "11b", "12c", "12d", "10c"}
    match = WORK_TEXT.match("Portrait of Jan Moretus I, No. 2, Copy; 58, fig. 6")
    assert match and (match["number"], match["copy"], match["refs"]) == (
        "2",
        "Copy",
        "58, fig. 6",
    )
    match = WORK_TEXT.match("The Triumph of Faith, Cat. 12c, 113, 114")
    assert match and entry_number(match["number"], known) == "12c"
    assert entry_number("nb", known) == "11b"
    assert entry_number("i2d", known) == "12d"
    assert entry_number("roc", known) == "10c"
    assert entry_number("14b", known) is None
