"""Build the text database: store each PDF of the manifest and extract its pages, words, links and bookmarks.

Creates <out_dir>/crlb.sqlite (text) and <out_dir>/pdfs.sqlite (the PDF files,
sqlar format). The text is stored exactly as it is in the PDF: no correction,
normalisation or segmentation. The console shows only counts and warnings,
never PDF text.
"""

import argparse
import hashlib
import json
import sqlite3
import time
from collections import Counter
from pathlib import Path

import pymupdf

from crlb import db
from crlb.database.manifest import (
    DocumentRow,
    PartRow,
    read_documents,
    read_parts,
    validate,
)
from crlb.runs import git_commit, utc_now

# One set of flags for all extractions of a page: ligatures and whitespace as in
# the PDF, no images, and no dehyphenation, so soft hyphens and line-end
# hyphens stay as they are
TEXT_FLAGS = pymupdf.TEXTFLAGS_WORDS
CHUNK_SIZE = 1 << 20
LINK_KINDS = {
    pymupdf.LINK_NONE: "none",
    pymupdf.LINK_GOTO: "goto",
    pymupdf.LINK_URI: "uri",
    pymupdf.LINK_LAUNCH: "launch",
    pymupdf.LINK_NAMED: "named",
    pymupdf.LINK_GOTOR: "gotor",
}

type Style = tuple[str, float, int]


def store_pdf(conn: sqlite3.Connection, root: Path, name: str) -> tuple[str, int]:
    """Stream a PDF into pdfs.sqlar in chunks, without holding it in memory; return its SHA-256 and size."""
    path = root / name
    stat = path.stat()
    row_id = conn.execute(
        "INSERT INTO pdfs.sqlar (name, mode, mtime, sz, data) VALUES (?, ?, ?, ?, zeroblob(?))",
        (name, stat.st_mode, int(stat.st_mtime), stat.st_size, stat.st_size),
    ).lastrowid
    assert row_id is not None
    digest = hashlib.sha256()
    with (
        path.open("rb") as f,
        conn.blobopen("sqlar", "data", row_id, name="pdfs") as blob,
    ):
        while chunk := f.read(CHUNK_SIZE):
            digest.update(chunk)
            blob.write(chunk)
    return digest.hexdigest(), stat.st_size


def text_source_of(metadata: dict) -> str | None:
    """Return the text source implied by the PDF metadata, or None if it is not recognised."""
    producer = metadata.get("producer") or ""
    creator = metadata.get("creator") or ""
    if "ABBYY" in producer or ("3-Heights" in producer and creator == "Paperless"):
        return "ocr"
    if "InDesign" in creator:
        return "born_digital"
    if not producer:
        return "ocr"
    return None


def insert_document(
    conn: sqlite3.Connection,
    run_id: int,
    row: DocumentRow,
    sha256: str,
    size: int,
    doc: pymupdf.Document,
) -> int:
    """Insert the documents row with the manifest fields and the PDF metadata; return its id."""
    meta = doc.metadata or {}
    document_id = conn.execute(
        "INSERT INTO documents (run_id, path, sha256, size, part, volume, section, text_source, note,"
        " pdf_version, title, producer, creator, creation_date, mod_date, page_count)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            row.path,
            sha256,
            size,
            row.part,
            row.volume,
            row.section,
            row.text_source,
            row.note,
            meta.get("format") or None,
            meta.get("title") or None,
            meta.get("producer") or None,
            meta.get("creator") or None,
            meta.get("creationDate") or None,
            meta.get("modDate") or None,
            doc.page_count,
        ),
    ).lastrowid
    assert document_id is not None
    return document_id


def insert_toc(
    conn: sqlite3.Connection, document_id: int, doc: pymupdf.Document
) -> int:
    """Insert the bookmarks with 0-based page indexes (NULL without target); return their number."""
    toc = doc.get_toc(simple=True)
    conn.executemany(
        "INSERT INTO toc (document_id, position, level, title, page_index) VALUES (?, ?, ?, ?, ?)",
        [
            (document_id, position, level, title, page - 1 if page >= 1 else None)
            for position, (level, title, page) in enumerate(toc)
        ],
    )
    return len(toc)


def word_styles(words: list[tuple], blocks: list[dict]) -> list[tuple[Style, int]]:
    """Return per word the (font, size, flags) of the span with most of its characters, and the number of distinct styles.

    `words` and `blocks` must come from the same text page, so that the block
    and line numbers of a word point to its line in `blocks` (rawdict output).
    A character belongs to a word when its centre lies inside the word's box.
    """
    result = []
    for x0, y0, x1, y1, _text, block_no, line_no, _word_no in words:
        chars_per_style: Counter[Style] = Counter()
        for span in blocks[block_no]["lines"][line_no]["spans"]:
            style = (span["font"], span["size"], span["flags"])
            for char in span["chars"]:
                cx0, cy0, cx1, cy1 = char["bbox"]
                if x0 <= (cx0 + cx1) / 2 <= x1 and y0 <= (cy0 + cy1) / 2 <= y1:
                    chars_per_style[style] += 1
        style, _count = chars_per_style.most_common(1)[0]
        result.append((style, len(chars_per_style)))
    return result


