"""The data of the entry list and the entry page, read from crlb.sqlite with crlb's own loaders.

The page shows what `crlb extract review` shows (the PDF pages next to the
records of the active step 4 runs), plus the normalised values of 5b, with
effective values and the review history of every row.
"""

import json
import sqlite3
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from django.http import Http404

from crlb import review
from crlb.extraction.references import object_nodes
from crlb.extraction.review import (
    Box,
    active_runs,
    covered,
    date_range,
    line_boxes,
    row_methods,
)
from crlb.extraction.source import Node, load_entries, segmentation_run
from crlb.sample import SampleItem
from crlb.text import active_run
from crlb_web.validation.models import SECTIONS

# The step 4 field (and so the active run) of each table
FIELD = {
    "ro_objects": "objects",
    "ro_object_identifiers": "objects",
    "ro_attributions": "objects",
    "ro_dimensions": "objects",
    "ro_related_objects": "objects",
    "ro_object_exhibitions": "references",
    "ro_object_sources": "references",
    "ro_collection_stays": "provenance",
    "ro_auctions": "provenance",
}
CANDIDATES = 3  # candidates shown per normalised value


def connect() -> sqlite3.Connection:
    """Open the reviewed crlb.sqlite (its schema is brought up to date by `make web_db`, not here)."""
    conn = sqlite3.connect(settings.CRLB_DB, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def runs(conn: sqlite3.Connection) -> dict[str, int]:
    """Return the active step 4 run of each field, or a 404 if a run is missing."""
    try:
        return active_runs(conn)
    except SystemExit as missing:
        raise Http404(str(missing)) from None


def normalisation_run(conn: sqlite3.Connection) -> int | None:
    """Return the active 5b run, or the latest one if none is active."""
    run_id = active_run(conn, "5b")
    if run_id is None:
        run_id = conn.execute(
            "SELECT MAX(id) FROM enrichment_runs WHERE part_of_step = '5b'"
        ).fetchone()[0]
    return run_id


@dataclass
class Value:
    """A value shown in a cell: the effective text, the extracted one if corrected, and what it maps to."""

    text: str
    original: str | None = None
    mapped: str | None = None
    label: str | None = None
    css: str | None = None  # e.g. 'badge llm'


@dataclass
class Field:
    """An editable column of a row with its effective value."""

    column: str
    value: str
    corrected: bool


@dataclass
class Row:
    """A row of a records table; table and id are None for rows that cannot be reviewed."""

    key: str
    cells: list[list[Value]]
    table: str | None = None
    id: int | None = None
    status: str | None = None
    section: str | None = None
    fields: list[Field] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)

    @property
    def anchor(self) -> str:
        """Return the HTML id of the row."""
        return f"row-{self.table}-{self.id}" if self.table else f"row-k{self.key}"


@dataclass
class Table:
    """A titled records table."""

    title: str
    headers: list[str]
    rows: list[Row]


@dataclass
class Effective:
    """A row with its corrections applied."""

    row: sqlite3.Row
    corrected: dict[str, str]

    def __getitem__(self, column: str) -> Any:
        """Return the effective value of a column."""
        return self.corrected.get(column, self.row[column])

    def value(
        self, column: str, mapped: str | None = None, label: str | None = None
    ) -> Value:
        """Return a column as a Value, with the extracted value if it was corrected."""
        current = self[column]
        original = None
        if column in self.corrected:
            original = "" if self.row[column] is None else str(self.row[column])
        return Value("" if current is None else str(current), original, mapped, label)


def plain(text: str | None) -> list[Value]:
    """Return a cell with one plain text."""
    return [] if text is None else [Value(text)]


