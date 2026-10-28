"""Write an HTML view of the segmentation of catalogue entries, for checking a segmentation run before making it active.

For each requested entry an HTML file is written to the output directory: the
PDF pages of the entry, rendered from pdfs.sqlite, with every word coloured by
the segment it belongs to (the entry and its parts, page furniture,
neighbouring entries), and the segment tree of the entry with rule,
confidence, reason and text. CRLB text goes only into these local files; the
console shows the file names and counts.
"""

import argparse
import base64
import html
import sqlite3
from pathlib import Path

import pymupdf

from crlb import db
from crlb.correction.show import find_document
from crlb.text import TextToken, raw_tokens, tokens

STEP = "3"
DPI = 110
# Fill colours (RGB, 0-1) for the shown entry and its parts, in order of appearance
PALETTE = [
    (0.30, 0.55, 0.95),
    (0.95, 0.60, 0.20),
    (0.35, 0.75, 0.40),
    (0.85, 0.35, 0.55),
    (0.60, 0.45, 0.85),
    (0.20, 0.75, 0.75),
    (0.80, 0.75, 0.20),
    (0.55, 0.35, 0.25),
]
FURNITURE = (0.55, 0.55, 0.55)
OTHER_ENTRY = (0.85, 0.85, 0.85)
LINK = (0.8, 0.1, 0.1)  # outline of an RKD link

STYLE = """
body { font-family: Georgia, serif; margin: 1.5em; color: #222; }
.columns { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 2em; align-items: start; }
.pages img { width: 100%; border: 1px solid #ccc; margin-bottom: 1em; }
.swatch { display: inline-block; width: 0.9em; height: 0.9em; margin-right: 0.3em; vertical-align: middle; opacity: 0.6; }
.swatch.link { background: none; border: 2px solid; opacity: 1; box-sizing: border-box; }
table { border-collapse: collapse; font-size: 0.85em; width: 100%; }
td, th { border: 1px solid #ccc; padding: 0.2em 0.4em; text-align: left; vertical-align: top; }
td.text { white-space: pre-wrap; max-width: 40em; }
.uncertain { background: #fde2e2; } .probable { background: #fff4d6; }
"""


def segmentation_run(conn: sqlite3.Connection, run_id: int | None) -> int:
    """Return the given segmentation run, else the active one, else the latest."""
    if run_id is not None:
        return run_id
    row = conn.execute(
        "SELECT run_id FROM active_runs WHERE step = ?", (STEP,)
    ).fetchone()
    if row is not None:
        return row[0]
    latest = conn.execute("SELECT max(id) FROM segmentation_runs").fetchone()[0]
    if latest is None:
        raise SystemExit("no segmentation run yet; run crlb segment run first")
    return latest


def segment_text(
    conn: sqlite3.Connection, first: int, last: int, correction_run: int | None
) -> list[TextToken]:
    """Return the tokens of a word range: corrected with the run's correction run, else raw."""
    if correction_run is None:
        return raw_tokens(conn, first, last)
    return tokens(conn, first, last, correction_run)


def descendants(
    segments: list[sqlite3.Row], root_id: int
) -> list[tuple[int, sqlite3.Row]]:
    """Return the segments under a root, depth first, with their depth below it."""
    children: dict[int, list[sqlite3.Row]] = {}
    for seg in segments:
        if seg["parent_id"] is not None:
            children.setdefault(seg["parent_id"], []).append(seg)
    result = []

    def walk(seg_id: int, depth: int) -> None:
        """Add the children of a segment, depth first."""
        for child in sorted(children.get(seg_id, []), key=lambda s: s["first_word_id"]):
            result.append((depth, child))
            walk(child["id"], depth + 1)

    walk(root_id, 1)
    return result


def colour_key(seg: sqlite3.Row) -> str:
    """Return the legend key of a segment: its kind, with the label for fields."""
    return (
        f"{seg['kind']}: {seg['label']}"
        if seg["kind"] in ("field", "item")
        else seg["kind"]
    )


def render_page(
    doc: pymupdf.Document,
    conn: sqlite3.Connection,
    page_id: int,
    page_index: int,
    shown: list[tuple[int, sqlite3.Row]],
    others: list[sqlite3.Row],
    colours: dict[str, tuple[float, float, float]],
) -> str:
    """Return a page as a base64 PNG with its words filled in the colour of their innermost segment and the RKD links outlined."""
    page = doc[page_index]
    for word_id, x0, y0, x1, y1 in conn.execute(
        "SELECT id, x0, y0, x1, y1 FROM words WHERE page_id = ?", (page_id,)
    ).fetchall():
        colour = None
        depth_found = -1
        for depth, seg in shown:
            if (
                seg["first_word_id"] <= word_id <= seg["last_word_id"]
                and depth > depth_found
            ):
                colour, depth_found = colours[colour_key(seg)], depth
        for seg in others:
            if seg["first_word_id"] <= word_id <= seg["last_word_id"]:
                colour = (
                    FURNITURE if seg["kind"] == "furniture" else (colour or OTHER_ENTRY)
                )
        if colour is not None:
            page.draw_rect(
                pymupdf.Rect(x0, y0, x1, y1),
                color=None,
                fill=colour,
                fill_opacity=0.35,
                width=0,
            )
    # The link tool's own highlight annotations are hidden; the links are outlined instead
    for x0, y0, x1, y1 in conn.execute(
        "SELECT x0, y0, x1, y1 FROM links WHERE page_id = ? AND kind = 'uri'",
        (page_id,),
    ).fetchall():
        page.draw_rect(pymupdf.Rect(x0, y0, x1, y1), color=LINK, width=0.8)
    pixmap = page.get_pixmap(dpi=DPI, annots=False)
    return base64.b64encode(pixmap.tobytes("png")).decode("ascii")


