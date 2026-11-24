"""Index entries (rule 10): the items of the index sections, as trees of entries and sub-entries.

Two layouts, chosen by the section label:

- names and places: an entry starts at the left edge of its column; a line
  indented one step more than an entry is its sub-entry. A line continues the
  item before it when it starts with a page reference ('132 n. 11', 'fig. 6')
  or a bracket, when it starts inside a word that step 2 joined across the
  line break, when it is indented and starts in lower case ('of the
  Netherlands'), when the line before ends in ',', '-', 'Cat.' or 'No.', when
  the item has a bracket still open and the line before does not end in a
  page number ('(and J. van' / 'den Hoecke)'), or when it is
  indented by the hanging indent beyond the item: two steps for an entry, and
  for a sub-entry the volume's `hanging` (two steps in XIX (4), one in the II
  index, which has no sub-sub-entries).
- collections: a line in capitals is a collection (and the capitals lines
  right after it continue it); a line ending in ':' is an attribution
  ('Rubens, painting:'), together with the line before it if that has no
  catalogue number ('J. Geubels, J. Raes, J. Fobert and H.' / 'Vervoert,
  tapestries after Rubens:'); the lines after it are works, each running up to
  its catalogue number ('No. 2, Copy;', 'Cat. 12c,', OCR 'a t . 17') and the
  page references after it. The indentation is not used: XIX (4) sets all
  lines flush.

The introduction of an index, set across the full width of the page, is in no
item: every line of a block (on its page) with a line wider than a column.
"""

import itertools
import re
from dataclasses import dataclass, field

from crlb.segmentation.model import Document, Line, Seg

COLLECTIONS = "collections"
NAMES = "names"
# section label -> layout
LAYOUTS = {"index: collections": COLLECTIONS, "index: names and places": NAMES}

ENTRY, ATTRIBUTION, WORK = "index entry", "index attribution", "index work"
RULE = "index layout"

# A line that starts with a page reference: '132 n. 11', 'nn. 8, 11', 'fig. 6', 'figs 160'
PAGE_REFERENCE = re.compile(r"^(?:\d|nn?\.|figs?\b|pls?\b)", re.IGNORECASE)
# A line that ends where the item cannot end: 'Berlin-', '(painting),', 'Cat.'
CONTINUES = re.compile(r"(?:[,\-­–]|\b(?:Cat|Nos?)[.,]?)$")
# The catalogue number of a work in the collections index ('No. 2', 'Cat. 12c'), also as
# the OCR reads it ('Cat, 15c', 'Cat 10', 'a t . 17', 'at. 12', 'Q t. 6b')
CATALOGUE_NUMBER = re.compile(
    r"\b(?:Nos?\.|Cat\b[.,]?|(?:[CQ]\s?)?a\s?t\s?[.,]|Q\s?t\s?[.,])"
)
# A line that continues a work of the collections index: its copy or page references
WORK_CONTINUES = re.compile(r"^(?:Copy\b|\d|nn?\.|figs?\b|pls?\b)", re.IGNORECASE)
# A cross-reference entry: 'Caesar: see Julius Caesar'
SEE = re.compile(r"\bsee\b", re.IGNORECASE)
# Lines starting within this distance share a column edge
COLUMN_GAP = 2.5
# The gap between the line starts of two columns is at least this wide (indents are smaller)
MIN_COLUMN_GAP = 60.0


@dataclass
class Item:
    """An index item under construction: its own lines and its sub-items."""

    label: str
    level: int
    lines: list[Line]
    reason: str
    children: list[Item] = field(default_factory=list)

    @property
    def text(self) -> str:
        """Return the corrected text of the item's own lines."""
        return " ".join(line_text(line) for line in self.lines)

    def last(self) -> int:
        """Return the last word id of the item and its sub-items."""
        return self.children[-1].last() if self.children else self.lines[-1].last


def line_text(line: Line) -> str:
    """Return the corrected text of a line, or its raw text without a correction."""
    return (line.corrected or line.text).strip()


def is_capitals(text: str) -> bool:
    """Return whether a line is set in capitals: not a page reference, at least three letters, nearly all upper case."""
    if PAGE_REFERENCE.match(text):
        return False
    letters = [c for c in text if c.isalpha()]
    upper = sum(c.isupper() for c in letters)
    return len(letters) >= 3 and upper >= 0.9 * len(letters)


def column_start(xs: list[float]) -> float:
    """Return the left edge of a column: the smallest x that at least two lines share."""
    ordered = sorted(xs)
    for k, x in enumerate(ordered[:-1]):
        if ordered[k + 1] - x <= COLUMN_GAP:
            return x
    return ordered[0]


def column_split(xs: list[float]) -> float:
    """Return the x that separates the two columns of a page: the middle of the widest gap between line starts."""
    ordered = sorted(xs)
    gaps = [(b - a, (a + b) / 2) for a, b in itertools.pairwise(ordered)]
    widest = max(gaps, default=(0.0, 0.0))
    return widest[1] if widest[0] >= MIN_COLUMN_GAP else float("inf")


def levels(lines: list[Line], indent: float) -> list[int]:
    """Return the indentation level of each line, from the left edge of its column on its page."""
    pages: dict[int, list[float]] = {}
    for line in lines:
        pages.setdefault(line.page_index, []).append(line.words[0].x0)
    splits = {page: column_split(xs) for page, xs in pages.items()}

    def column(line: Line) -> tuple[int, bool]:
        """Return the page and column of a line."""
        return line.page_index, line.words[0].x0 > splits[line.page_index]

    columns: dict[tuple[int, bool], list[float]] = {}
    for line in lines:
        columns.setdefault(column(line), []).append(line.words[0].x0)
    starts = {key: column_start(xs) for key, xs in columns.items()}
    return [
        max(0, round((line.words[0].x0 - starts[column(line)]) / indent))
        for line in lines
    ]