class Builder:
    """Builds the data of one entry page: the PDF boxes and the records tables."""

    def __init__(self, conn: sqlite3.Connection, active: dict[str, int]) -> None:
        """Remember the connection and the active runs."""
        self.conn, self.runs = conn, active
        self.boxes: list[tuple[Box, str]] = []
        self.keys = 0
        self.normalisation = normalisation_run(conn)

    def key(self, first: int, last: int) -> str:
        """Add hidden highlight boxes for a word range and return the key that shows them."""
        self.keys += 1
        for box in self.words(first, last):
            self.boxes.append((box, f"mark k{self.keys}"))
        return str(self.keys)

    def words(self, first: int, last: int) -> list[Box]:
        """Return the line boxes of a word range."""
        return line_boxes(
            self.conn.execute(
                "SELECT page_id, block_no, line_no, x0, y0, x1, y1 FROM words WHERE id BETWEEN ? AND ?",
                (first, last),
            ).fetchall()
        )

    def rows(self, table: str, object_id: int) -> list[Effective]:
        """Return the rows of a table for an object in its active run, with corrections applied."""
        return [
            Effective(r, review.corrections(self.conn, table, r["id"]))
            for r in self.conn.execute(
                f"SELECT * FROM {table} WHERE object_id = ? AND run_id = ? ORDER BY first_word_id, id",
                (object_id, self.runs[FIELD[table]]),
            ).fetchall()
        ]

    def row(
        self, table: str, r: Effective, cells: list[list[Value]], key: str | None = None
    ) -> Row:
        """Return a reviewable row with its editable fields and history."""
        return Row(
            key or self.key(r.row["first_word_id"], r.row["last_word_id"]),
            cells,
            table,
            r.row["id"],
            r.row["status"],
            SECTIONS[table],
            [
                Field(c, "" if r[c] is None else str(r[c]), c in r.corrected)
                for c in review.EDITABLE[table]
            ],
            [dict(h) for h in review.history(self.conn, table, r.row["id"])],
        )

    def table(
        self,
        title: str,
        headers: list[str],
        table: str,
        object_id: int,
        cells: Callable[[Effective], list[list[Value]]],
    ) -> Table:
        """Return the table of one crlb table's rows for an object."""
        return Table(
            title,
            headers,
            [self.row(table, r, cells(r)) for r in self.rows(table, object_id)],
        )

    def object(self, owner: Node, object_id: int) -> dict[str, Any]:
        """Return the record of one object: its properties and its tables."""
        (obj,) = self.rows_by_id("ro_objects", object_id)
        record = self.row(
            "ro_objects",
            obj,
            [
                [obj.value("title_value")],
                [obj.value("object_name_label", label=obj["object_name_text"])],
                [
                    obj.value(
                        "production_date_label",
                        mapped=date_range(
                            obj["production_date_start"], obj["production_date_end"]
                        ),
                    )
                ],
                [obj.value("material_note", mapped=obj["material_support_label"])],
                [obj.value("destruction_cause", label=obj["destruction_text"])],
            ],
        )
        tables = [
            Table(
                "Object",
                ["Title", "Object name", "Date", "Material", "Lost or destroyed"],
                [record],
            ),
            self.table(
                "Identifiers",
                ["Type", "Identifier"],
                "ro_object_identifiers",
                object_id,
                lambda r: [
                    [r.value("object_identifier_type_label")],
                    [r.value("object_identifier")],
                ],
            ),
            self.table(
                "Attributions",
                ["Text", "Actor", "Status", "Current"],
                "ro_attributions",
                object_id,
                lambda r: [
                    plain(r["attribution_text"]),
                    [r.value("production_actor_label")],
                    [r.value("production_attribution_status")],
                    [r.value("is_current")],
                ],
            ),
            self.table(
                "Dimensions",
                ["Text", "Type", "Value", "Note"],
                "ro_dimensions",
                object_id,
                lambda r: [
                    plain(r["dimensions_text"]),
                    [r.value("dimension_type_label")],
                    [r.value("dimension_value"), r.value("dimension_unit_label")],
                    [r.value("dimension_note")],
                ],
            ),
            *self.provenance(owner, object_id),
            self.table(
                "Exhibited",
                ["Exhibition", "Cat. no.", "Note"],
                "ro_object_exhibitions",
                object_id,
                lambda r: [
                    [r.value("exhibition_reference")],
                    [r.value("exhibition_cat_number")],
                    [r.value("exhibition_note")],
                ],
            ),
            self.table(
                "Literature",
                ["Source", "Pages", "Note"],
                "ro_object_sources",
                object_id,
                lambda r: [
                    [r.value("source_reference")],
                    [r.value("source_page_reference")],
                    [r.value("source_note")],
                ],
            ),
            self.table(
                "Related objects",
                ["Relation", "Text"],
                "ro_related_objects",
                object_id,
                lambda r: [
                    [r.value("related_object_artistic_relation_type")],
                    plain(r["relation_text"]),
                ],
            ),
        ]
        return {
            "number": obj["crlb_number"],
            "tables": [t for t in tables if t.rows],
        }

    def rows_by_id(self, table: str, row_id: int) -> list[Effective]:
        """Return one row by id, with corrections applied."""
        return [
            Effective(r, review.corrections(self.conn, table, r["id"]))
            for r in self.conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,))
        ]

    def provenance(self, owner: Node, object_id: int) -> list[Table]:
        """Return the provenance chain, the normalised values, the stages without a row and the rejected LLM answers."""
        stays = self.rows("ro_collection_stays", object_id)
        auctions = self.rows("ro_auctions", object_id)
        chain = sorted(
            [
                *(("ro_collection_stays", r) for r in stays),
                *(("ro_auctions", r) for r in auctions),
            ],
            key=lambda pair: pair[1]["position"],
        )
        rows, normalised = [], []
        for table, r in chain:
            method = r["method"]
            if table == "ro_collection_stays":
                kind = (
                    "current location"
                    if r["collection_is_current"] in (1, "1")
                    else "collection"
                )
                what = [r.value("holder_text")]
                details = [
                    r.value(c, label=name)
                    for name, c in [
                        ("place", "collection_place_label"),
                        ("inv.", "collection_identifier"),
                        ("type", "collection_type_label"),
                        ("entry", "collection_entry_method"),
                        ("removed", "collection_removal_date"),
                    ]
                ]
                parsed = r.value("collection_entry_date")
                date = [
                    Value(
                        r["collection_entry_date_text"] or "",
                        parsed.original,
                        parsed.text or None,
                    )
                ]
            else:
                kind = "auction"
                what = plain(r["auction_label"])
                details = [
                    r.value(c, label=name)
                    for name, c in [
                        ("house", "auction_organizer_label"),
                        ("place", "auction_place_label"),
                        ("lot", "auction_lot_number"),
                        ("consignor", "auction_consignor"),
                        ("buyer", "auction_buyer"),
                        ("price", "auction_price_amount"),
                        ("currency", "auction_price_currency"),
                        ("note", "auction_note"),
                    ]
                ]
                date = [
                    Value(
                        r["auction_date_text"] or "",
                        mapped=date_range(
                            r["auction_date_start"], r["auction_date_end"]
                        ),
                    )
                ]
            if r["uncertain"] in (1, "1"):
                kind += " ?"
            row = self.row(
                table,
                r,
                [
                    [Value(str(r["position"]))],
                    [Value(method, css=f"badge {method}")],
                    [Value(kind)],
                    what,
                    date,
                    [d for d in details if d.text],
                ],
            )
            rows.append(row)
            normalised += self.normalised(table, r.row["id"], row.key)
        items = [
            item
            for fld in owner.fields("provenance")
            for item in fld.children
            if item.kind == "item"
        ]
        methods = row_methods([r.row for _, r in chain], items)
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
        ranges = list(methods)
        missing = [
            Row(self.key(item.first, item.last), [plain(item.text)])
            for item in items
            if not covered(item, ranges)
        ]
        return [
            Table(
                "Provenance",
                ["#", "By", "Kind", "Holder or sale", "Date", "Details"],
                rows,
            ),
            Table(
                "Normalised values",
                ["Column", "Verbatim", "Normalised", "Rule", "Score"],
                normalised,
            ),
            Table("Provenance stages without a row", ["Stage"], missing),
            Table(
                "Rejected LLM answers", ["Stage", "Why", "Answer"], self.rejected(items)
            ),
        ]

    def normalised(self, table: str, row_id: int, key: str) -> list[Row]:
        """Return the normalised values of a provenance row; they highlight the row's words."""
        if self.normalisation is None:
            return []
        out = []
        for n in self.conn.execute(
            "SELECT * FROM normalised_values WHERE run_id = ? AND table_name = ? AND row_id = ? ORDER BY id",
            (self.normalisation, table, row_id),
        ).fetchall():
            eff = Effective(
                n, review.corrections(self.conn, "normalised_values", n["id"])
            )
            row = self.row(
                "normalised_values",
                eff,
                [
                    [Value(n["column_name"].replace("_", " "))],
                    [Value(n["value_text"])],
                    [eff.value("normalised_value")],
                    [Value(n["rule"])],
                    [Value("" if n["score"] is None else f"{n['score']:.2f}")],
                ],
                key=key,
            )
            row.candidates = json.loads(n["candidates"] or "[]")[:CANDIDATES]
            out.append(row)
        return out

    def rejected(self, items: list[Node]) -> list[Row]:
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
                    Row(
                        self.key(item.first, item.last),
                        [plain(item.text), plain(call["error"]), plain(answer)],
                    )
                )
        return rows

    def pages(self, node: Node) -> list[dict[str, Any]]:
        """Return the PDF pages of the entry with the boxes to lay over them, in percent of the page."""
        (document_id,) = self.conn.execute(
            "SELECT document_id FROM segments WHERE id = ?", (node.id,)
        ).fetchone()
        out = []
        for page_id, index, width, height in self.conn.execute(
            "SELECT DISTINCT p.id, p.page_index, p.width, p.height FROM words w JOIN pages p ON p.id = w.page_id"
            " WHERE w.id BETWEEN ? AND ? ORDER BY p.page_index",
            (node.first, node.last),
        ).fetchall():
            boxes = [
                {
                    "classes": classes,
                    "style": f"left:{b.x0 / width:.3%};top:{b.y0 / height:.3%};"
                    f"width:{(b.x1 - b.x0) / width:.3%};height:{(b.y1 - b.y0) / height:.3%}",
                }
                for b, classes in self.boxes
                if b.page_id == page_id
            ]
            out.append({"document_id": document_id, "index": index, "boxes": boxes})
        return out


