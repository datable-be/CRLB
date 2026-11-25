"""Tests for review decisions and effective values."""

import sqlite3
from pathlib import Path

import pytest

from crlb import db, review


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    """Return a database with one collection stay and one normalised value of it (no other rows)."""
    conn = db.connect(tmp_path / "crlb.sqlite")
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        "INSERT INTO ro_collection_stays (id, object_id, segment_id, first_word_id, last_word_id,"
        " run_id, method, position, holder_text, collection_is_current)"
        " VALUES (1, 1, 1, 10, 14, 1, 'rules', 1, 'Jan Smit', 0)"
    )
    conn.execute(
        "INSERT INTO normalised_values (id, run_id, table_name, row_id, column_name, value_text,"
        " normalised_value, rule) VALUES (1, 1, 'ro_collection_stays', 1, 'holder_text',"
        " 'Jan Smit', 'Smit, Jan', 'entry instruction')"
    )
    conn.commit()
    return conn


def status(conn: sqlite3.Connection, table: str = "ro_collection_stays") -> str:
    """Return the status of row 1 of a table."""
    return conn.execute(f"SELECT status FROM {table} WHERE id = 1").fetchone()[0]


@pytest.mark.parametrize(
    ("action", "expected"),
    [("accept", "accepted"), ("reject", "rejected")],
)
def test_status_follows_the_decision(
    conn: sqlite3.Connection, action: str, expected: str
) -> None:
    """Accepting or rejecting a row sets its status."""
    review.record(conn, "ro_collection_stays", 1, action, "anna")
    assert status(conn) == expected


def test_correction_sets_status_and_keeps_the_row(conn: sqlite3.Connection) -> None:
    """A correction is stored as a review with the old value; the row keeps its value."""
    review.record(
        conn, "ro_collection_stays", 1, "correct", "anna", "holder_text", "Jan Smits"
    )
    assert status(conn) == "corrected"
    (row,) = review.history(conn, "ro_collection_stays", 1)
    assert (row["old_value"], row["new_value"]) == ("Jan Smit", "Jan Smits")
    assert (row["first_word_id"], row["last_word_id"]) == (10, 14)
    assert (
        conn.execute("SELECT holder_text FROM ro_collection_stays").fetchone()[0]
        == "Jan Smit"
    )


def test_comment_leaves_the_status(conn: sqlite3.Connection) -> None:
    """A comment is recorded but does not change the status."""
    review.record(conn, "ro_collection_stays", 1, "accept", "anna")
    review.record(conn, "ro_collection_stays", 1, "comment", "ben", comment="check")
    assert status(conn) == "accepted"
    assert [r["action"] for r in review.history(conn, "ro_collection_stays", 1)] == [
        "accept",
        "comment",
    ]


def test_latest_correction_wins(conn: sqlite3.Connection) -> None:
    """The effective value is the latest correction; the second one records the first as old value."""
    for value in ("A", "B"):
        review.record(
            conn, "ro_collection_stays", 1, "correct", "anna", "holder_text", value
        )
    assert review.effective(conn, "ro_collection_stays", 1, "holder_text") == "B"
    assert review.history(conn, "ro_collection_stays", 1)[1]["old_value"] == "A"
    assert review.effective(conn, "ro_collection_stays", 1, "position") == 1


def test_normalised_value_is_anchored_to_its_step_4_row(
    conn: sqlite3.Connection,
) -> None:
    """A review of a normalised value has the word range of the row it normalises."""
    review.record(
        conn, "normalised_values", 1, "correct", "anna", "normalised_value", "Smits"
    )
    (row,) = review.history(conn, "normalised_values", 1)
    assert (row["first_word_id"], row["last_word_id"]) == (10, 14)
    assert status(conn, "normalised_values") == "corrected"


@pytest.mark.parametrize(
    ("table", "action", "column", "comment"),
    [
        ("ro_collection_stays", "correct", "run_id", None),
        ("ro_collection_stays", "correct", None, None),
        ("segments", "accept", None, None),
        ("ro_collection_stays", "delete", None, None),
        ("ro_collection_stays", "comment", None, ""),
    ],
)
def test_invalid_decisions_are_refused(
    conn: sqlite3.Connection,
    table: str,
    action: str,
    column: str | None,
    comment: str | None,
) -> None:
    """Corrections outside EDITABLE, unknown tables and actions, and empty comments are refused."""
    with pytest.raises(ValueError):
        review.record(conn, table, 1, action, "anna", column, "x", comment)
    assert conn.execute("SELECT count(*) FROM reviews").fetchone()[0] == 0


def test_missing_row_rolls_back(conn: sqlite3.Connection) -> None:
    """A decision on a row that does not exist stores nothing."""
    with pytest.raises(ValueError):
        review.record(conn, "ro_collection_stays", 99, "accept", "anna")
    assert not conn.in_transaction
    assert conn.execute("SELECT count(*) FROM reviews").fetchone()[0] == 0
