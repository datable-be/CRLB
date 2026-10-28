"""Run step 2a: repair superfluous spaces (R1, R2) and soft-hyphenated line breaks (R3).

OCR documents get all rules, born-digital documents only R3. The raw words are
never changed: the result is a new correction run in `correction_runs`,
`corrected_words` (one token per raw word range) and `correction_flags`. Every
page is checked: with whitespace and soft hyphens removed, its text must be
unchanged. The console shows only counts.
"""

import argparse
import dataclasses
import json
import sqlite3
import time
from collections import Counter
from pathlib import Path

from crlb import db
from crlb.correction.lexicon import count_page
from crlb.correction.rules import (
    ALL_RULES,
    Flag,
    Lexicon,
    Options,
    Token,
    check_page,
    correct_page,
)
from crlb.correction.tokens import Word
from crlb.runs import git_commit, utc_now
from crlb.sample import SampleItem, add_sample_option, sample_parts

RULES_BY_SOURCE = {"ocr": ALL_RULES, "born_digital": ("R3",)}

type Box = tuple[float, float, float, float]


def document_pages(
    conn: sqlite3.Connection, document_id: int
) -> list[tuple[int, list[Word], dict[int, Box]]]:
    """Return per page of a document its id, its words in stored order and their boxes."""
    pages = []
    for (page_id,) in conn.execute(
        "SELECT id FROM pages WHERE document_id = ? ORDER BY page_index", (document_id,)
    ).fetchall():
        rows = conn.execute(
            "SELECT id, text, block_no, line_no, x0, y0, x1, y1 FROM words WHERE page_id = ? ORDER BY id",
            (page_id,),
        ).fetchall()
        words = [Word(r[0], r[1], r[2], r[3]) for r in rows]
        pages.append((page_id, words, {r[0]: (r[4], r[5], r[6], r[7]) for r in rows}))
    return pages


def union_box(boxes: dict[int, Box], first: int, last: int) -> Box:
    """Return the union of the boxes of the words first..last."""
    parts = [boxes[i] for i in range(first, last + 1)]
    return (
        min(b[0] for b in parts),
        min(b[1] for b in parts),
        max(b[2] for b in parts),
        max(b[3] for b in parts),
    )


def insert_page(
    conn: sqlite3.Connection,
    run_id: int,
    page_id: int,
    boxes: dict[int, Box],
    tokens: list[Token],
    flags: list[Flag],
) -> None:
    """Store the tokens and flags of one page."""
    conn.executemany(
        "INSERT INTO corrected_words (run_id, page_id, first_word_id, last_word_id, text, x0, y0, x1, y1, rule, reason)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                run_id,
                page_id,
                t.first,
                t.last,
                t.text,
                *union_box(boxes, t.first, t.last),
                t.rule,
                t.reason,
            )
            for t in tokens
        ],
    )
    conn.executemany(
        "INSERT INTO correction_flags (run_id, page_id, first_word_id, last_word_id, rule, candidate, reason)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (run_id, page_id, f.first, f.last, f.rule, f.candidate, f.reason)
            for f in flags
        ],
    )


def correct(
    conn: sqlite3.Connection, options: Options, sample: list[SampleItem] | None = None
) -> int:
    """Run step 2a on the documents (of the sample, if given); return the id of the new correction run."""
    lexicon = Lexicon.load(conn)
    if not lexicon.born_digital:
        raise SystemExit("the lexicon is empty; run crlb lexicon first")
    sources = conn.execute("SELECT count(*) FROM lexicon_sources").fetchone()[0]
    run_options = {
        **dataclasses.asdict(options),
        "sample": None
        if sample is None
        else [dataclasses.asdict(item) for item in sample],
        "lexicon": {
            "sources": sources,
            "forms": len(lexicon.born_digital),
            "bigrams": len(lexicon.bigrams),
        },
    }
    run_id = conn.execute(
        "INSERT INTO correction_runs (started_at, step, version, options) VALUES (?, '2a', ?, ?)",
        (utc_now(), git_commit(), json.dumps(run_options)),
    ).lastrowid
    assert run_id is not None

    parts = sample_parts(sample)
    documents = conn.execute(
        "SELECT id, path, part, text_source FROM documents ORDER BY id"
    ).fetchall()
    for document_id, path, part, text_source in documents:
        if parts is not None and part not in parts:
            continue
        started = time.monotonic()
        pages = document_pages(conn, document_id)
        # Forms that occur unsplit in the document itself can accept a join (R2)
        lexicon.document = Counter()
        for _, words, _ in pages:
            count_page(words, lexicon.document)
        joins: Counter[str] = Counter()
        flagged: Counter[str] = Counter()
        for page_id, words, boxes in pages:
            tokens, flags = correct_page(
                words, lexicon, options, RULES_BY_SOURCE[text_source]
            )
            check_page(words, tokens)
            insert_page(conn, run_id, page_id, boxes, tokens, flags)
            joins.update(t.rule for t in tokens if t.rule)
            flagged.update(f.rule for f in flags)
        conn.commit()
        print(
            f"{path}: joins {dict(sorted(joins.items()))}, flags {dict(sorted(flagged.items()))} "
            f"({time.monotonic() - started:.0f} s)"
        )
    return run_id


def configure(parser: argparse.ArgumentParser) -> None:
    """Add the arguments of this command to its parser."""
    defaults = Options()
    parser.add_argument("db", type=Path, help="crlb.sqlite")
    add_sample_option(parser)
    parser.add_argument(
        "--min-doc-count",
        type=int,
        default=defaults.min_doc_count,
        help="occurrences in the same document that accept a joined form",
    )
    parser.add_argument(
        "--max-window",
        type=int,
        default=defaults.max_window,
        help="most tokens joined by R2",
    )
    parser.add_argument(
        "--min-count-word-end",
        type=int,
        default=defaults.min_count_word_end,
        help="born-digital count a join needs if its last piece is a word",
    )
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Run the correction and print the new run id."""
    if not args.db.exists():
        raise SystemExit(f"{args.db} does not exist; run crlb build first")
    conn = db.connect(args.db)
    options = Options(args.min_doc_count, args.max_window, args.min_count_word_end)
    run_id = correct(conn, options, args.sample)
    conn.close()
    print(
        f"correction run {run_id}. Next:\n"
        f"  check it:       crlb correct measure {args.db} <specimens_dir> <split.csv> --run {run_id}\n"
        f"                  crlb correct show {args.db} <document> <page>... --run {run_id}\n"
        f"  make it active: crlb set-active {args.db} 2 {run_id}   (step 2, run {run_id})"
    )
