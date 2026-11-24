"""Turn the index items of step 3 into control terms with their page references (step 5a).

Reads the active segmentation run: the sections `index: names and places` and
`index: collections` of every document, and their items (rule 10 of step 3).

- **Names and places:** one term per entry and sub-entry. The label is the
  text before the page references; the type follows from the index:
  `dealer` and `auctioneer` when the entry says so, `work` for an italic
  sub-entry (a work by the person above), `place` for an entry with
  institutions below it, `collection` for those institutions, `person` for
  `Last, First`.
- **Collections:** one term per collection (type `collection`). Each work
  below it gives references with the catalogue number, checked against the
  entries of the part (the OCR's `Cat. nb` is `11b` only if that entry exists),
  the copy (`No. 22, Copy 4`) and the attribution (`After Rubens, painting`).

The terms replace the index terms of an earlier run of this command, unless a
normalisation run already refers to them. Prints only counts.
"""

import argparse
import itertools
import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from crlb import db
from crlb.extraction.source import joined_text
from crlb.runs import utc_now
from crlb.segmentation.index import ATTRIBUTION, ENTRY, LAYOUTS, NAMES, WORK
from crlb.text import SEGMENTATION_STEP, active_run

VOCABULARY = "crlb_index"
ITALIC = 2  # words.flags

# Tokens of the page references: '57–58,', '11', 'n.', 'nn.', 'fig.', 'figs'
KEYWORD = re.compile(r"^(?:nn?|figs?|pls?)\.?,?;?$", re.IGNORECASE)
# The OCR reads digits as letters inside a number ('I25', 'l8o')
OCR_DIGITS = str.maketrans(
    {"I": "1", "l": "1", "i": "1", "!": "1", "|": "1", "o": "0", "O": "0"}
)
NUMBER = re.compile(r"^(\d+)(?:\s*[–\-—]\s*(\d+))?[a-z]?$")
MARKER = re.compile(r"\s*\((dealer|auctioneer)\)", re.IGNORECASE)
# A work of the collections index: title, catalogue number, copy, page references
WORK_TEXT = re.compile(
    r"^(?P<title>.*?),?\s*(?P<label>Nos?\.|Cat\b[.,]?|(?:[CQ]\s?)?a\s?t\s?[.,]|Q\s?t\s?[.,])"
    r"\s*(?P<number>[^\s,;]+(?:\s[a-z](?=[\s,;]))?)[^\s,;]*"
    r"(?:,\s*(?P<copy>Copy(?:\s*\d+)?))?\s*[;,]?\s*(?P<refs>.*)$"
)
# Characters the OCR reads in catalogue numbers, with the digits they may stand for
OCR_NUMBER = {
    "i": "1",
    "l": "1",
    "I": "1",
    "!": "1",
    "|": "1",
    "x": "1",
    "r": "1",
    "o": "0",
    "O": "0",
    "n": "11",
}


@dataclass(frozen=True)
class Reference:
    """A page reference: a page or page range, with a note or figure number."""

    page: str | None
    note: str | None = None
    figure: str | None = None


@dataclass(frozen=True)
class Work:
    """A work listed under a collection in the collections index."""

    segment_id: int
    attribution: str | None
    entry_text: str | None
    entry_number: str | None
    copy: str | None
    references: list[Reference]


@dataclass
class Term:
    """An index term under construction."""

    segment_id: int
    label: str
    type: str | None
    references: list[Reference]
    path: list[str]
    parent: int | None = None  # segment id of the broader term
    works: list[Work] = field(default_factory=list)


def is_reference_token(token: str) -> bool:
    """Return whether a token belongs to the page references: it has a digit, or it is 'n.', 'nn.', 'fig.'."""
    return bool(re.search(r"\d", token) or KEYWORD.match(token))


