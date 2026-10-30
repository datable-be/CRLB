"""Write an HTML review page per entry of the active step 4 runs: the PDF pages next to the extracted records.

For each entry of --sample one HTML file is written to the review directory:
on the left the PDF pages of the entry, with every provenance stage coloured
by how it was extracted (rules, the LLM, or not at all); on the right the
objects of the entry (the entry and its copies) with their identifiers,
attributions, dimensions, provenance chain, exhibitions and literature, and
the rejected LLM answers. Pointing at a row highlights its source words in the
PDF; clicking it scrolls the PDF to them. CRLB text goes only into these local
files; the console shows the file names and counts.
"""

import argparse
import base64
import html
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from crlb import db
from crlb.extraction.references import object_nodes
from crlb.extraction.source import Entry, Node, load_entries, segmentation_run
from crlb.sample import add_sample_option
from crlb.text import active_run

DPI = 110
FIELDS = ("objects", "references", "provenance")

STYLE = """
:root { --rules: 48,110,220; --llm: 230,130,20; --none: 210,40,40; --hover: 250,215,0; }
* { box-sizing: border-box; }
body { font-family: Georgia, serif; margin: 0; color: #222; background: #fafaf7; }
header { padding: 0.8em 1.5em; border-bottom: 1px solid #ddd; background: #fff; }
header h1 { margin: 0 0 0.2em; font-size: 1.4em; }
header p { margin: 0.2em 0; font-size: 0.9em; }
.view { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
.pdf { position: sticky; top: 0; height: 100vh; overflow-y: auto; padding: 1em; background: #eee; }
.page { position: relative; margin-bottom: 1em; box-shadow: 0 1px 4px rgba(0,0,0,0.25); }
.page img { display: block; width: 100%; }
.box { position: absolute; border-radius: 2px; pointer-events: none; }
.box.stage { opacity: 0.28; }
.box.rules { background: rgb(var(--rules)); }
.box.llm { background: rgb(var(--llm)); }
.box.none { background: rgb(var(--none)); }
.box.mark { display: none; background: rgba(var(--hover), 0.55); outline: 2px solid rgb(200,150,0); }
.box.mark.on { display: block; }
.records { padding: 1em 1.5em 4em; font-size: 0.9em; }
.object { background: #fff; border: 1px solid #ddd; border-radius: 6px; padding: 0.8em 1em; margin-bottom: 1.5em; }
.object h2 { margin: 0 0 0.5em; font-size: 1.15em; }
h3 { font-size: 0.95em; margin: 1.1em 0 0.3em; color: #555; text-transform: uppercase; letter-spacing: 0.04em; }
table { border-collapse: collapse; width: 100%; }
td, th { border-bottom: 1px solid #e5e5e5; padding: 0.25em 0.4em; text-align: left; vertical-align: top; }
th { font-weight: normal; color: #777; font-size: 0.85em; }
table.props th { width: 11em; }
tr[data-key] { cursor: pointer; }
tr[data-key]:hover { background: rgba(var(--hover), 0.25); }
.badge { display: inline-block; padding: 0 0.45em; border-radius: 0.7em; font-size: 0.8em; color: #fff; font-family: sans-serif; }
.badge.rules { background: rgb(var(--rules)); }
.badge.llm { background: rgb(var(--llm)); }
.badge.none { background: rgb(var(--none)); }
.swatch { display: inline-block; width: 0.9em; height: 0.9em; vertical-align: middle; opacity: 0.5; margin: 0 0.2em 0 0.8em; }
.muted { color: #888; }
.mapped { color: #2a7a2a; }
pre { white-space: pre-wrap; font-size: 0.85em; margin: 0.2em 0; }
.legend { font-size: 0.85em; }
"""

SCRIPT = """
document.querySelectorAll('tr[data-key]').forEach(row => {
  const boxes = () => document.querySelectorAll('.box.mark.k' + row.dataset.key);
  row.addEventListener('mouseenter', () => boxes().forEach(b => b.classList.add('on')));
  row.addEventListener('mouseleave', () => boxes().forEach(b => b.classList.remove('on')));
  row.addEventListener('click', () => {
    const first = boxes()[0];
    if (first) first.scrollIntoView({behavior: 'smooth', block: 'center'});
  });
});
"""


