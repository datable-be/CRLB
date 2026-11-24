"""Export each entry of the active runs as one Markdown file, in the faithful version.

The file holds the text of the entry as printed (the effective text of step 2,
without page furniture), in the structure of step 3: YAML front matter, the
heading, the unlabelled fields as paragraphs, the labelled fields under `##`
headings, the copies and the notes as numbered lists. Italics come from the
font flags of step 1, printed page breaks become HTML comments. The notes are
a section of their own until step 3 links their markers in the text (note_refs);
then they become footnotes. CRLB text goes only into these local files; the
console shows the file names and counts.
"""

import argparse
import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

from crlb import db
from crlb.extraction.source import (
    Entry,
    Node,
    broken_word,
    load_entries,
    segmentation_run,
    word_lines,
)
from crlb.sample import add_sample_option
from crlb.text import CORRECTION_STEP, SEGMENTATION_STEP, active_run, tokens

ITALIC = 2
UNLABELLED = ("heading", "material", "location", "date")
HEADINGS = {
    "provenance": "Provenance",
    "copies": "Copies",
    "exhibited": "Exhibited",
    "literature": "Literature",
    "description": "Description",
    "notes": "Notes",
}
ESCAPE = re.compile(r"([\\*_#\[\]`<>])")
LIST_START = re.compile(r"^(\d+)([.)])|^([-+])(?=\s|$)")
COPY_LABEL = re.compile(r"^\(\s*[^)\s]{1,6}\s*\)\s*")
NOTE_NUMBER = re.compile(r"^\d+\\?[.)]\s*")
# A first-line indent: further right than the column's left edge, by this much (points)
INDENT = (4.0, 25.0)
# Font sizes (points): a change of paragraph, and a line smaller than the body text.
# OCR sizes vary by half a point within a line, so small differences are noise.
SIZE_CHANGE = 1.0
SMALLER = 0.4


@dataclass(frozen=True)
class Piece:
    """A token of the effective text with what the Markdown needs: style, page and position."""

    text: str
    italic: bool
    printed: str | None  # printed page number of its page
    joined: bool  # no space before it: the rest of a word broken at the end of a line
    paragraph: bool  # it starts a new paragraph


@dataclass
class Stats:
    """Counts of what the export wrote."""

    paragraphs: int = 0
    italic_runs: int = 0
    page_breaks: int = 0


def escape(value: str) -> str:
    """Escape the characters with a meaning in Markdown."""
    return ESCAPE.sub(r"\\\1", value)


def escape_start(paragraph: str) -> str:
    """Escape what would make a paragraph start a list: '1.', '2)', '-', '+'."""
    return LIST_START.sub(
        lambda m: f"{m[1]}\\{m[2]}" if m[1] else f"\\{m[3]}", paragraph, count=1
    )


def render(pieces: list[Piece], stats: Stats) -> list[str]:
    """Return the pieces as Markdown paragraphs, with italics and page-break comments."""
    paragraphs: list[str] = []
    out: list[str] = []
    italic = False
    previous: Piece | None = None

    def close() -> None:
        """Close the open italic run and the paragraph."""
        nonlocal italic
        if italic:
            out.append("*")
            italic = False
        if out:
            paragraphs.append(escape_start("".join(out)))
            out.clear()

    for piece in pieces:
        if piece.paragraph and out:
            close()
        if out and not piece.joined:
            if italic and not piece.italic:
                out.append("*")
                italic = False
            out.append(" ")
        if previous is not None and piece.printed != previous.printed:
            out.append(f"<!-- p. {piece.printed or '?'} --> ")
            stats.page_breaks += 1
        if piece.italic and not italic and not piece.joined:
            out.append("*")
            italic = True
            stats.italic_runs += 1
        out.append(escape(piece.text))
        previous = piece
    close()
    stats.paragraphs += len(paragraphs)
    return paragraphs


def column_starts(xs: list[float]) -> list[float]:
    """Return the left edges of the text columns of a page, from the left x of its lines."""
    clusters: list[list[float]] = []
    for x in sorted(xs):
        if clusters and x - clusters[-1][-1] <= 2.5:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    frequent = [c[0] for c in clusters if len(c) >= 3]
    # An indented cluster has a column edge just left of it
    return [
        x
        for x in frequent
        if not any(INDENT[0] <= x - other <= INDENT[1] for other in frequent)
    ]


def indented(x0: float, starts: list[float]) -> bool:
    """Return whether a line starting at x0 is indented from the column it is in."""
    left = [s for s in starts if s <= x0 + 2.5]
    return bool(left) and INDENT[0] <= x0 - max(left) <= INDENT[1]