def split_references(text: str) -> tuple[str, str]:
    """Split an index entry into its label and its page references: the longest tail of reference tokens that starts with a digit."""
    tokens = text.split()
    start = len(tokens)
    for k in range(len(tokens) - 1, -1, -1):
        if not is_reference_token(tokens[k]):
            break
        if re.match(r"^\d", tokens[k].translate(OCR_DIGITS)) or KEYWORD.match(
            tokens[k]
        ):
            start = k
    while start < len(tokens) and KEYWORD.match(tokens[start]):
        start += 1  # references start with a page, not with 'n.'
    label = " ".join(tokens[:start]).rstrip(" ,;")
    return label, " ".join(tokens[start:])


def parse_references(text: str) -> list[Reference]:
    """Parse page references: '57–58, 11 n. 4, 132 nn. 8, 11, 156, fig. 6' (a note number is smaller than its page)."""
    result: list[Reference] = []
    mode = "page"
    page: str | None = None
    for raw in text.replace(";", ",").split():
        token = (
            raw.strip(",.;:").translate(OCR_DIGITS) if re.search(r"\d", raw) else raw
        )
        lower = raw.lower().strip(",;")
        if lower in ("n.", "n"):
            mode = "note"
            continue
        if lower in ("nn.", "nn"):
            mode = "notes"
            continue
        if lower.startswith(("fig", "pl")):
            mode = "figure"
            digits = re.sub(r"^\D+", "", raw.strip(",;"))
            if digits:
                result.append(Reference(None, figure=digits.strip(".")))
            continue
        match = NUMBER.match(token)
        if not match:
            continue
        number = int(match[1])
        if mode == "figure":
            result.append(Reference(None, figure=token))
        elif (
            mode in ("note", "notes") and page is not None and number < first_page(page)
        ):
            result.append(Reference(page, note=token))
            if mode == "note":
                mode = "page"
        else:
            mode = "page"
            page = token
            result.append(Reference(token))
    # A page followed by its note: keep only the note row for that page
    noted = {r.page for r in result if r.note}
    return [r for r in result if r.note or r.figure or r.page not in noted]


def first_page(printed: str) -> int:
    """Return the first page number of a printed page or range."""
    match = NUMBER.match(printed)
    return int(match[1]) if match else 0


def page_numbers(printed: str) -> set[int]:
    """Return the page numbers of a printed page or range ('57–58' -> {57, 58})."""
    match = NUMBER.match(printed)
    if not match:
        return set()
    first = int(match[1])
    last = int(match[2]) if match[2] else first
    return set(range(first, last + 1)) if 0 <= last - first <= 50 else {first}


def entry_number(raw: str, known: set[str]) -> str | None:
    """Return the catalogue number of an index reference, reading OCR letters as digits only if exactly one existing entry fits."""
    clean = re.sub(r"[^0-9A-Za-z!|]", "", raw)
    if clean in known:
        return clean
    options = [[c] + ([OCR_NUMBER[c]] if c in OCR_NUMBER else []) for c in clean]
    fits = {"".join(choice) for choice in itertools.product(*options)} & known
    return fits.pop() if len(fits) == 1 else None


def clean(text: str) -> str:
    """Return index text with soft hyphens at line ends rejoined."""
    return re.sub(r"­\s*", "", text).strip()


def own_text(
    conn: sqlite3.Connection,
    item: sqlite3.Row,
    children: list[sqlite3.Row],
    gaps: list[tuple[int, int]],
) -> str:
    """Return the text of an item without its sub-items and without the introduction inside its range."""
    end = children[0]["first_word_id"] - 1 if children else item["last_word_id"]
    pieces, start = [], item["first_word_id"]
    for a, b in sorted(gaps):
        if start <= a <= end:
            pieces.append((start, a - 1))
            start = b + 1
    pieces.append((start, end))
    return clean(" ".join(joined_text(conn, a, b) for a, b in pieces if a <= b))


