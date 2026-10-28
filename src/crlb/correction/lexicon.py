"""Build the lexicon of word forms and bigrams from the born-digital PDFs listed in a sources file.

The born-digital text is correct, so its word forms decide whether a joined
OCR form is a real word. The PDFs are read directly from disk (they need not
be in the database); their path and SHA-256 are stored in `lexicon_sources`.
Every run replaces the lexicon completely. The console shows only counts.
"""

import argparse
import csv
import hashlib
import sqlite3
import time
from collections import Counter
from itertools import pairwise
from pathlib import Path

import pymupdf

from crlb import db
from crlb.correction.tokens import Word, form, logical_words
from crlb.database.build import TEXT_FLAGS
from crlb.runs import utc_now

CHUNK_SIZE = 1 << 20


def read_sources(path: Path) -> list[str]:
    """Read the paths from a lexicon sources file (columns path, note)."""
    with path.open(newline="", encoding="utf-8") as f:
        return [row["path"] for row in csv.DictReader(f)]


def file_sha256(path: Path) -> str:
    """Return the SHA-256 of a file, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def pdf_pages(path: Path) -> list[list[Word]]:
    """Return the words of every page of a PDF, extracted as in step 1."""
    pages = []
    for page in pymupdf.open(path):
        words = page.get_text("words", flags=TEXT_FLAGS, sort=False)
        pages.append([Word(i, w[4], w[5], w[6]) for i, w in enumerate(words)])
    return pages


def count_page(
    words: list[Word],
    forms: Counter[str],
    bigrams: Counter[tuple[str, str]] | None = None,
) -> None:
    """Add the forms (and, if given, the bigrams of consecutive words on a line) of one page."""
    for texts in logical_words(words):
        line_forms = [form(t) for t in texts]
        forms.update(f for f in line_forms if f)
        if bigrams is not None:
            bigrams.update((a, b) for a, b in pairwise(line_forms) if a and b)


def ocr_forms(conn: sqlite3.Connection) -> Counter[str]:
    """Count the forms of the OCR documents in the database."""
    forms: Counter[str] = Counter()
    page_ids = [
        row[0]
        for row in conn.execute(
            "SELECT p.id FROM pages p JOIN documents d ON d.id = p.document_id WHERE d.text_source = 'ocr'"
        )
    ]
    for page_id in page_ids:
        rows = conn.execute(
            "SELECT id, text, block_no, line_no FROM words WHERE page_id = ? ORDER BY id",
            (page_id,),
        )
        count_page([Word(*row) for row in rows], forms)
    return forms


def build_lexicon(
    conn: sqlite3.Connection, root: Path, sources: list[str]
) -> tuple[int, int, int]:
    """Replace the lexicon, bigrams and sources in the database; return the counts of sources, forms and bigrams.

    Prints progress per source (path and counts only).
    """
    forms: Counter[str] = Counter()
    bigrams: Counter[tuple[str, str]] = Counter()
    source_rows = []
    for i, name in enumerate(sources, 1):
        started = time.monotonic()
        path = root / name
        pages = pdf_pages(path)
        before = forms.total()
        for words in pages:
            count_page(words, forms, bigrams)
        source_rows.append(
            (name, file_sha256(path), len(pages), forms.total() - before, utc_now())
        )
        print(
            f"  [{i}/{len(sources)}] {name}: {len(pages)} pages, "
            f"{forms.total() - before} words ({time.monotonic() - started:.0f} s)",
            flush=True,
        )
    started = time.monotonic()
    ocr = ocr_forms(conn)
    print(
        f"  OCR documents in the database: {ocr.total()} words "
        f"({time.monotonic() - started:.0f} s)",
        flush=True,
    )

    conn.execute("DELETE FROM lexicon")
    conn.execute("DELETE FROM bigrams")
    conn.execute("DELETE FROM lexicon_sources")
    conn.executemany("INSERT INTO lexicon_sources VALUES (?, ?, ?, ?, ?)", source_rows)
    conn.executemany(
        "INSERT INTO lexicon (form, born_digital, ocr) VALUES (?, ?, ?)",
        [(f, n, ocr[f]) for f, n in forms.items()],
    )
    # A bigram only matters when its two words joined are a lexicon form ("a part"
    # against "apart"), so the others are not stored
    kept = [(a, b, n) for (a, b), n in bigrams.items() if a + b in forms]
    conn.executemany(
        "INSERT INTO bigrams (first, second, born_digital) VALUES (?, ?, ?)", kept
    )
    conn.commit()
    return len(source_rows), len(forms), len(kept)


def configure(parser: argparse.ArgumentParser) -> None:
    """Add the arguments of this command to its parser."""
    parser.add_argument("db", type=Path, help="crlb.sqlite")
    parser.add_argument(
        "sources", type=Path, help="lexicon_sources.csv: the born-digital PDFs to read"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="directory the source paths are relative to",
    )
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Build the lexicon and print its size."""
    if not args.db.exists():
        raise SystemExit(f"{args.db} does not exist; run crlb build first")
    sources = read_sources(args.sources)
    if missing := [s for s in sources if not (args.root / s).is_file()]:
        raise SystemExit("lexicon sources not found:\n" + "\n".join(missing))
    started = time.monotonic()
    conn = db.connect(args.db)
    n_sources, n_forms, n_bigrams = build_lexicon(conn, args.root, sources)
    conn.close()
    print(
        f"lexicon: {n_sources} sources, {n_forms} forms, {n_bigrams} bigrams "
        f"({time.monotonic() - started:.0f} s)"
    )