def strip_label(paragraphs: list[str], label: str) -> list[str]:
    """Remove the printed field label ('provenance:') from the start; keep the text if it isn't there."""
    if not paragraphs:
        return paragraphs
    pattern = re.compile(
        r"^\s*" + r"\s?".join(re.escape(c) for c in label) + r"\s*:\s*",
        re.IGNORECASE,
    )
    first = pattern.sub("", paragraphs[0], count=1)
    return ([first] if first else []) + paragraphs[1:]


def list_item(marker: str, paragraphs: list[str]) -> str:
    """Return a list item that starts with the printed number ('(3)', '12.'), kept as printed."""
    body = " ".join(p for p in paragraphs if p)
    return "- " + escape_start(f"{marker} {body}".strip())


def front_matter(values: dict[str, object]) -> str:
    """Return YAML front matter; every value is written as JSON, which YAML reads."""
    lines = [
        f"{key}: {json.dumps(value, ensure_ascii=False)}"
        for key, value in values.items()
    ]
    return "---\n" + "\n".join(lines) + "\n---\n"


class Exporter:
    """Writes the Markdown of entries from the database."""

    def __init__(self, conn: sqlite3.Connection, segmentation: int) -> None:
        """Keep the connection, the printed page numbers and a cache of column edges."""
        self.conn = conn
        self.stats = Stats()
        self.printed = dict(
            conn.execute(
                "SELECT page_id, printed FROM printed_pages WHERE run_id = ?",
                (segmentation,),
            ).fetchall()
        )
        self.starts: dict[int, list[float]] = {}

    def page_starts(self, page_id: int) -> list[float]:
        """Return the column edges of a page."""
        if page_id not in self.starts:
            xs = [
                x
                for (x,) in self.conn.execute(
                    "SELECT min(x0) FROM words WHERE page_id = ? GROUP BY block_no, line_no",
                    (page_id,),
                )
            ]
            self.starts[page_id] = column_starts(xs)
        return self.starts[page_id]

    def pieces(self, node: Node) -> list[Piece]:
        """Return the effective text of a segment as pieces."""
        found = tokens(self.conn, node.first, node.last)
        lines = word_lines(self.conn, node.first, node.last)
        words = {
            row["id"]: row
            for row in self.conn.execute(
                "SELECT id, page_id, x0, size, flags FROM words WHERE id BETWEEN ? AND ?",
                (node.first, node.last),
            )
        }
        # The left x and font size of each line (of its first word, and its most common size)
        line_x: dict[tuple[int, int, int], float] = {}
        line_sizes: dict[tuple[int, int, int], Counter[float]] = {}
        for word_id, line in lines.items():
            line_x[line] = min(
                line_x.get(line, words[word_id]["x0"]), words[word_id]["x0"]
            )
            line_sizes.setdefault(line, Counter())[
                round(words[word_id]["size"], 1)
            ] += 1
        size = {line: c.most_common(1)[0][0] for line, c in line_sizes.items()}
        words_per_size: Counter[float] = Counter()
        for line, sizes in line_sizes.items():
            words_per_size[size[line]] += sum(sizes.values())
        body = words_per_size.most_common(1)[0][0] if words_per_size else 0.0

        result: list[Piece] = []
        for i, token in enumerate(found):
            ids = range(token.first_word_id, token.last_word_id + 1)
            italic = sum(words[w]["flags"] & ITALIC > 0 for w in ids) * 2 > len(ids)
            line = lines[token.first_word_id]
            page_id = words[token.first_word_id]["page_id"]
            joined = paragraph = False
            if i:
                previous = found[i - 1]
                joined = broken_word(previous, token, lines)
                previous_line = lines[previous.last_word_id]
                if line != previous_line and not joined:
                    # A new paragraph at a first-line indent, or where the font size changes
                    # Indents count only in the body font: smaller lines are notes on the page
                    paragraph = abs(
                        size[line] - size[previous_line]
                    ) >= SIZE_CHANGE or (
                        body - size[line] < SMALLER
                        and indented(line_x[line], self.page_starts(page_id))
                    )
                if joined:
                    italic = result[-1].italic
            result.append(
                Piece(token.text, italic, self.printed.get(page_id), joined, paragraph)
            )
        return result

    def paragraphs(self, node: Node, split: bool = False) -> list[str]:
        """Return a segment as Markdown paragraphs; split at paragraph starts, or as one flowing paragraph."""
        pieces = self.pieces(node)
        if not split:
            pieces = [replace(p, paragraph=False) for p in pieces]
        return render(pieces, self.stats)

    def field(self, node: Node, counts: Counter[str]) -> str:
        """Return a field of an entry as Markdown."""
        label = node.label or ""
        counts[label] += 1
        if label in UNLABELLED:
            text = "\n\n".join(self.paragraphs(node))
            return (
                f"# {' '.join(text.split(chr(10) * 2))}" if label == "heading" else text
            )
        heading = f"## {HEADINGS.get(label, label.capitalize())}"
        children = [c for c in node.children if c.kind in ("copy", "note")]
        if not children:
            body = strip_label(
                self.paragraphs(node, split=label == "description"), label
            )
            return heading + "\n\n" + "\n\n".join(body)
        items = []
        for child in children:
            counts[child.kind] += 1
            text = self.paragraphs(child)
            if text:
                pattern = COPY_LABEL if child.kind == "copy" else NOTE_NUMBER
                text[0] = pattern.sub("", text[0], count=1)
            marker = child.label if child.kind == "copy" else f"{child.label}."
            items.append(list_item(marker or "", text))
        return heading + "\n\n" + "\n".join(items)

    def entry(
        self, entry: Entry, runs: dict[str, int | None]
    ) -> tuple[str, Counter[str]]:
        """Return the Markdown file of an entry, with the counts of what it contains."""
        node = entry.node
        counts: Counter[str] = Counter()
        obj = self.conn.execute(
            "SELECT title_value, object_name_label FROM ro_objects WHERE segment_id = ? AND run_id = ?",
            (node.id, runs["objects"]),
        ).fetchone()
        copies = [
            c for f in node.fields("copies") for c in f.children if c.kind == "copy"
        ]
        rkd = [
            uri
            for (uri,) in self.conn.execute(
                "SELECT l.uri FROM segments s JOIN links l ON l.id = s.link_id"
                f" WHERE s.id IN ({', '.join('?' * (len(copies) + 1))}) ORDER BY s.first_word_id",
                (node.id, *(c.id for c in copies)),
            )
        ]
        ends = self.conn.execute(
            "SELECT d.path, p.id, p.page_index FROM words w JOIN pages p ON p.id = w.page_id"
            " JOIN documents d ON d.id = p.document_id WHERE w.id IN (?, ?) ORDER BY w.id",
            (node.first, node.last),
        ).fetchall()
        document, first, last = ends[0]["path"], ends[0], ends[-1]
        meta: dict[str, object] = {
            "part": entry.part,
            "number": entry.number,
            "title": obj["title_value"] if obj else None,
            "object_name": obj["object_name_label"] if obj else None,
            "rkd": rkd,
            "document": Path(document).name,
            "pdf_pages": [first["page_index"] + 1, last["page_index"] + 1],
            "printed_pages": [
                self.printed.get(first["id"]),
                self.printed.get(last["id"]),
            ],
            "runs": runs,
        }
        body = [self.field(f, counts) for f in node.children if f.kind == "field"]
        return front_matter(meta) + "\n" + "\n\n".join(
            b for b in body if b
        ) + "\n", counts