def children_of(conn: sqlite3.Connection, segment_id: int) -> list[sqlite3.Row]:
    """Return the child segments of a segment, in order."""
    return conn.execute(
        "SELECT * FROM segments WHERE parent_id = ? ORDER BY first_word_id",
        (segment_id,),
    ).fetchall()


def is_italic(conn: sqlite3.Connection, word_id: int) -> bool:
    """Return whether a word is set in italics."""
    return bool(
        conn.execute("SELECT flags FROM words WHERE id = ?", (word_id,)).fetchone()[0]
        & ITALIC
    )


def names_terms(
    conn: sqlite3.Connection, section: sqlite3.Row, gaps: list[tuple[int, int]]
) -> list[Term]:
    """Return the terms of a names-and-places index section."""
    terms: list[Term] = []

    def visit(item: sqlite3.Row, parent: Term | None) -> None:
        """Add the term of an item and of its sub-items."""
        children = [c for c in children_of(conn, item["id"]) if c["kind"] == "item"]
        label, refs = split_references(own_text(conn, item, children, gaps))
        marker = MARKER.search(label)
        italic = is_italic(conn, item["first_word_id"])
        if marker:
            kind: str | None = marker[1].lower()
        elif parent is not None and italic:
            kind = "work"
        elif (
            parent is None
            and children
            and not all(is_italic(conn, c["first_word_id"]) for c in children)
        ):
            kind = "place"
        elif parent is not None and parent.type in ("place", "collection"):
            kind = "collection"
        elif parent is None and "," in label:
            kind = "person"
        else:
            kind = None
        term = Term(
            item["id"],
            label,
            kind,
            parse_references(refs),
            (parent.path if parent else []) + [label],
            parent.segment_id if parent else None,
        )
        terms.append(term)
        for child in children:
            visit(child, term)

    for item in children_of(conn, section["id"]):
        if item["kind"] == "item" and item["label"] == ENTRY:
            visit(item, None)
    return terms


def collection_terms(
    conn: sqlite3.Connection,
    section: sqlite3.Row,
    gaps: list[tuple[int, int]],
    known: set[str],
) -> list[Term]:
    """Return the collections of a collections index section, each with the works listed under it."""
    terms = []
    for item in children_of(conn, section["id"]):
        if item["kind"] != "item":
            continue
        below = children_of(conn, item["id"])
        label = own_text(conn, item, below, gaps)
        term = Term(item["id"], label, "collection", [], [label])
        for attribution in below:
            works = (
                [attribution]
                if attribution["label"] == WORK
                else children_of(conn, attribution["id"])
            )
            attributed = (
                own_text(conn, attribution, works, gaps).rstrip(":")
                if attribution["label"] == ATTRIBUTION
                else None
            )
            for work in works:
                text = own_text(conn, work, [], gaps)
                match = WORK_TEXT.match(text)
                number = match["number"].strip() if match else None
                term.works.append(
                    Work(
                        work["id"],
                        attributed,
                        f"{match['label']} {number}" if match else None,
                        entry_number(number, known) if number else None,
                        match["copy"] if match else None,
                        parse_references(match["refs"] or "") if match else [],
                    )
                )
        terms.append(term)
    return terms


def known_entries(conn: sqlite3.Connection, run_id: int, part: str) -> set[str]:
    """Return the catalogue numbers of the entries of a part in a segmentation run."""
    return {
        label
        for (label,) in conn.execute(
            "SELECT s.label FROM segments s JOIN documents d ON d.id = s.document_id"
            " WHERE s.run_id = ? AND s.kind = 'entry' AND d.part = ?",
            (run_id, part),
        )
    }


