"""The view of a document that the segmentation rules work on: pages of visual lines, links and bookmarks.

A visual line is a run of consecutive words (in stored order) on the same
height: ABBYY often puts an entry number and its title in separate blocks on
one line, so the stored (block, line) is too fine. Each line carries its raw
text and its corrected text (tokens of the correction run that start on the
line), so rules can match on corrected text while boundaries stay raw word ids.
"""

import sqlite3
from dataclasses import dataclass, field
from statistics import median


@dataclass(frozen=True)
class Word:
    """A raw word with its position and typography."""

    id: int
    text: str
    font: str
    size: float
    flags: int
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class Line:
    """A visual line: consecutive words on the same height."""

    page_index: int
    page_height: float
    page_width: float
    words: list[Word]
    corrected: str = ""

    @property
    def first(self) -> int:
        """Return the id of the first word."""
        return self.words[0].id

    @property
    def last(self) -> int:
        """Return the id of the last word."""
        return self.words[-1].id

    @property
    def text(self) -> str:
        """Return the raw text of the line."""
        return " ".join(w.text for w in self.words)

    @property
    def top(self) -> float:
        """Return the top of the line as a fraction of the page height."""
        return min(w.y0 for w in self.words) / self.page_height

    @property
    def bottom(self) -> float:
        """Return the bottom of the line as a fraction of the page height."""
        return max(w.y1 for w in self.words) / self.page_height

    @property
    def size(self) -> float:
        """Return the median font size of the line's words."""
        return median(w.size for w in self.words)


@dataclass
class Link:
    """A URI link annotation."""

    id: int
    page_index: int
    uri: str
    x0: float
    y0: float
    x1: float
    y1: float

    def covers(self, word: Word) -> bool:
        """Return whether the centre of a word lies inside the link box."""
        cx, cy = (word.x0 + word.x1) / 2, (word.y0 + word.y1) / 2
        return self.x0 <= cx <= self.x1 and self.y0 <= cy <= self.y1


@dataclass
class Document:
    """A document as pages of visual lines, with its links and bookmarks."""

    id: int
    path: str
    part: str
    pages: list[list[Line]]  # per page index
    links: list[Link]
    toc: list[tuple[int, str, int | None]]  # level, title, page index

    @property
    def lines(self) -> list[Line]:
        """Return all lines in reading order."""
        return [line for page in self.pages for line in page]


@dataclass
class Seg:
    """A segment under construction, before it is stored."""

    kind: str
    label: str | None
    first: int
    last: int
    rule: str
    confidence: str
    reason: str | None = None
    link_id: int | None = None
    children: list[Seg] = field(default_factory=list)


def same_line(a: Word, b: Word) -> bool:
    """Return whether word b continues word a's visual line: to its right and overlapping in height by half."""
    overlap = min(a.y1, b.y1) - max(a.y0, b.y0)
    return b.x0 >= a.x1 - 1 and overlap >= 0.5 * min(a.y1 - a.y0, b.y1 - b.y0)


def visual_lines(
    rows: list[sqlite3.Row], height: float, width: float, page_index: int
) -> list[Line]:
    """Group the words of a page (in stored order) into visual lines."""
    result: list[Line] = []
    previous_key = None
    for row in rows:
        word = Word(
            row["id"],
            row["text"],
            row["font"],
            row["size"],
            row["flags"],
            row["x0"],
            row["y0"],
            row["x1"],
            row["y1"],
        )
        key = (row["block_no"], row["line_no"])
        if result and (key == previous_key or same_line(result[-1].words[-1], word)):
            result[-1].words.append(word)
        else:
            result.append(Line(page_index, height, width, [word]))
        previous_key = key
    return result


def corrected_texts(lines: list[Line], tokens: dict[int, str]) -> None:
    """Set the corrected text of each line: the tokens that start on it, or the raw words where there is no token."""
    for line in lines:
        parts = []
        for word in line.words:
            if word.id in tokens:
                parts.append(tokens[word.id])
            elif not tokens:
                parts.append(word.text)
        line.corrected = " ".join(parts)


def load_document(
    conn: sqlite3.Connection, document_id: int, correction_run: int | None
) -> Document:
    """Load a document with its visual lines, the corrected text of the given run, links and bookmarks."""
    doc = conn.execute(
        "SELECT id, path, part FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    tokens: dict[int, str] = {}
    if correction_run is not None:
        tokens = dict(
            conn.execute(
                "SELECT c.first_word_id, c.text FROM corrected_words c JOIN pages p ON p.id = c.page_id"
                " WHERE c.run_id = ? AND p.document_id = ?",
                (correction_run, document_id),
            ).fetchall()
        )
    pages = []
    for page_id, page_index, height, width in conn.execute(
        "SELECT id, page_index, height, width FROM pages WHERE document_id = ? ORDER BY page_index",
        (document_id,),
    ).fetchall():
        rows = conn.execute(
            "SELECT * FROM words WHERE page_id = ? ORDER BY id", (page_id,)
        ).fetchall()
        lines = visual_lines(rows, height, width, page_index)
        corrected_texts(lines, tokens)
        pages.append(lines)
    links = [
        Link(r["id"], r["page_index"], r["uri"], r["x0"], r["y0"], r["x1"], r["y1"])
        for r in conn.execute(
            "SELECT l.*, p.page_index FROM links l JOIN pages p ON p.id = l.page_id"
            " WHERE p.document_id = ? AND l.kind = 'uri' ORDER BY l.id",
            (document_id,),
        )
    ]
    toc = [
        (r["level"], r["title"], r["page_index"])
        for r in conn.execute(
            "SELECT level, title, page_index FROM toc WHERE document_id = ? ORDER BY position",
            (document_id,),
        )
    ]
    return Document(doc["id"], doc["path"], doc["part"], pages, links, toc)