def configure(parser: argparse.ArgumentParser) -> None:
    """Add the arguments of this command to its parser."""
    parser.add_argument("db", type=Path, help="crlb.sqlite")
    parser.add_argument(
        "--out",
        type=Path,
        help="directory for the Markdown files; default: entries/ next to the database",
    )
    add_sample_option(parser)
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Write one Markdown file per entry and print where they are, with counts."""
    conn = db.connect(args.db)
    segmentation = segmentation_run(conn)
    objects = active_run(conn, "4:objects")
    if objects is None:
        raise SystemExit(
            "no active objects run; accept one first (crlb set-active <db> 4:objects <run>)"
        )
    runs: dict[str, int | None] = {
        "correction": active_run(conn, CORRECTION_STEP),
        "segmentation": active_run(conn, SEGMENTATION_STEP),
        "objects": objects,
    }
    entries = load_entries(conn, segmentation, args.sample)
    if not entries:
        raise SystemExit("no entries in the active segmentation run match the sample")
    out_dir = args.out or args.db.parent / "entries"
    exporter = Exporter(conn, segmentation)
    for entry in entries:
        markdown, counts = exporter.entry(entry, runs)
        part = entry.part.replace(" ", "_").replace("(", "").replace(")", "")
        out = out_dir / part / f"{entry.number}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown, encoding="utf-8")
        fields = sum(n for k, n in counts.items() if k not in ("copy", "note"))
        print(
            f"{out}: {fields} fields, {counts['copy']} copies, {counts['note']} notes"
        )
    s = exporter.stats
    print(
        f"{len(entries)} files: {s.paragraphs} paragraphs, {s.italic_runs} italic runs,"
        f" {s.page_breaks} page breaks"
    )
    conn.close()