def entry_html(
    conn: sqlite3.Connection,
    run_id: int,
    document_id: int,
    entry: sqlite3.Row,
    title: str,
) -> str:
    """Return the HTML view of one entry."""
    segments = conn.execute(
        "SELECT * FROM segments WHERE run_id = ? AND document_id = ? ORDER BY first_word_id",
        (run_id, document_id),
    ).fetchall()
    correction_run = conn.execute(
        "SELECT correction_run_id FROM segmentation_runs WHERE id = ?", (run_id,)
    ).fetchone()[0]
    shown = [(0, entry), *descendants(segments, entry["id"])]
    shown_ids = {seg["id"] for _, seg in shown}
    colours: dict[str, tuple[float, float, float]] = {}
    for _, seg in shown:
        colours.setdefault(colour_key(seg), PALETTE[len(colours) % len(PALETTE)])
    pages = conn.execute(
        "SELECT DISTINCT p.id, p.page_index FROM words w JOIN pages p ON p.id = w.page_id"
        " WHERE w.id BETWEEN ? AND ? ORDER BY p.page_index",
        (entry["first_word_id"], entry["last_word_id"]),
    ).fetchall()
    first_page, last_page = pages[0][1], pages[-1][1]
    page_words = conn.execute(
        "SELECT min(w.id), max(w.id) FROM words w JOIN pages p ON p.id = w.page_id"
        " WHERE p.document_id = ? AND p.page_index BETWEEN ? AND ?",
        (document_id, first_page, last_page),
    ).fetchone()
    others = [
        s
        for s in segments
        if s["id"] not in shown_ids
        and s["kind"] in ("furniture", "entry")
        and s["last_word_id"] >= page_words[0]
        and s["first_word_id"] <= page_words[1]
    ]
    pdf = db.open_pdf(conn, document_id)
    images = "".join(
        f'<img alt="PDF page {index + 1}" src="data:image/png;base64,'
        f'{render_page(pdf, conn, page_id, index, shown, others, colours)}">'
        for page_id, index in pages
    )
    legend = " ".join(
        f'<span><span class="swatch" style="background: rgb({r * 255:.0f},{g * 255:.0f},{b * 255:.0f})"></span>{html.escape(key)}</span>'
        for key, (r, g, b) in [
            *colours.items(),
            ("furniture", FURNITURE),
            ("other entries", OTHER_ENTRY),
        ]
    ) + (
        f' <span><span class="swatch link" style="border-color: rgb({LINK[0] * 255:.0f},'
        f'{LINK[1] * 255:.0f},{LINK[2] * 255:.0f})"></span>RKD link</span>'
    )
    rows = []
    for depth, seg in shown:
        text = " ".join(
            t.text
            for t in segment_text(
                conn, seg["first_word_id"], seg["last_word_id"], correction_run
            )
        )
        if seg["kind"] == "entry":
            text = text[:400] + (" …" if len(text) > 400 else "")
        rows.append(
            f'<tr class="{seg["confidence"]}"><td>{"&nbsp;" * 4 * depth}{html.escape(seg["kind"])}</td>'
            f"<td>{html.escape(seg['label'] or '')}</td><td>{html.escape(seg['rule'])}</td>"
            f"<td>{seg['confidence']}</td><td>{html.escape(seg['reason'] or '')}</td>"
            f'<td class="text">{html.escape(text)}</td></tr>'
        )
    body = f"""<h1>{html.escape(title)}</h1>
<p>Segmentation run {run_id}; PDF pages {first_page + 1}–{last_page + 1}. Each word is filled in the colour of its segment: {legend}</p>
<div class="columns">
<div class="pages">{images}</div>
<div><table><tr><th>Kind</th><th>Label</th><th>Rule</th><th>Confidence</th><th>Reason</th><th>Text</th></tr>
{"".join(rows)}</table></div>
</div>"""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>{STYLE}</style></head><body>{body}</body></html>
"""


def configure(parser: argparse.ArgumentParser) -> None:
    """Add the arguments of this command to its parser."""
    parser.add_argument(
        "db", type=Path, help="crlb.sqlite (with pdfs.sqlite next to it)"
    )
    parser.add_argument("document", help="part of the document's path, e.g. 19_4_links")
    parser.add_argument("entries", nargs="+", help="entry numbers, e.g. 22 10a R3")
    parser.add_argument(
        "--run",
        type=int,
        help="segmentation run to show; default: the active one, else the latest",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="directory for the HTML files; default: review/ next to the database",
    )
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Write one HTML file per requested entry and print where they are."""
    conn = db.connect(args.db)
    db.attach_pdfs(conn, args.db.parent / "pdfs.sqlite")
    run_id = segmentation_run(conn, args.run)
    document_id, path = find_document(conn, args.document)
    out_dir = args.out or args.db.parent / "review"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = Path(path).stem.split("-")[0].replace(" ", "_")
    for number in args.entries:
        entry = conn.execute(
            "SELECT * FROM segments WHERE run_id = ? AND document_id = ? AND kind = 'entry' AND label = ?",
            (run_id, document_id, number),
        ).fetchone()
        if entry is None:
            raise SystemExit(
                f"no entry {number} in {path} in segmentation run {run_id}"
            )
        out = out_dir / f"segment_run{run_id}_{name}_No{number}.html"
        out.write_text(
            entry_html(conn, run_id, document_id, entry, f"{name}, No. {number}"),
            encoding="utf-8",
        )
        parts = conn.execute(
            "SELECT count(*) FROM segments WHERE run_id = ? AND parent_id = ?",
            (run_id, entry["id"]),
        ).fetchone()[0]
        print(f"{out}: {parts} parts, confidence {entry['confidence']}")
    conn.close()
