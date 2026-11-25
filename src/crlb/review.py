"""Review decisions on the results of a step: recording them, and the effective values they give.

A decision is an event in `reviews` (accept, correct, reject or comment). The
row itself is never changed except its `status`, which follows the latest
decision that is not a comment. The effective value of a column is the new
value of its latest correction, otherwise the value in the row. Only the
columns in EDITABLE can be corrected: values, never ids, word ranges or runs.
"""

import sqlite3
from typing import Any

from crlb.runs import utc_now

ACTIONS = ("accept", "correct", "reject", "comment")
STATUS = {"accept": "accepted", "correct": "corrected", "reject": "rejected"}

# The columns a reviewer can correct, per table
EDITABLE: dict[str, tuple[str, ...]] = {
    "ro_objects": (
        "title_value",
        "object_name_label",
        "production_date_label",
        "production_date_start",
        "production_date_end",
        "material_note",
        "material_support_label",
        "destruction_cause",
    ),
    "ro_object_identifiers": ("object_identifier", "object_identifier_type_label"),
    "ro_attributions": (
        "production_actor_label",
        "production_attribution_status",
        "is_current",
    ),
    "ro_dimensions": (
        "dimension_value",
        "dimension_unit_label",
        "dimension_type_label",
        "dimension_note",
    ),
    "ro_collection_stays": (
        "holder_text",
        "collection_type_label",
        "collection_place_label",
        "collection_identifier",
        "collection_entry_date",
        "collection_entry_method",
        "collection_entry_note",
        "collection_removal_date",
        "collection_is_current",
        "uncertain",
    ),
    "ro_auctions": (
        "auction_organizer_label",
        "auction_place_label",
        "auction_date_start",
        "auction_date_end",
        "auction_lot_number",
        "auction_consignor",
        "auction_buyer",
        "auction_price_amount",
        "auction_price_currency",
        "auction_note",
        "uncertain",
    ),
    "ro_object_exhibitions": (
        "exhibition_reference",
        "exhibition_cat_number",
        "exhibition_note",
    ),
    "ro_object_sources": ("source_reference", "source_page_reference", "source_note"),
    "ro_related_objects": ("related_object_artistic_relation_type",),
    "normalised_values": ("normalised_value",),
}


def anchor(
    conn: sqlite3.Connection, table: str, row: sqlite3.Row
) -> tuple[int | None, int | None]:
    """Return the word range of a row; a normalised value has the range of the step 4 row it normalises."""
    if table == "normalised_values":
        source = conn.execute(
            f"SELECT first_word_id, last_word_id FROM {row['table_name']} WHERE id = ?",
            (row["row_id"],),
        ).fetchone()
        return (None, None) if source is None else (source[0], source[1])
    return row["first_word_id"], row["last_word_id"]


def corrections(conn: sqlite3.Connection, table: str, row_id: int) -> dict[str, str]:
    """Return the new value of the latest correction of each corrected column of a row."""
    found: dict[str, str] = {}
    for column, value in conn.execute(
        "SELECT column_name, new_value FROM reviews WHERE table_name = ? AND row_id = ?"
        " AND action = 'correct' ORDER BY id",
        (table, row_id),
    ):
        found[column] = value
    return found


def effective(conn: sqlite3.Connection, table: str, row_id: int, column: str) -> Any:
    """Return the effective value of a column: its latest correction, otherwise the value in the row."""
    corrected = corrections(conn, table, row_id)
    if column in corrected:
        return corrected[column]
    row = conn.execute(
        f"SELECT {column} FROM {table} WHERE id = ?", (row_id,)
    ).fetchone()
    return None if row is None else row[0]


def history(conn: sqlite3.Connection, table: str, row_id: int) -> list[sqlite3.Row]:
    """Return the decisions on a row, oldest first."""
    return conn.execute(
        "SELECT * FROM reviews WHERE table_name = ? AND row_id = ? ORDER BY id",
        (table, row_id),
    ).fetchall()


def record(
    conn: sqlite3.Connection,
    table: str,
    row_id: int,
    action: str,
    reviewer: str,
    column: str | None = None,
    new_value: str | None = None,
    comment: str | None = None,
) -> int:
    """Store a decision and update the row's status in one transaction; return the review id."""
    if table not in EDITABLE:
        raise ValueError(f"{table} cannot be reviewed")
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    if action == "correct" and column not in EDITABLE[table]:
        raise ValueError(f"{table}.{column} cannot be corrected")
    if action != "correct" and column is not None and column not in EDITABLE[table]:
        raise ValueError(f"{table}.{column} cannot be reviewed")
    if action == "comment" and not comment:
        raise ValueError("a comment needs text")
    own = not conn.in_transaction
    if own:
        conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
        if row is None:
            raise ValueError(f"no row {row_id} in {table}")
        old = (
            effective(conn, table, row_id, column)
            if column is not None and action == "correct"
            else None
        )
        first, last = anchor(conn, table, row)
        review_id = conn.execute(
            "INSERT INTO reviews (table_name, row_id, column_name, action, old_value, new_value,"
            " reviewer, reviewed_at, comment, first_word_id, last_word_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                table,
                row_id,
                column,
                action,
                None if old is None else str(old),
                new_value if action == "correct" else None,
                reviewer,
                utc_now(),
                comment or None,
                first,
                last,
            ),
        ).lastrowid
        if action in STATUS:
            conn.execute(
                f"UPDATE {table} SET status = ? WHERE id = ?", (STATUS[action], row_id)
            )
        if own:
            conn.commit()
    except BaseException:
        if own:
            conn.rollback()
        raise
    assert review_id is not None
    return review_id
