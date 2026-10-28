"""Write a side-by-side view of raw and corrected pages, for checking a correction run before making it active.

For each requested page an HTML file is written to the output directory: the
raw text on the left, the corrected text on the right, the joins coloured by
rule (hover for the pieces and the reason), the flagged cases underlined, and
a table of all changes and flags below. CRLB text goes only into these local
files; the console shows the file names and counts.
"""

import argparse
import html
import sqlite3
from pathlib import Path

from crlb import db
from crlb.correction.measure import latest_run
from crlb.text import page_tokens

STYLE = """
body { font-family: Georgia, serif; margin: 1.5em; color: #222; }
.columns { display: grid; grid-template-columns: 1fr 1fr; gap: 2em; }
.page { white-space: pre-wrap; line-height: 1.5; border: 1px solid #ccc; padding: 1em; }
.R1 { background: #cde4ff; } .R2 { background: #ffe8a8; } .R3 { background: #d4f5d0; }
.flag { text-decoration: underline wavy #c0392b; }
table { border-collapse: collapse; margin-top: 2em; font-size: 0.9em; }
td, th { border: 1px solid #ccc; padding: 0.2em 0.5em; text-align: left; vertical-align: top; }
"""


def find_document(conn: sqlite3.Connection, name: str) -> tuple[int, str]:
    """Return the id and path of the one document whose path contains name."""
    rows = conn.execute(
        "SELECT id, path FROM documents WHERE instr(path, ?) > 0", (name,)
    ).fetchall()
    if len(rows) != 1:
        raise SystemExit(
            f"{name!r} matches {len(rows)} documents; give a more specific part of the path"
        )
    return rows[0][0], rows[0][1]


def page_html(
    conn: sqlite3.Connection, page_id: int, run_id: int, title: str
) -> tuple[str, int, int]:
    """Return the HTML view of one page, with its number of joins and flags."""
    words = dict(
        conn.execute(
            "SELECT id, text FROM words WHERE page_id = ?", (page_id,)
        ).fetchall()
    )
    joins = conn.execute(
        "SELECT first_word_id, last_word_id, text, rule, reason FROM corrected_words"
        " WHERE run_id = ? AND page_id = ? AND rule IS NOT NULL ORDER BY first_word_id",
        (run_id, page_id),
    ).fetchall()
    flags = conn.execute(
        "SELECT first_word_id, last_word_id, rule, candidate, reason FROM correction_flags"
        " WHERE run_id = ? AND page_id = ? ORDER BY first_word_id",
        (run_id, page_id),
    ).fetchall()

    def pieces(first: int, last: int) -> str:
        """Return the raw words of a range, separated by '|'."""
        return "|".join(words[i] for i in range(first, last + 1))

    # Which rule joined each raw word, and which flags cover it
    joined_by = {
        i: rule for first, last, _, rule, _ in joins for i in range(first, last + 1)
    }
    flagged = {}
    for first, last, rule, candidate, reason in flags:
        for i in range(first, last + 1):
            flagged.setdefault(i, []).append(f"{rule} {candidate}: {reason}")
    reasons = {
        first: f"{rule}: {pieces(first, last)} ({reason})"
        for first, last, _, rule, reason in joins
    }

    raw_parts = []
    for separator, token in page_tokens(conn, page_id, raw=True):
        classes = [joined_by.get(token.first_word_id, "")]
        notes = []
        if token.first_word_id in flagged:
            classes.append("flag")
            notes += flagged[token.first_word_id]
        attributes = f' class="{" ".join(c for c in classes if c)}" title="{html.escape("; ".join(notes))}"'
        raw_parts.append(
            html.escape(separator)
            + f"<span{attributes}>{html.escape(token.text)}</span>"
        )

    corrected_parts = []
    for separator, token in page_tokens(conn, page_id, run_id):
        text = html.escape(token.text)
        if token.first_word_id in reasons:
            rule = joined_by[token.first_word_id]
            text = f'<span class="{rule}" title="{html.escape(reasons[token.first_word_id])}">{text}</span>'
        corrected_parts.append(html.escape(separator) + text)

    rows = [
        f"<tr><td>{rule}</td><td>{html.escape(pieces(first, last))}</td><td>{html.escape(text)}</td>"
        f"<td>{html.escape(reason or '')}</td></tr>"
        for first, last, text, rule, reason in joins
    ] + [
        f"<tr><td>{rule} (flag)</td><td>{html.escape(pieces(first, last))}</td><td>{html.escape(candidate)}</td>"
        f"<td>{html.escape(reason)}</td></tr>"
        for first, last, rule, candidate, reason in flags
    ]
    body = f"""<h1>{html.escape(title)}</h1>
<p>Correction run {run_id}: {len(joins)} joins, {len(flags)} flags.
<span class="R1">R1 letter-spaced</span> <span class="R2">R2 lexicon join</span>
<span class="R3">R3 soft hyphen</span> <span class="flag">flagged, not changed</span>.
Hover over a word for the pieces and the reason.</p>
<div class="columns">
<div><h2>Raw</h2><div class="page">{"".join(raw_parts)}</div></div>
<div><h2>Corrected</h2><div class="page">{"".join(corrected_parts)}</div></div>
</div>
<table><tr><th>Rule</th><th>Raw pieces</th><th>Result or candidate</th><th>Reason</th></tr>
{"".join(rows)}</table>"""
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>{STYLE}</style></head><body>{body}</body></html>
"""
    return page, len(joins), len(flags)


def configure(parser: argparse.ArgumentParser) -> None:
    """Add the arguments of this command to its parser."""
    parser.add_argument("db", type=Path, help="crlb.sqlite")
    parser.add_argument("document", help="part of the document's path, e.g. 02_1_links")
    parser.add_argument(
        "pages", type=int, nargs="+", help="PDF page numbers, starting at 1"
    )
    parser.add_argument(
        "--run", type=int, help="correction run to show; default: the latest"
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="directory for the HTML files; default: review/ next to the database",
    )
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Write one HTML file per requested page and print where they are."""
    conn = db.connect(args.db)
    run_id = args.run if args.run is not None else latest_run(conn)
    document_id, path = find_document(conn, args.document)
    out_dir = args.out or args.db.parent / "review"
    out_dir.mkdir(parents=True, exist_ok=True)
    for number in args.pages:
        row = conn.execute(
            "SELECT id FROM pages WHERE document_id = ? AND page_index = ?",
            (document_id, number - 1),
        ).fetchone()
        if row is None:
            raise SystemExit(f"{path} has no page {number}")
        title = f"{Path(path).stem.split('-')[0]}, page {number}"
        page, joins, flags = page_html(conn, row[0], run_id, title)
        out = (
            out_dir
            / f"run{run_id}_{Path(path).stem.split('-')[0].replace(' ', '_')}_p{number:04d}.html"
        )
        out.write_text(page, encoding="utf-8")
        print(f"{out}: {joins} joins, {flags} flags")
    conn.close()