@dataclass
class Box:
    """A rectangle on a PDF page, in points."""

    page_id: int
    x0: float
    y0: float
    x1: float
    y1: float


def line_boxes(
    words: Iterable[tuple[int, int, int, float, float, float, float]],
) -> list[Box]:
    """Return one box per line for words given as (page_id, block_no, line_no, x0, y0, x1, y1)."""
    lines: dict[tuple[int, int, int], Box] = {}
    for page_id, block_no, line_no, x0, y0, x1, y1 in words:
        box = lines.get((page_id, block_no, line_no))
        if box is None:
            lines[(page_id, block_no, line_no)] = Box(page_id, x0, y0, x1, y1)
        else:
            box.x0, box.y0 = min(box.x0, x0), min(box.y0, y0)
            box.x1, box.y1 = max(box.x1, x1), max(box.y1, y1)
    return list(lines.values())


def covered(item: Node, ranges: list[tuple[int, int]]) -> bool:
    """Return whether any of the word ranges overlaps the item."""
    return any(first <= item.last and last >= item.first for first, last in ranges)


class Page:
    """Builds the review page of one entry: the PDF boxes and the record tables."""

    def __init__(
        self, conn: sqlite3.Connection, entry: Entry, runs: dict[str, int]
    ) -> None:
        """Remember the entry and the active runs, and number the highlighted rows."""
        self.conn, self.entry, self.runs = conn, entry, runs
        self.boxes: list[tuple[Box, str]] = []  # (box, CSS classes)
        self.keys = 0

    def words(self, first: int, last: int) -> list[Box]:
        """Return the line boxes of a word range."""
        return line_boxes(
            self.conn.execute(
                "SELECT page_id, block_no, line_no, x0, y0, x1, y1 FROM words WHERE id BETWEEN ? AND ?",
                (first, last),
            ).fetchall()
        )

    def key(self, first: int, last: int) -> str:
        """Add hidden highlight boxes for a word range and return the key that shows them."""
        self.keys += 1
        for box in self.words(first, last):
            self.boxes.append((box, f"mark k{self.keys}"))
        return str(self.keys)

    def row(self, first: int, last: int, cells: Iterable[str]) -> str:
        """Return a table row (cells already HTML) that highlights its word range."""
        tds = "".join(f"<td>{cell}</td>" for cell in cells)
        return f'<tr data-key="{self.key(first, last)}">{tds}</tr>'

    def rows(self, table: str, field: str, object_id: int) -> list[sqlite3.Row]:
        """Return the rows of a table for an object in the active run of a field."""
        return self.conn.execute(
            f"SELECT * FROM {table} WHERE object_id = ? AND run_id = ? ORDER BY first_word_id, id",
            (object_id, self.runs[field]),
        ).fetchall()

    def object_section(self, owner: Node, obj: sqlite3.Row) -> str:
        """Return the record of one object: its properties and its related rows."""
        props = [
            ("Title", text(obj["title_value"])),
            ("Object name", mapped(obj["object_name_text"], obj["object_name_label"])),
            (
                "Date",
                mapped(
                    obj["production_date_label"],
                    date_range(
                        obj["production_date_start"], obj["production_date_end"]
                    ),
                ),
            ),
            ("Material", mapped(obj["material_note"], obj["material_support_label"])),
            (
                "Lost or destroyed",
                mapped(obj["destruction_text"], obj["destruction_cause"]),
            ),
        ]
        for ident in self.rows("ro_object_identifiers", "objects", obj["id"]):
            value = text(ident["object_identifier"])
            if ident["link_id"] is not None:
                uri = self.conn.execute(
                    "SELECT uri FROM links WHERE id = ?", (ident["link_id"],)
                ).fetchone()[0]
                value = f'<a href="{html.escape(uri)}" target="_blank">{value}</a>'
            props.append((html.escape(ident["object_identifier_type_label"]), value))
        body = (
            "<table class='props'>"
            + "".join(
                f"<tr><th>{name}</th><td>{value}</td></tr>"
                for name, value in props
                if value
            )
            + "</table>"
        )
        body += self.table(
            "Attributions",
            ["Text", "Actor", "Status", "Current"],
            [
                self.row(
                    a["first_word_id"],
                    a["last_word_id"],
                    [
                        text(a["attribution_text"]),
                        text(a["production_actor_label"]),
                        text(a["production_attribution_status"]),
                        "yes" if a["is_current"] else "",
                    ],
                )
                for a in self.rows("ro_attributions", "objects", obj["id"])
            ],
        )
        body += self.table(
            "Dimensions",
            ["Text", "Type", "Value", "Note"],
            [
                self.row(
                    d["first_word_id"],
                    d["last_word_id"],
                    [
                        text(d["dimensions_text"]),
                        text(d["dimension_type_label"]),
                        f"{d['dimension_value']:g} {html.escape(d['dimension_unit_label'])}",
                        text(d["dimension_note"]),
                    ],
                )
                for d in self.rows("ro_dimensions", "objects", obj["id"])
            ],
        )
        body += self.provenance(owner, obj["id"])
        body += self.table(
            "Exhibited",
            ["Exhibition", "Cat. no.", "Note"],
            [
                self.row(
                    e["first_word_id"],
                    e["last_word_id"],
                    [
                        text(e["exhibition_reference"]),
                        text(e["exhibition_cat_number"]),
                        text(e["exhibition_note"]),
                    ],
                )
                for e in self.rows("ro_object_exhibitions", "references", obj["id"])
            ],
        )
        body += self.table(
            "Literature",
            ["Source", "Pages", "Note"],
            [
                self.row(
                    s["first_word_id"],
                    s["last_word_id"],
                    [
                        text(s["source_reference"]),
                        text(s["source_page_reference"]),
                        text(s["source_note"]),
                    ],
                )
                for s in self.rows("ro_object_sources", "references", obj["id"])
            ],
        )
        body += self.table(
            "Related objects",
            ["Relation", "Text"],
            [
                self.row(
                    r["first_word_id"],
                    r["last_word_id"],
                    [
                        text(r["related_object_artistic_relation_type"]),
                        text(r["relation_text"]),
                    ],
                )
                for r in self.rows("ro_related_objects", "objects", obj["id"])
            ],
        )
        return f'<section class="object"><h2>No. {html.escape(obj["crlb_number"])}</h2>{body}</section>'

    def provenance(self, owner: Node, object_id: int) -> str:
        """Return the provenance chain of an object, the stages without a row, and the rejected LLM answers."""
        stays = self.rows("ro_collection_stays", "provenance", object_id)
        auctions = self.rows("ro_auctions", "provenance", object_id)
        chain = sorted(
            [*(("stay", r) for r in stays), *(("auction", r) for r in auctions)],
            key=lambda pair: pair[1]["position"],
        )
        rows = []
        for table, r in chain:
            if table == "stay":
                kind = (
                    "current location" if r["collection_is_current"] else "collection"
                )
                what = text(r["holder_text"])
                details = [
                    ("place", r["collection_place_label"]),
                    ("inv.", r["collection_identifier"]),
                    ("type", r["collection_type_label"]),
                    ("entry", r["collection_entry_method"]),
                    ("removed", r["collection_removal_date"]),
                ]
                date = mapped(
                    r["collection_entry_date_text"], r["collection_entry_date"]
                )
            else:
                kind = "auction"
                what = text(r["auction_label"])
                details = [
                    ("house", r["auction_organizer_label"]),
                    ("place", r["auction_place_label"]),
                    ("lot", r["auction_lot_number"]),
                    ("consignor", r["auction_consignor"]),
                    ("buyer", r["auction_buyer"]),
                    (
                        "price",
                        " ".join(
                            filter(
                                None,
                                [
                                    r["auction_price_amount"],
                                    r["auction_price_currency"],
                                ],
                            )
                        ),
                    ),
                    ("note", r["auction_note"]),
                ]
                date = mapped(
                    r["auction_date_text"],
                    date_range(r["auction_date_start"], r["auction_date_end"]),
                )
            facts = "; ".join(
                f'<span class="muted">{name}</span> {html.escape(value)}'
                for name, value in details
                if value
            )
            flags = " <b title='uncertain'>?</b>" if r["uncertain"] else ""
            rows.append(
                self.row(
                    r["first_word_id"],
                    r["last_word_id"],
                    [
                        str(r["position"]),
                        f'<span class="badge {r["method"]}">{r["method"]}</span>',
                        html.escape(kind) + flags,
                        what,
                        date,
                        facts,
                    ],
                )
            )
        ranges = [(r["first_word_id"], r["last_word_id"]) for _, r in chain]
        items = [
            item
            for field in owner.fields("provenance")
            for item in field.children
            if item.kind == "item"
        ]
        methods = {
            (r["first_word_id"], r["last_word_id"]): r["method"] for _, r in chain
        }
        for item in items:
            method = next(
                (
                    m
                    for (first, last), m in methods.items()
                    if first <= item.last and last >= item.first
                ),
                "none",
            )
            for box in self.words(item.first, item.last):
                self.boxes.append((box, f"stage {method}"))
        missing = [
            self.row(
                item.first,
                item.last,
                ['<span class="badge none">none</span>', text(item.text)],
            )
            for item in items
            if not covered(item, ranges)
        ]
        out = self.table(
            "Provenance",
            ["#", "By", "Kind", "Holder or sale", "Date", "Details"],
            rows,
        )
        out += self.table("Provenance stages without a row", ["", "Stage"], missing)
        out += self.rejected(items)
        return out

    def rejected(self, items: list[Node]) -> str:
        """Return the rejected LLM answers for the stages of an object."""
        rows = []
        for item in items:
            for call in self.conn.execute(
                "SELECT error, output_json FROM llm_calls WHERE run_table = 'ro_runs' AND run_id = ?"
                " AND first_word_id = ? AND valid = 0 ORDER BY id",
                (self.runs["provenance"], item.first),
            ).fetchall():
                answer = call["output_json"] or ""
                try:
                    answer = json.dumps(
                        {
                            k: v
                            for k, v in json.loads(answer).items()
                            if v not in (None, False)
                        },
                        ensure_ascii=False,
                    )
                except ValueError, AttributeError:
                    pass
                rows.append(
                    self.row(
                        item.first,
                        item.last,
                        [
                            text(item.text),
                            text(call["error"]),
                            f"<pre>{html.escape(answer)}</pre>",
                        ],
                    )
                )
        return self.table("Rejected LLM answers", ["Stage", "Why", "Answer"], rows)

    def table(self, title: str, headers: list[str], rows: list[str]) -> str:
        """Return a titled table, or nothing if it has no rows."""
        if not rows:
            return ""
        head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
        return f"<h3>{html.escape(title)} ({len(rows)})</h3><table><tr>{head}</tr>{''.join(rows)}</table>"

    def pdf(self) -> str:
        """Return the PDF pages of the entry as images with the boxes laid over them."""
        node = self.entry.node
        (document_id,) = self.conn.execute(
            "SELECT document_id FROM segments WHERE id = ?", (node.id,)
        ).fetchone()
        pages = self.conn.execute(
            "SELECT DISTINCT p.id, p.page_index, p.width, p.height FROM words w JOIN pages p ON p.id = w.page_id"
            " WHERE w.id BETWEEN ? AND ? ORDER BY p.page_index",
            (node.first, node.last),
        ).fetchall()
        pdf = db.open_pdf(self.conn, document_id)
        out = []
        for page_id, index, width, height in pages:
            png = base64.b64encode(
                pdf[index].get_pixmap(dpi=DPI, annots=False).tobytes("png")
            ).decode("ascii")
            boxes = "".join(
                f'<div class="box {classes}" style="left:{b.x0 / width:.3%};top:{b.y0 / height:.3%};'
                f'width:{(b.x1 - b.x0) / width:.3%};height:{(b.y1 - b.y0) / height:.3%}"></div>'
                for b, classes in self.boxes
                if b.page_id == page_id
            )
            out.append(
                f'<div class="page"><img alt="PDF page {index + 1}" src="data:image/png;base64,{png}">{boxes}</div>'
            )
        return "".join(out)

    def html(self, title: str, summary: str) -> str:
        """Return the whole page."""
        ids = dict(
            self.conn.execute(
                "SELECT segment_id, id FROM ro_objects WHERE run_id = ?",
                (self.runs["objects"],),
            ).fetchall()
        )
        sections = []
        for owner in object_nodes(self.entry):
            obj = self.conn.execute(
                "SELECT * FROM ro_objects WHERE id = ?", (ids[owner.id],)
            ).fetchone()
            sections.append(self.object_section(owner, obj))
        legend = (
            '<p class="legend">Provenance stages in the PDF:'
            '<span class="swatch" style="background:rgb(var(--rules))"></span>by rules'
            '<span class="swatch" style="background:rgb(var(--llm))"></span>by the LLM'
            '<span class="swatch" style="background:rgb(var(--none))"></span>no row'
            " — point at a row on the right to see its source in the PDF; click it to scroll there.</p>"
        )
        records = "".join(sections)
        pages = self.pdf()
        return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title><style>{STYLE}</style></head><body>
