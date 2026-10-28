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
from crlb.text import TextToken, furniture_ranges, raw_tokens, tokens

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
    (0.45, 0.65, 0.20),
    (0.90, 0.45, 0.35),
    (0.40, 0.40, 0.75),
    (0.70, 0.55, 0.70),
]
FURNITURE = (0.55, 0.55, 0.55)
OTHER_ENTRY = (0.85, 0.85, 0.85)
LINK = (0.8, 0.1, 0.1)  # outline of an RKD link

STYLE = """
body { font-family: Georgia, serif; margin: 1.5em; color: #222; }
.view { display: grid; grid-template-columns: minmax(12em, 1fr) minmax(0, 3fr); gap: 2em; align-items: start; }
.legend { list-style: none; padding: 0; margin: 0; position: sticky; top: 1em; font-size: 0.9em; line-height: 1.7; }
section { margin-bottom: 3em; }
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
    conn: sqlite3.Connection,
    first: int,
    last: int,
    correction_run: int | None,
    segmentation_run: int,
) -> list[TextToken]:
    """Return the tokens of a word range without the run's furniture: corrected with the run's correction run, else raw."""
    if correction_run is None:
        ranges = furniture_ranges(conn, first, last, segmentation_run)
        return [
            t
            for t in raw_tokens(conn, first, last)
            if not any(a <= t.first_word_id <= b for a, b in ranges)
        ]
    return tokens(conn, first, last, correction_run, segmentation_run)


def part_name(seg: sqlite3.Row) -> str:
    """Return the name of a segment in a legend path: fields by name; items and notes alternate, so each boundary shows."""
    if seg["kind"] == "field":
        return seg["label"] or "field"
    if seg["kind"] in ("item", "note") and seg["label"] and seg["label"].isdigit():
        return f"{seg['kind']} ({'odd' if int(seg['label']) % 2 else 'even'})"
    return seg["kind"]


def descendants(
    segments: list[sqlite3.Row], root_id: int
) -> list[tuple[int, sqlite3.Row, str]]:
    """Return the segments under a root, depth first, with their depth below it and their path ('copies › copy › object')."""
    children: dict[int, list[sqlite3.Row]] = {}
    for seg in segments:
        if seg["parent_id"] is not None:
            children.setdefault(seg["parent_id"], []).append(seg)
    result = []

    def walk(seg_id: int, depth: int, path: list[str]) -> None:
        """Add the children of a segment, depth first."""
        for child in sorted(children.get(seg_id, []), key=lambda s: s["first_word_id"]):
            child_path = [*path, part_name(child)]
            result.append((depth, child, " › ".join(child_path)))
            walk(child["id"], depth + 1, child_path)

    walk(root_id, 1, [])
    return result


def render_page(
    page: pymupdf.Page,
    conn: sqlite3.Connection,
    page_id: int,
    shown: list[tuple[int, sqlite3.Row, str]],
    others: list[sqlite3.Row],
    colours: dict[str, tuple[float, float, float]],
) -> str:
    """Return a page as a base64 PNG with its words filled in the colour of their innermost shown segment and the RKD links outlined."""
    for word_id, x0, y0, x1, y1 in conn.execute(
        "SELECT id, x0, y0, x1, y1 FROM words WHERE page_id = ?", (page_id,)
    ).fetchall():
        colour = None
        depth_found = -1
        for depth, seg, key in shown:
            if (
                seg["first_word_id"] <= word_id <= seg["last_word_id"]
                and depth > depth_found
            ):
                colour, depth_found = colours[key], depth
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


def swatch(name: str, colour: tuple[float, float, float], outline: bool = False) -> str:
    """Return a legend entry with its colour."""
    rgb = f"rgb({colour[0] * 255:.0f},{colour[1] * 255:.0f},{colour[2] * 255:.0f})"
    style = f"border-color: {rgb}" if outline else f"background: {rgb}"
    return f'<li><span class="swatch{" link" if outline else ""}" style="{style}"></span>{html.escape(name)}</li>'


def view_html(
    conn: sqlite3.Connection,
    document_id: int,
    pages: list[tuple[int, int]],
    shown: list[tuple[int, sqlite3.Row, str]],
    others: list[sqlite3.Row],
    title: str,
    explanation: str,
) -> str:
    """Return one view of the entry: its pages coloured by the shown segments, with the legend of those segments."""
    colours: dict[str, tuple[float, float, float]] = {}
    for _, _, key in shown:
        colours.setdefault(key, PALETTE[len(colours) % len(PALETTE)])
    # A fresh copy of the PDF per view, as drawing changes the pages
    pdf = db.open_pdf(conn, document_id)
    images = "".join(
        f'<img alt="PDF page {index + 1}" src="data:image/png;base64,'
        f'{render_page(pdf[index], conn, page_id, shown, others, colours)}">'
        for page_id, index in pages
    )
    legend = "".join(swatch(key, colour) for key, colour in colours.items())
    legend += swatch("furniture (running head, page number)", FURNITURE) + swatch(
        "other entries", OTHER_ENTRY
    )
    legend += swatch("RKD link", LINK, outline=True)
    return f"""<section><h2>{html.escape(title)}</h2><p>{html.escape(explanation)}</p>
<div class="view"><ul class="legend">{legend}</ul><div class="pages">{images}</div></div></section>"""


def entry_html(
    conn: sqlite3.Connection,
    run_id: int,
    document_id: int,
    entry: sqlite3.Row,
    title: str,
) -> str:
    """Return the HTML view of one entry: its fields, what lies inside them, and the segment tree."""
    segments = conn.execute(
        "SELECT * FROM segments WHERE run_id = ? AND document_id = ? ORDER BY first_word_id",
        (run_id, document_id),
    ).fetchall()
    correction_run = conn.execute(
        "SELECT correction_run_id FROM segmentation_runs WHERE id = ?", (run_id,)
    ).fetchone()[0]
    tree = descendants(segments, entry["id"])
    shown_ids = {entry["id"]} | {seg["id"] for _, seg, _ in tree}
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
    entry_row = [(0, entry, "entry (outside its fields)")]
    fields_view = view_html(
        conn,
        document_id,
        pages,
        entry_row + [t for t in tree if t[0] == 1],
        others,
        "1. The fields of the entry",
        "Each field is one block: the heading, material, location and date, the labelled fields "
        "(provenance, exhibited, copies, literature, ...), the description and the notes.",
    )
    inside_view = view_html(
        conn,
        document_id,
        pages,
        [t for t in tree if t[0] > 1],
        others,
        "2. Inside the fields",
        "The parts found within the fields: each copy in a copies field with its own description "
        "('object'), provenance and literature; the items of the list fields, split at ';'; the "
        "single notes. The path shows where a part lies, e.g. 'copies › copy › provenance › item'. "
        "Items and notes alternate between two colours, so every split is visible; fields without "
        "parts stay white.",
    )
    rows = []
    for depth, seg, _ in [(0, entry, ""), *tree]:
        text = " ".join(
            t.text
            for t in segment_text(
                conn, seg["first_word_id"], seg["last_word_id"], correction_run, run_id
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
<p>Segmentation run {run_id}; PDF pages {first_page + 1}–{last_page + 1}. Each word is filled in the colour
of the segment it belongs to.</p>
{fields_view}
{inside_view}
<section><h2>3. The segment tree</h2>
<table><tr><th>Kind</th><th>Label</th><th>Rule</th><th>Confidence</th><th>Reason</th><th>Text</th></tr>
{"".join(rows)}</table></section>"""
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
