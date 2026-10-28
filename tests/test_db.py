"""Tests for the database connection and schema versions."""

from pathlib import Path

from crlb import db


def test_schema_is_applied_once_in_order(tmp_path: Path) -> None:
    """A new database gets all schema files in order; opening it again applies nothing."""
    conn = db.connect(tmp_path / "crlb.sqlite")
    applied = [
        row[0] for row in conn.execute("SELECT file FROM schema_version ORDER BY rowid")
    ]
    assert applied == db.schema_files() and applied[0] == "01_text.sql"
    conn.close()
    assert db.apply_schema(db.connect(tmp_path / "crlb.sqlite")) == []


def test_foreign_keys_are_on(tmp_path: Path) -> None:
    """Connections enforce foreign keys."""
    assert (
        db.connect(tmp_path / "crlb.sqlite")
        .execute("PRAGMA foreign_keys")
        .fetchone()[0]
        == 1
    )


def test_attach_pdfs_creates_the_sqlar_table(tmp_path: Path) -> None:
    """Attaching a new pdfs.sqlite creates the standard sqlar table in it."""
    conn = db.connect(tmp_path / "crlb.sqlite")
    db.attach_pdfs(conn, tmp_path / "pdfs.sqlite")
    assert conn.execute("SELECT count(*) FROM pdfs.sqlar").fetchone()[0] == 0