<header><h1>{html.escape(title)}</h1><p>{summary}</p>{legend}</header>
<div class="view"><div class="pdf">{pages}</div><div class="records">{records}</div></div>
<script>{SCRIPT}</script></body></html>
"""


def text(value: str | None) -> str:
    """Return a value as HTML, or nothing."""
    return "" if value is None else html.escape(value)


def mapped(verbatim: str | None, value: str | None) -> str:
    """Return a verbatim value with what it was mapped or parsed to."""
    if verbatim is None:
        return ""
    out = html.escape(verbatim)
    if value:
        out += f' <span class="mapped">→ {html.escape(value)}</span>'
    return out


def date_range(start: str | None, end: str | None) -> str | None:
    """Return a parsed date range as text."""
    if start is None:
        return None
    return start if end in (None, start) else f"{start} – {end}"


def active_runs(conn: sqlite3.Connection) -> dict[str, int]:
    """Return the active step 4 run of each field."""
    runs = {}
    for field in FIELDS:
        run_id = active_run(conn, f"4:{field}")
        if run_id is None:
            raise SystemExit(
                f"no active {field} run; accept one first (crlb set-active <db> 4:{field} <run>)"
            )
        runs[field] = run_id
    return runs


def run_summary(conn: sqlite3.Connection, runs: dict[str, int]) -> str:
    """Return the runs shown, with the model of the provenance run, as HTML."""
    parts = []
    for field, run_id in runs.items():
        method, model = conn.execute(
            "SELECT method, model FROM ro_runs WHERE id = ?", (run_id,)
        ).fetchone()
        label = f"{field}: run {run_id} ({method}"
        if model:
            label += f", {json.loads(model).get('name', '')}"
        parts.append(html.escape(label + ")"))
    return "Active step 4 runs — " + "; ".join(parts)


def configure(parser: argparse.ArgumentParser) -> None:
    """Add the arguments of this command to its parser."""
    parser.add_argument(
        "db", type=Path, help="crlb.sqlite (with pdfs.sqlite next to it)"
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="directory for the HTML files; default: review/ next to the database",
    )
    add_sample_option(parser)
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Write one review page per entry and print where they are."""
    conn = db.connect(args.db)
    db.attach_pdfs(conn, args.db.parent / "pdfs.sqlite")
    runs = active_runs(conn)
    summary = run_summary(conn, runs)
    entries = load_entries(conn, segmentation_run(conn), args.sample)
    if not entries:
        raise SystemExit("no entries in the active segmentation run match the sample")
    out_dir = args.out or args.db.parent / "review"
    out_dir.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        page = Page(conn, entry, runs)
        title = f"CRLB {entry.part}, No. {entry.number}"
        name = entry.part.replace(" ", "_").replace("(", "").replace(")", "")
        out = out_dir / f"extract_{name}_No{entry.number}.html"
        out.write_text(page.html(title, summary), encoding="utf-8")
        print(f"{out}: {len(object_nodes(entry))} objects, {page.keys} rows")
    conn.close()