def continues(item: Item, line: Line, level: int, hanging: int) -> bool:
    """Return whether a line continues an item of the names layout."""
    text = item.text
    previous = item.lines[-1]
    return bool(
        PAGE_REFERENCE.match(line_text(line))
        or line_text(line).startswith("(")
        # a word joined by step 2 across the line break ('Arch-' / 'duchess')
        or any(last >= line.first for _, last in previous.tokens)
        # a wrapped name ('y Guzmán, 6th Marques of', 'of the Netherlands')
        or (line_text(line)[:1].islower() and level > item.level)
        or CONTINUES.search(line_text(item.lines[-1]))
        or (
            text.count("(") > text.count(")")
            and not line_text(item.lines[-1])[-1:].isdigit()
        )
        or level >= item.level + (hanging if item.level else 2)
    )


def names_items(lines: list[Line], indent: float, hanging: int) -> list[Item]:
    """Return the entries of a names-and-places index, with their sub-entries."""
    roots: list[Item] = []
    stack: list[Item] = []
    current: Item | None = None
    for line, level in zip(lines, levels(lines, indent), strict=True):
        if current is not None and continues(current, line, level, hanging):
            current.lines.append(line)
            continue
        while stack and stack[-1].level >= level:
            stack.pop()
        reason = f"indentation level {level}" + (" under its entry" if stack else "")
        item = Item(ENTRY, level, [line], reason)
        (stack[-1].children if stack else roots).append(item)
        stack.append(item)
        current = item
    return roots


def collection_items(lines: list[Line]) -> list[Item]:
    """Return the collections of a collections index, with their attributions and works."""
    roots: list[Item] = []
    collection = attribution = work = None
    previous_capitals = False
    for k, line in enumerate(lines):
        text = line_text(line)
        capitals = is_capitals(text)
        following = line_text(lines[k + 1]) if k + 1 < len(lines) else ""
        if capitals and collection is not None and previous_capitals:
            collection.lines.append(line)
        elif capitals:
            collection = Item(ENTRY, 0, [line], "a line in capitals")
            roots.append(collection)
            attribution = work = None
        elif collection is None:
            pass  # the introduction of the index, before the first collection
        elif (
            attribution is not None
            and attribution.lines[-1] is lines[k - 1]
            and (not attribution.text.endswith(":"))
        ):
            attribution.lines.append(line)
        elif text.endswith(":") or (
            following.endswith(":")
            and not is_capitals(following)
            and not WORK_CONTINUES.match(text)
            and not CATALOGUE_NUMBER.search(text)
            and not (work is not None and not CATALOGUE_NUMBER.search(work.text))
        ):
            attribution = Item(ATTRIBUTION, 1, [line], "a line ending in ':'")
            collection.children.append(attribution)
            work = None
        elif work is not None and (
            not CATALOGUE_NUMBER.search(work.text)
            or WORK_CONTINUES.match(text)
            or CONTINUES.search(line_text(work.lines[-1]))
        ):
            work.lines.append(line)
        else:
            work = Item(WORK, 2, [line], "a work, up to its catalogue number")
            (attribution or collection).children.append(work)
        previous_capitals = capitals
    return roots


def complete(item: Item) -> bool:
    """Return whether an item has what its layout expects: a work its number, a final entry a page reference."""
    if item.label == WORK:
        return bool(CATALOGUE_NUMBER.search(item.text))
    if item.label == ENTRY and not item.children:
        return bool(re.search(r"\d", item.text) or SEE.search(item.text))
    return True


def to_seg(item: Item) -> Seg:
    """Return the segment of an item and its sub-items."""
    return Seg(
        "item",
        item.label,
        item.lines[0].first,
        item.last(),
        RULE,
        "certain" if complete(item) else "probable",
        item.reason if complete(item) else item.reason + "; incomplete",
        children=[to_seg(child) for child in item.children],
    )


def is_wide(line: Line) -> bool:
    """Return whether a line is wider than a column: more than half the page."""
    return line.words[-1].x1 - line.words[0].x0 > line.page_width / 2


def introduction_segs(lines: list[Line]) -> list[Seg]:
    """Return one 'introduction' field per run of consecutive introduction lines."""
    runs: list[list[Line]] = []
    for line in lines:
        if runs and runs[-1][-1].last + 1 == line.first:
            runs[-1].append(line)
        else:
            runs.append([line])
    return [
        Seg(
            "field",
            "introduction",
            run[0].first,
            run[-1].last,
            RULE,
            "certain",
            "a block with a line wider than a column",
        )
        for run in runs
    ]


def index_items(
    doc: Document,
    section: Seg,
    indent: float,
    hanging: int,
    layout: str,
    skip: set[int],
) -> list[Seg]:
    """Return the index items of a section in the given layout, and its introduction as fields.

    An item's word range can enclose an introduction, which the PDF may store
    between the lines of a column; the item's text leaves it out.
    """
    lines = [
        line
        for line in doc.lines
        if section.first <= line.first <= section.last and line.first not in skip
    ]
    wide = {(line.page_index, line.block_no) for line in lines if is_wide(line)}
    introduction = [line for line in lines if (line.page_index, line.block_no) in wide]
    lines = [line for line in lines if (line.page_index, line.block_no) not in wide]
    items = (
        collection_items(lines)
        if layout == COLLECTIONS
        else names_items(lines, indent, hanging)
    )
    segs = [to_seg(item) for item in items] + introduction_segs(introduction)
    return sorted(segs, key=lambda seg: seg.first)
