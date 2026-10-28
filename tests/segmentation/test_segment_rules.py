"""Tests for the step 3 rules: furniture, printed pages, sections and entries."""

import dataclasses
import re
from typing import Any

from crlb.segmentation import rules
from crlb.segmentation.config import Band, Config
from crlb.segmentation.model import Document, Line, Link, Seg, Word

HEIGHT, WIDTH = 800.0, 500.0


BASE = Config(
    part="XIX (4)",
    path="test.toml",
    sha256="",
    furniture=[
        Band("running_head", 0.0, 0.1, max_size=7.2),
        Band("page_number", 0.9, 1.0, max_size=7.2),
    ],
    link_tool_fonts=["BellMT"],
    section_source="running_heads",
    section_level=1,
    head_name=re.compile(r"^(.*?)(?:\s+Nos?\.?\s.*)?$"),
    section_names={"catalogue": re.compile("catalog", re.IGNORECASE)},
    heading=re.compile(r"^(?:No\.\s*)?(?P<number>[UR]?\d+[a-z]?)\."),
    heading_with_link=None,
    heading_damaged_with_link=None,
    heading_bold=True,
    heading_min_size=10.6,
    heading_max_size=11.8,
    number=re.compile(r"^(?P<prefix>[A-Z]?)(?P<digits>\d+)(?P<letter>[a-z]?)$"),
    prefixes=["", "U", "R"],
)


def config(**overrides: Any) -> Config:
    """Return a configuration in the style of XIX (4), with overrides."""
    return dataclasses.replace(BASE, **overrides)


class PageBuilder:
    """Build pages of lines with consecutive word ids."""

    def __init__(self) -> None:
        """Start with no pages."""
        self.pages: list[list[Line]] = []
        self.next_id = 1

    def page(self, *lines: tuple[str, float, float, int]) -> None:
        """Add a page; each line is (text, top fraction, size, flags)."""
        result = []
        for text, top, size, flags in lines:
            y0 = top * HEIGHT
            words = []
            for i, t in enumerate(text.split(" ")):
                words.append(
                    Word(
                        self.next_id,
                        t,
                        "Palatino",
                        size,
                        flags,
                        50 + 30 * i,
                        y0,
                        75 + 30 * i,
                        y0 + size,
                    )
                )
                self.next_id += 1
            result.append(Line(len(self.pages), HEIGHT, WIDTH, words, corrected=text))
        self.pages.append(result)

    def document(self, links: list[Link] | None = None) -> Document:
        """Return the document."""
        return Document(1, "test.pdf", "XIX (4)", self.pages, links or [], [])


def body(text: str, top: float = 0.5) -> tuple[str, float, float, int]:
    """Return a body line."""
    return (text, top, 8.8, 0)


def heading(text: str, top: float = 0.3) -> tuple[str, float, float, int]:
    """Return a bold 11.2 pt heading line."""
    return (text, top, 11.2, 16)


def test_furniture_and_printed_pages() -> None:
    """Running heads and page numbers are furniture; an unreadable page number is interpolated."""
    b = PageBuilder()
    for number in ("10", "11", "1l", "13"):
        b.page(("CATALOGUE No. 1", 0.05, 6.8, 0), body("text"), (number, 0.95, 7.0, 0))
    doc = b.document()
    furniture = rules.furniture(doc, config())
    assert [s.label for s in furniture] == ["running_head", "page_number"] * 4
    printed = rules.printed_pages(doc, furniture)
    assert printed == [
        (0, "10", "furniture"),
        (1, "11", "furniture"),
        (2, "12", "interpolated"),
        (3, "13", "furniture"),
    ]


def test_link_tool_words_are_furniture() -> None:
    """Words in the link tool's font are marked, as they are stored out of reading order."""
    b = PageBuilder()
    b.page(body("see copy"))
    b.pages[0][0].words.append(Word(99, "(7)", "BellMT", 10.0, 0, 200, 400, 220, 410))
    segs = rules.furniture(b.document(), config())
    assert [(s.label, s.first) for s in segs] == [("moved_by_link_tool", 99)]


def test_sections_follow_running_heads() -> None:
    """A page without a running head belongs to the section of the next page with one."""
    b = PageBuilder()
    b.page(("INTRODUCTION", 0.05, 6.8, 0), body("intro"))
    b.page(body("Catalogue title page"))
    b.page(("CATALOGUE No. 1", 0.05, 6.8, 0), body("entry"))
    doc = b.document()
    cfg = config()
    sections = rules.sections(doc, cfg, rules.furniture(doc, cfg))
    assert [s.label for s in sections] == ["introduction", "catalogue"]
    assert sections[1].first == doc.pages[1][0].first


def test_entries_by_heading_pattern_and_style() -> None:
    """Bold headings with increasing numbers start entries; body lines and wrong styles do not."""
    b = PageBuilder()
    b.page(
        heading("No. 1. Augustus: Painting"),
        body("No. 2. in a body line", 0.4),
        body("provenance: x", 0.6),
    )
    b.page(heading("No. 1a. Copy"), heading("R1. Rejected", 0.7))
    doc = b.document()
    section = Seg("section", "catalogue", 1, b.next_id - 1, "test", "certain")
    found, dropped = rules.entries(doc, section, config())
    assert [e.label for e in found] == ["1", "1a", "R1"] and dropped == []
    assert found[0].last == doc.pages[1][0].first - 1


def test_out_of_sequence_number_is_dropped() -> None:
    """A number that breaks the increasing sequence is dropped, not made an entry."""
    b = PageBuilder()
    for number in ("1", "2", "9", "3", "4"):
        b.page(heading(f"No. {number}. Title"))
    doc = b.document()
    section = Seg("section", "catalogue", 1, b.next_id - 1, "test", "certain")
    found, dropped = rules.entries(doc, section, config())
    assert [e.label for e in found] == ["1", "2", "3", "4"] and dropped == ["9"]


def test_damaged_number_is_inferred_from_the_sequence() -> None:
    """With an RKD link, a title with an unreadable number ('10«') gets the one number that fits."""
    b = PageBuilder()
    b.page(
        body("10. THE SACRIFICE: TAPESTRY", 0.2),
        body("10«. THE SACRIFICE: BOZZETTO", 0.5),
        body("10b. THE SACRIFICE: MODELLO", 0.8),
    )
    damaged = b.pages[0][1].words[1]
    link = Link(
        1, 0, "https://rkd.nl/images/1", damaged.x0, damaged.y0, damaged.x1, damaged.y1
    )
    doc = b.document([link])
    cfg = config(
        heading=re.compile(r"^(?P<number>\d{1,2} ?[a-z]?) ?\.\s*(?=[A-Z][A-Z])"),
        heading_damaged_with_link=re.compile(
            r"^(?P<number>\S{0,4}?)\s*\.?\s*(?=[A-Z][A-Z ]+:\s*[A-Z]{4,})"
        ),
        heading_bold=False,
    )
    section = Seg("section", "catalogue", 1, b.next_id - 1, "test", "certain")
    found, _ = rules.entries(doc, section, cfg)
    assert [(e.label, e.confidence) for e in found] == [
        ("10", "probable"),
        ("10a", "uncertain"),
        ("10b", "probable"),
    ]
    assert "inferred" in (found[1].reason or "")


def test_infer_key_needs_exactly_one_fit() -> None:
    """Between 13d and 14a only 14 fits; after the last entry nothing is certain."""
    assert rules.infer_key((0, 13, "d"), (0, 14, "a")) == (0, 14, "")
    assert rules.infer_key((0, 13, "d"), None) is None
