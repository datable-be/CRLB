"""List the catalogue entries of a document with their structure, for choosing entries to check or work on.

One line per entry: number, PDF pages, confidence, RKD link, and per labelled
field the number of items (or copies). No CRLB text is printed.
"""

import argparse
import sqlite3
from pathlib import Path

from crlb import db
from crlb.correction.show import find_document
from crlb.segmentation.show import segmentation_run

COLUMNS = ["provenance", "exhibited", "copies", "literature", "description", "notes"]


def entry_rows(
    conn: sqlite3.Connection, run_id: int, document_id: int
) -> list[dict[str, str | int]]:
    """Return one row per entry: number, pages, confidence, link and counts per field."""
    rows = []
    entries = conn.execute(
        "SELECT * FROM segments WHERE run_id = ? AND document_id = ? AND kind = 'entry' ORDER BY first_word_id",
        (run_id, document_id),
    ).fetchall()
    for entry in entries:
        pages = conn.execute(
            "SELECT min(p.page_index) + 1, max(p.page_index) + 1 FROM words w JOIN pages p ON p.id = w.page_id"
            " WHERE w.id IN (?, ?)",
            (entry["first_word_id"], entry["last_word_id"]),
        ).fetchone()
        row: dict[str, str | int] = {
            "entry": entry["label"],
            "pages": f"{pages[0]}-{pages[1]}"
            if pages[0] != pages[1]
            else str(pages[0]),
            "confidence": entry["confidence"],
            "link": "yes" if entry["link_id"] else "no",
        }
        for name in COLUMNS:
            fields = conn.execute(
                "SELECT id FROM segments WHERE run_id = ? AND parent_id = ? AND kind = 'field' AND label = ?",
                (run_id, entry["id"], name),
            ).fetchall()
            if not fields:
                row[name] = "-"
                continue
            # Count the parts of the field: items, copies or notes; 'x' for a field without parts
            parts = sum(
                conn.execute(
                    "SELECT count(*) FROM segments WHERE parent_id = ?", (f[0],)
                ).fetchone()[0]
                for f in fields
            )
            row[name] = parts if parts else "x"
        rows.append(row)
    return rows


def configure(parser: argparse.ArgumentParser) -> None:
    """Add the arguments of this command to its parser."""
    parser.add_argument("db", type=Path, help="crlb.sqlite")
    parser.add_argument("document", help="part of the document's path, e.g. 19_4_links")
    parser.add_argument(
        "--run",
        type=int,
        help="segmentation run; default: the active one, else the latest",
    )
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Print the entry list of a document."""
    conn = db.connect(args.db)
    run_id = segmentation_run(conn, args.run)
    document_id, path = find_document(conn, args.document)
    rows = entry_rows(conn, run_id, document_id)
    print(f"{path}, segmentation run {run_id}: {len(rows)} entries")
    print(
        "per field: number of items (provenance, exhibited, literature), copies or notes; x = field without parts"
    )
    header = ["entry", "pages", "confidence", "link", *COLUMNS]
    widths = (
        [max(len(h), *(len(str(r[h])) for r in rows)) for h in header]
        if rows
        else [len(h) for h in header]
    )
    print("  ".join(h.ljust(w) for h, w in zip(header, widths, strict=True)))
    for row in rows:
        print(
            "  ".join(str(row[h]).ljust(w) for h, w in zip(header, widths, strict=True))
        )
    conn.close()