def entry_page(conn: sqlite3.Connection, part: str, number: str) -> dict[str, Any]:
    """Return the context of an entry page, or a 404 if the entry is not in the active runs."""
    active = runs(conn)
    found = load_entries(conn, segmentation_run(conn), [SampleItem(part, number)])
    if not found:
        raise Http404(f"no entry {part} No. {number} in the active segmentation run")
    entry = found[0]
    ids = dict(
        conn.execute(
            "SELECT segment_id, id FROM ro_objects WHERE run_id = ?",
            (active["objects"],),
        ).fetchall()
    )
    builder = Builder(conn, active)
    objects = [
        builder.object(owner, ids[owner.id])
        for owner in object_nodes(entry)
        if owner.id in ids
    ]
    if not objects:
        raise Http404(f"{part} No. {number} has no records in the active step 4 runs")
    return {
        "part": part,
        "number": number,
        "runs": active,
        "normalisation_run": builder.normalisation,
        "objects": objects,
        "pages": builder.pages(entry.node),
    }


def entry_list(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return the entries of the active step 4 runs with the number of rows per status."""
    active = runs(conn)
    entries = []
    for e in conn.execute(
        "SELECT o.part, s.label, o.title_value, s.first_word_id, s.last_word_id"
        " FROM ro_objects o JOIN segments s ON s.id = o.segment_id"
        " WHERE o.run_id = ? AND s.kind = 'entry' ORDER BY s.document_id, s.first_word_id",
        (active["objects"],),
    ).fetchall():
        counts: Counter[str] = Counter()
        for table, fld in FIELD.items():
            for status, n in conn.execute(
                f"SELECT status, count(*) FROM {table} WHERE run_id = ?"
                " AND first_word_id BETWEEN ? AND ? GROUP BY status",
                (active[fld], e["first_word_id"], e["last_word_id"]),
            ):
                counts[status] += n
        entries.append(
            {
                "part": e["part"],
                "number": e["label"],
                "title": e["title_value"],
                "counts": counts,
                "total": sum(counts.values()),
            }
        )
    return entries
