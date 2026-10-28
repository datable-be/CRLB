"""Tests for the step 3 rules: furniture, printed pages, sections, entries and their fields."""

import dataclasses
import re
from typing import Any

from crlb.segmentation import fields, rules
from crlb.segmentation.config import Band, Config, Fields
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
    fields=Fields(
        labels={
            "provenance": ["provenance"],
            "copies": ["copies", "copy"],
            "literature": ["literature"],
        },
        separator=re.compile(r":|;|'\."),
        date=re.compile(r"^(?:c\.\s*)?1[4-7]\d\d\b"),
        heading_bold_lines=True,
        description_new_block=True,
        description_min_size=None,
        notes_max_size=7.8,
        note_number=re.compile(r"^(?P<number>\d+)\.?$"),
        item_fields=["provenance", "literature"],
        numbered_fields=["copies"],
        copy_marker=re.compile(r"^\((?P<number>\d+|[ilI])\)[,;:.]?$"),
        copy_labels={"provenance": ["prov."], "literature": ["lit."]},
    ),
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


def words(text: str, start: int = 1) -> list[Word]:
    """Return words of a text with consecutive ids."""
    return [
        Word(start + i, t, "Palatino", 8.8, 0, 50 + 30 * i, 100, 75 + 30 * i, 109)
        for i, t in enumerate(text.split(" "))
    ]


def texts_of(ranges: list[tuple[int, int]], ws: list[Word]) -> list[str]:
    """Return the text of each word range."""
    by_id = {w.id: w.text for w in ws}
    return [" ".join(by_id[i] for i in range(a, b + 1)) for a, b in ranges]


def test_labels_ignore_spaces_and_ocr_separators() -> None:
    """Labels match letter-spaced and with ':' read as "'." by the OCR; text in the same piece stays outside."""
    separator = re.compile(r":|;|'\.")
    assert (
        fields.label_length(
            ["P", "r", "o", "v", "e", "n", "a", "n", "c", "e", ":", "Jacob"],
            ["provenance"],
            separator,
        )
        == 11
    )
    assert (
        fields.label_length(
            ["provenance:", "see", "No.", "21."], ["provenance"], separator
        )
        == 1
    )
    assert (
        fields.label_length(
            ["Copy", "'.Drawing", "(Fig.", "116)"], ["copies", "copy"], separator
        )
        == 1
    )
    assert (
        fields.label_length(["Provenances", "of", "Rubens"], ["provenance"], separator)
        == 0
    )


def test_label_from_corrected_text_with_raw_fallback() -> None:
    """A label is taken from the corrected tokens; an unjoined label is found on the raw words and marked."""
    joined = Line(
        0,
        HEIGHT,
        WIDTH,
        words("P r o v e n a n c e : Jacob"),
        tokens=[("Provenance:", 11), ("Jacob", 12)],
    )
    assert fields.find_label(joined, BASE.fields) == ("provenance", 11, True)
    unjoined = Line(0, HEIGHT, WIDTH, words("P r o v e n a n c e : Jacob"))
    unjoined.tokens = [(w.text, w.id) for w in unjoined.words]
    unjoined.tokens[0:2] = [("Pr", 2)]  # step 2 joined only the first two letters
    assert fields.find_label(unjoined, BASE.fields) == ("provenance", 11, False)


def test_items_split_at_semicolons_outside_brackets_and_quotes() -> None:
    """A ';' inside brackets or quotation marks does not end an item."""
    ws = words('provenance: A, Antwerp; B (sold; bought back); "C; D", Paris; E.')
    items = fields.split_items(ws, 1)
    assert texts_of(items, ws) == [
        "A, Antwerp;",
        "B (sold; bought back);",
        '"C; D", Paris;',
        "E.",
    ]


def test_copy_markers_tolerate_ocr() -> None:
    """'( i )' is copy 1, a marker after '!' counts, and one missing number is skipped."""
    ws = words("( i ) Painting, lot 59! (2) Engraving, after (1), by X; (4) Drawing")
    starts = fields.copy_starts(ws, set(), BASE.fields.copy_marker)
    assert [number for _, number in starts] == ["1", "2", "4"]


def test_copies_without_markers_are_one_copy() -> None:
    """'Copy: Drawing ...' without '(n)' is a single copy with its sub-fields."""
    ws = words("Copy: Drawing, Yale; prov.: Sir John; lit.: Haverkamp, 1970.")
    doc = Document(1, "t.pdf", "XIX (4)", [], [], [])
    copies = fields.copies(ws, {1}, 1, doc, BASE)
    assert [(c.label, c.rule) for c in copies] == [("(1)", "single copy")]
    assert [f.label for f in copies[0].children] == [
        "object",
        "provenance",
        "literature",
    ]


def entry_lines() -> list[Line]:
    """Return the lines of an entry in the style of XIX (4)."""
    b = PageBuilder()
    b.page(
        heading("No. 22. Augustus: Painting", 0.10),
        body("Oil on panel; 68 × 52 cm.", 0.15),
        ("Stuttgart, Staatsgalerie.", 0.20, 8.8, 2),
        body("c. 1598–1600", 0.25),
        body("provenance: A, Antwerp; B, Paris.", 0.30),
        body("literature: Rooses, 1890; Held, 1980.", 0.35),
        body("After a long battle, Octavian.", 0.40),
        ("1. Goltzius, 1557.", 0.45, 7.5, 0),
        ("2. Van der Meulen, 1994,", 0.47, 7.5, 0),
        ("pp. 214–227.", 0.49, 7.5, 0),
    )
    lines = b.pages[0]
    # One block per group, as InDesign writes them
    for block, line in enumerate(lines):
        line.words = [
            Word(w.id, w.text, w.font, w.size, w.flags, w.x0, w.y0, w.x1, w.y1, block)
            for w in line.words
        ]
    return lines


def test_entry_fields_from_heading_to_notes() -> None:
    """An entry is divided into heading, material, location, date, labelled fields, description and notes."""
    lines = entry_lines()
    entry = Seg("entry", "22", lines[0].first, lines[-1].last, "heading", "certain")
    doc = Document(1, "t.pdf", "XIX (4)", [lines], [], [])
    found = fields.entry_fields(entry, lines, doc, BASE)
    assert [f.label for f in found] == [
        "heading",
        "material",
        "location",
        "date",
        "provenance",
        "literature",
        "description",
        "notes",
    ]
    provenance = found[4]
    assert len(provenance.children) == 2
    notes = found[-1].children
    assert [n.label for n in notes] == ["1", "2"] and notes[-1].last == lines[-1].last


def test_boundary_inside_a_joined_token_is_a_conflict() -> None:
    """A segment that starts or ends inside a token joined by step 2 is counted; one at its edges is not."""
    from crlb.segmentation.checks import boundary_conflicts

    joined = [(10, 12)]
    segs = [
        Seg("field", "a", 11, 20, "test", "probable"),  # starts inside the token
        Seg("field", "b", 1, 10, "test", "probable"),  # ends inside it
        Seg("field", "c", 13, 30, "test", "probable"),  # starts after it
        Seg("field", "d", 10, 12, "test", "probable"),  # covers it exactly
    ]
    assert boundary_conflicts(segs, joined) == 2
