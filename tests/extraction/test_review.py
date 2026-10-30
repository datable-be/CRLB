"""Tests for the helpers of the extraction review page."""

from crlb.extraction import review
from crlb.extraction.source import Node


def test_line_boxes_merge_the_words_of_a_line() -> None:
    """Words on one line become one box; another line or page gets its own."""
    boxes = review.line_boxes(
        [
            (1, 0, 0, 10, 20, 30, 28),
            (1, 0, 0, 35, 19, 60, 29),
            (1, 0, 1, 10, 32, 40, 40),
            (2, 0, 0, 10, 20, 30, 28),
        ]
    )
    assert [(b.page_id, b.x0, b.y0, b.x1, b.y1) for b in boxes] == [
        (1, 10, 19, 60, 29),
        (1, 10, 32, 40, 40),
        (2, 10, 20, 30, 28),
    ]


def test_covered_by_an_overlapping_range() -> None:
    """A stage is covered when a row's word range overlaps it."""
    item = Node(1, "item", "1", 10, 19, None, "Albert Fonson;")
    assert review.covered(item, [(15, 30)])
    assert not review.covered(item, [(1, 9), (20, 25)])


def test_date_range_and_mapped_values() -> None:
    """A parsed range shows one date when start and end are equal; mapped values are escaped."""
    assert review.date_range("1813", "1813") == "1813"
    assert review.date_range("1613", "1616") == "1613 – 1616"
    assert review.date_range(None, None) is None
    assert review.mapped("Oil & panel", "paneel") == (
        'Oil &amp; panel <span class="mapped">→ paneel</span>'
    )