def insert_page(
    conn: sqlite3.Connection, document_id: int, page: pymupdf.Page
) -> tuple[int, Counter[str]]:
    """Insert one page with its words and links; return the word count and the link count per kind."""
    textpage = page.get_textpage(flags=TEXT_FLAGS)
    label = page.get_label()
    page_id = conn.execute(
        "INSERT INTO pages (document_id, page_index, page_label, rotation, width, height, mediabox, text)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            document_id,
            page.number,
            label or None,
            page.rotation,
            page.rect.width,
            page.rect.height,
            json.dumps(list(page.mediabox)),
            page.get_text("text", textpage=textpage, sort=False),
        ),
    ).lastrowid

    words = page.get_text("words", textpage=textpage, sort=False)
    blocks = page.get_text("rawdict", textpage=textpage, sort=False)["blocks"]
    conn.executemany(
        "INSERT INTO words (page_id, block_no, line_no, word_no, x0, y0, x1, y1, text, font, size, flags, styles)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (page_id, b, ln, w, x0, y0, x1, y1, text, font, size, flags, styles)
            for (x0, y0, x1, y1, text, b, ln, w), ((font, size, flags), styles) in zip(
                words, word_styles(words, blocks), strict=True
            )
        ],
    )

    link_kinds: Counter[str] = Counter()
    for link in page.get_links():
        kind = LINK_KINDS.get(link["kind"], str(link["kind"]))
        link_kinds[kind] += 1
        rect = link["from"]
        conn.execute(
            "INSERT INTO links (page_id, kind, uri, target_page, x0, y0, x1, y1) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                page_id,
                kind,
                link.get("uri") if kind == "uri" else None,
                link.get("page") if kind == "goto" else None,
                rect.x0,
                rect.y0,
                rect.x1,
                rect.y1,
            ),
        )
    return len(words), link_kinds


def build(
    documents: list[DocumentRow], parts: list[PartRow], root: Path, out_dir: Path
) -> None:
    """Build crlb.sqlite and pdfs.sqlite in out_dir from the manifest rows."""
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = db.connect(out_dir / "crlb.sqlite")
    db.attach_pdfs(conn, out_dir / "pdfs.sqlite")
    options = {
        "text_flags": TEXT_FLAGS,
        "sort": False,
        "word_styles": "rawdict, character centres",
    }
    run_id = conn.execute(
        "INSERT INTO build_runs (started_at, git_commit, tool, tool_version, options) VALUES (?, ?, ?, ?, ?)",
        (
            utc_now(),
            git_commit(),
            "pymupdf",
            f"PyMuPDF {pymupdf.__version__}, MuPDF {pymupdf.mupdf_version}",
            json.dumps(options),
        ),
    ).lastrowid
    assert run_id is not None
    conn.executemany(
        "INSERT INTO parts (part, title, year, authors) VALUES (?, ?, ?, ?)",
        [(p.part, p.title, p.year, p.authors) for p in parts],
    )
    conn.commit()

    ids = {}
    for row in documents:
        started = time.monotonic()
        sha256, size = store_pdf(conn, root, row.path)
        # Extract from the stored bytes, so the text belongs to exactly that file
        doc = db.read_pdf(conn, row.path, sha256)
        detected = text_source_of(doc.metadata or {})
        if detected != row.text_source:
            print(
                f"warning: {row.path}: manifest says {row.text_source}, metadata suggests {detected}"
            )
        document_id = insert_document(conn, run_id, row, sha256, size, doc)
        ids[row.path] = document_id
        bookmarks = insert_toc(conn, document_id, doc)
        words = 0
        links: Counter[str] = Counter()
        for page in doc:
            page_words, page_links = insert_page(conn, document_id, page)
            words += page_words
            links += page_links
        conn.commit()
        link_counts = ", ".join(f"{k} {n}" for k, n in sorted(links.items())) or "none"
        print(
            f"{row.path}: {doc.page_count} pages, {words} words, links: {link_counts}, "
            f"{bookmarks} bookmarks ({time.monotonic() - started:.0f} s)"
        )

    conn.executemany(
        "UPDATE documents SET excerpt_of = ? WHERE id = ?",
        [(ids[row.excerpt_of], ids[row.path]) for row in documents if row.excerpt_of],
    )
    conn.execute("INSERT INTO pages_fts(pages_fts) VALUES ('rebuild')")
    conn.commit()
    conn.execute("ANALYZE")
    conn.close()


def configure(parser: argparse.ArgumentParser) -> None:
    """Add the arguments of this command to its parser."""
    parser.add_argument(
        "manifest",
        type=Path,
        help="documents.csv; parts.csv is read from the same folder",
    )
    parser.add_argument(
        "out_dir", type=Path, help="directory for crlb.sqlite and pdfs.sqlite"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="directory the manifest paths are relative to",
    )
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Check the manifests and build the databases."""
    # Refuse to overwrite, so a build is never mixed with an earlier one
    for name in ("crlb.sqlite", "pdfs.sqlite"):
        if (args.out_dir / name).exists():
            raise SystemExit(
                f"{args.out_dir / name} already exists; remove it or choose a new output directory"
            )
    documents = read_documents(args.manifest)
    parts = read_parts(args.manifest.parent / "parts.csv")
    if problems := validate(documents, parts, args.root):
        raise SystemExit("manifest problems:\n" + "\n".join(problems))
    started = time.monotonic()
    build(documents, parts, args.root, args.out_dir)
    print(f"{len(documents)} documents built in {time.monotonic() - started:.0f} s")
