"""The input of step 4: the entries of the active segmentation run, as trees of segments with their text."""

import itertools
import sqlite3
from dataclasses import dataclass, field

from crlb import text
from crlb.sample import SampleItem


@dataclass
class Node:
    """A segment of step 3 with its effective text and its children."""

    id: int
    kind: str
    label: str | None
    first: int
    last: int
    link_id: int | None
    text: str
    children: list[Node] = field(default_factory=list)

    def fields(self, label: str) -> list[Node]:
        """Return the child fields with this label."""
        return [c for c in self.children if c.kind == "field" and c.label == label]

    def field(self, label: str) -> Node | None:
        """Return the first child field with this label, if any."""
        found = self.fields(label)
        return found[0] if found else None


@dataclass
class Entry:
    """A catalogue entry to extract: its part, number and segment tree."""

    part: str
    number: str
    node: Node


def joined_text(conn: sqlite3.Connection, first: int, last: int) -> str:
    """Return the effective text of a word range, with words broken by a hyphen at the end of a line rejoined."""
    tokens = text.tokens(conn, first, last)
    if not tokens:
        return ""
    lines = {
        word_id: (page_id, block_no, line_no)
        for word_id, page_id, block_no, line_no in conn.execute(
            "SELECT id, page_id, block_no, line_no FROM words WHERE id BETWEEN ? AND ?",
            (first, last),
        )
    }
    parts = [tokens[0].text]
    for previous, token in itertools.pairwise(tokens):
        # 'Plantin-' at the end of a line and 'Moretus' on the next: one word
        broken = (
            previous.text.endswith("-")
            and len(previous.text) > 1
            and lines[previous.last_word_id] != lines[token.first_word_id]
        )
        parts.append(token.text if broken else " " + token.text)
    return "".join(parts)


def load_node(conn: sqlite3.Connection, row: sqlite3.Row) -> Node:
    """Return a segment and its descendants as a tree of nodes."""
    node = Node(
        row["id"],
        row["kind"],
        row["label"],
        row["first_word_id"],
        row["last_word_id"],
        row["link_id"],
        joined_text(conn, row["first_word_id"], row["last_word_id"]),
    )
    node.children = [
        load_node(conn, child)
        for child in conn.execute(
            "SELECT * FROM segments WHERE parent_id = ? ORDER BY first_word_id",
            (row["id"],),
        ).fetchall()
    ]
    return node


def segmentation_run(conn: sqlite3.Connection) -> int:
    """Return the active segmentation run; step 4 reads only an accepted segmentation."""
    run_id = text.active_run(conn, text.SEGMENTATION_STEP)
    if run_id is None:
        raise SystemExit(
            "no active segmentation run; accept one first (crlb set-active <db> 3 <run>)"
        )
    return run_id


def load_entries(
    conn: sqlite3.Connection, run_id: int, sample: list[SampleItem] | None
) -> list[Entry]:
    """Return the entries of the main documents in a segmentation run, restricted to the sample if given."""
    rows = conn.execute(
        "SELECT s.*, d.part FROM segments s JOIN documents d ON d.id = s.document_id"
        " WHERE s.run_id = ? AND s.kind = 'entry' AND d.section = 'main' ORDER BY s.document_id, s.first_word_id",
        (run_id,),
    ).fetchall()
    wanted = None if sample is None else {(item.part, item.number) for item in sample}
    entries = []
    for row in rows:
        if wanted is not None and not (
            (row["part"], row["label"]) in wanted or (row["part"], None) in wanted
        ):
            continue
        entries.append(Entry(row["part"], row["label"], load_node(conn, row)))
    return entries


def insert(
    conn: sqlite3.Connection,
    table: str,
    node: Node,
    run_id: int,
    **values: str | float | None,
) -> int:
    """Insert an extracted row anchored to a segment (its id and word range); return its id."""
    columns = {
        "segment_id": node.id,
        "first_word_id": node.first,
        "last_word_id": node.last,
        "run_id": run_id,
        **values,
    }
    row_id = conn.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
        tuple(columns.values()),
    ).lastrowid
    assert row_id is not None
    return row_id