def remove_old_terms(conn: sqlite3.Connection) -> int:
    """Delete the index terms of an earlier run, unless a normalisation refers to them; return how many."""
    used = conn.execute(
        "SELECT COUNT(*) FROM clusters c JOIN control_terms t ON t.id = c.term_id WHERE t.vocabulary = ?",
        (VOCABULARY,),
    ).fetchone()[0]
    if used:
        raise SystemExit(
            "the index terms are used by a normalisation run; they are not replaced"
        )
    conn.execute(
        "DELETE FROM index_references WHERE term_id IN (SELECT id FROM control_terms WHERE vocabulary = ?)",
        (VOCABULARY,),
    )
    return conn.execute(
        "DELETE FROM control_terms WHERE vocabulary = ?", (VOCABULARY,)
    ).rowcount


def store(
    conn: sqlite3.Connection, terms: list[Term], part: str, source: str, now: str
) -> Counter[str]:
    """Store terms and their references; return counts."""
    counts: Counter[str] = Counter()
    ids: dict[int, int] = {}
    for term in terms:
        extra = {"part": part, "path": term.path}
        if term.parent is not None:
            extra["broader"] = ids[term.parent]
        term_id = conn.execute(
            "INSERT INTO control_terms (vocabulary, label, type, extra, source, retrieved_at, segment_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                VOCABULARY,
                term.label,
                term.type,
                json.dumps(extra, ensure_ascii=False),
                source,
                now,
                term.segment_id,
            ),
        ).lastrowid
        assert term_id is not None
        ids[term.segment_id] = term_id
        counts[f"terms: {term.type or 'no type'}"] += 1
        rows = [
            (
                term_id,
                term.segment_id,
                part,
                r.page,
                r.note,
                r.figure,
                None,
                None,
                None,
                None,
            )
            for r in term.references
        ]
        for work in term.works:
            rows += [
                (
                    term_id,
                    work.segment_id,
                    part,
                    r.page,
                    r.note,
                    r.figure,
                    work.entry_number,
                    work.entry_text,
                    work.copy,
                    work.attribution,
                )
                for r in work.references or [Reference(None)]
            ]
            counts["collection works"] += 1
            counts["collection works with a catalogue number of the part"] += (
                work.entry_number is not None
            )
        conn.executemany(
            "INSERT INTO index_references (term_id, segment_id, part, printed_page, note_number, figure,"
            " entry_number, entry_text, copy_text, attribution) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        counts["references"] += len(rows)
    return counts


def build(conn: sqlite3.Connection) -> Counter[str]:
    """Replace the index terms with those of the active segmentation run; return counts."""
    run_id = active_run(conn, SEGMENTATION_STEP)
    if run_id is None:
        raise SystemExit(
            "no active segmentation run; accept one first (crlb set-active <db> 3 <run>)"
        )
    counts: Counter[str] = Counter()
    counts["old terms removed"] = remove_old_terms(conn)
    now, source = utc_now(), f"segmentation run {run_id}"
    sections = conn.execute(
        "SELECT s.*, d.part FROM segments s JOIN documents d ON d.id = s.document_id"
        " WHERE s.run_id = ? AND s.kind = 'section' AND s.label IN (?, ?) ORDER BY s.id",
        (run_id, *LAYOUTS),
    ).fetchall()
    for section in sections:
        gaps = [
            (row["first_word_id"], row["last_word_id"])
            for row in children_of(conn, section["id"])
            if row["kind"] == "field" and row["label"] == "introduction"
        ]
        if LAYOUTS[section["label"]] == NAMES:
            terms = names_terms(conn, section, gaps)
        else:
            terms = collection_terms(
                conn, section, gaps, known_entries(conn, run_id, section["part"])
            )
        part_counts = store(conn, terms, section["part"], source, now)
        for name, value in part_counts.items():
            counts[f"{section['part']}, {section['label']}: {name}"] += value
    conn.commit()
    return counts


def configure(parser: argparse.ArgumentParser) -> None:
    """Add the arguments of this command to its parser."""
    parser.add_argument("db", type=Path, help="crlb.sqlite")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Build the index terms and print the counts."""
    conn = db.connect(args.db)
    for name, value in sorted(build(conn).items()):
        print(f"  {name}: {value}")
    conn.close()
