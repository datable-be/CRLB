"""Connections to crlb.sqlite and pdfs.sqlite, schema versions and access to the stored PDFs.

crlb.sqlite grows step by step: every step has its own numbered SQL file in
`crlb/schema/` (`01_text.sql`, `02_correction.sql`, ...). `connect` applies the
files that are missing, in name order, and records them in `schema_version`, so
a later step never requires rebuilding the database.

pdfs.sqlite holds the PDF files themselves (sqlar format). It is attached to
the crlb.sqlite connection under the name `pdfs`, so both are read and written
through one connection and committed together.
"""

import hashlib
import sqlite3
from importlib.resources import files
from pathlib import Path

import pymupdf

from crlb.runs import utc_now

SCHEMA_DIR = files("crlb") / "schema"


def schema_files() -> list[str]:
    """Return the names of the numbered schema files of crlb.sqlite, in order."""
    return sorted(
        f.name
        for f in SCHEMA_DIR.iterdir()
        if f.name[:2].isdigit() and f.name.endswith(".sql")
    )


def apply_schema(conn: sqlite3.Connection) -> list[str]:
    """Apply the schema files not yet recorded in schema_version; return their names."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "file TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    applied = {row[0] for row in conn.execute("SELECT file FROM schema_version")}
    new = [name for name in schema_files() if name not in applied]
    for name in new:
        sql = (SCHEMA_DIR / name).read_text(encoding="utf-8")
        # One transaction per file, so a failing file leaves no half-applied schema
        conn.executescript(
            f"BEGIN;\n{sql}\n"
            f"INSERT INTO schema_version VALUES ('{name}', '{utc_now()}');\n"
            "COMMIT;"
        )
    return new


def connect(path: Path) -> sqlite3.Connection:
    """Open crlb.sqlite (created if missing) with foreign keys on and the schema up to date."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_schema(conn)
    return conn


def attach_pdfs(conn: sqlite3.Connection, path: Path) -> None:
    """Attach pdfs.sqlite to the connection as schema `pdfs`, creating its table if needed."""
    pdfs = sqlite3.connect(path)
    pdfs.executescript((SCHEMA_DIR / "pdfs.sql").read_text(encoding="utf-8"))
    pdfs.close()
    conn.execute("ATTACH DATABASE ? AS pdfs", (str(path),))


def read_pdf(conn: sqlite3.Connection, name: str, sha256: str) -> pymupdf.Document:
    """Open a PDF from the attached pdfs.sqlite; raise ValueError if its hash differs."""
    row = conn.execute("SELECT data FROM pdfs.sqlar WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise ValueError(f"{name} is not in pdfs.sqlite")
    data = row[0]
    if hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError(f"{name} in pdfs.sqlite does not match its SHA-256")
    return pymupdf.open(stream=data, filetype="pdf")


def open_pdf(conn: sqlite3.Connection, document_id: int) -> pymupdf.Document:
    """Open the stored PDF of a document, checked against documents.sha256."""
    row = conn.execute(
        "SELECT path, sha256 FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"no document with id {document_id}")
    return read_pdf(conn, row["path"], row["sha256"])
