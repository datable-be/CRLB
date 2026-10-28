"""Run step 3: segment the documents into furniture, sections and entries, with the per-volume configuration.

Covers the main documents whose part has a configuration in the configuration
directory. Matching uses the corrected text of the active correction run; the
segments are ranges of raw word ids. The console shows only counts and the
results of the checks.
"""

import argparse
import dataclasses
import json
import sqlite3
import time
from pathlib import Path

from crlb import db
from crlb.runs import git_commit, utc_now
from crlb.sample import SampleItem, add_sample_option, sample_parts
from crlb.segmentation import checks, rules
from crlb.segmentation.config import Config, load_configs
from crlb.segmentation.model import Seg, load_document
from crlb.text import CORRECTION_STEP, active_run

CONFIG_DIR = Path("data_manifest/segmentation")


def insert_segments(
    conn: sqlite3.Connection,
    run_id: int,
    document_id: int,
    segs: list[Seg],
    parent: int | None = None,
) -> None:
    """Store segments and their children, depth first."""
    for seg in segs:
        seg_id = conn.execute(
            "INSERT INTO segments (run_id, document_id, parent_id, kind, label, first_word_id, last_word_id,"
            " rule, confidence, reason, link_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                document_id,
                parent,
                seg.kind,
                seg.label,
                seg.first,
                seg.last,
                seg.rule,
                seg.confidence,
                seg.reason,
                seg.link_id,
            ),
        ).lastrowid
        insert_segments(conn, run_id, document_id, seg.children, seg_id)


def segment_document(
    conn: sqlite3.Connection,
    run_id: int,
    document_id: int,
    config: Config,
    correction_run: int | None,
) -> dict[str, int]:
    """Segment one document and store the result; return the counts and check results."""
    doc = load_document(conn, document_id, correction_run)
    furniture = rules.furniture(doc, config)
    printed = rules.printed_pages(doc, furniture)
    sections = rules.sections(doc, config, furniture)
    counts = {"furniture": len(furniture), "sections": len(sections)}
    furniture_starts = [s.first for s in furniture]
    for section in sections:
        if section.label != "catalogue":
            continue
        section.children, dropped = rules.entries(
            doc, section, config, furniture_starts
        )
        counts |= checks.entry_checks(doc, section, section.children, dropped, config)
    counts |= checks.page_checks(printed)

    insert_segments(conn, run_id, document_id, furniture + sections)
    page_ids = dict(
        conn.execute(
            "SELECT page_index, id FROM pages WHERE document_id = ?", (document_id,)
        ).fetchall()
    )
    conn.executemany(
        "INSERT INTO printed_pages (run_id, page_id, printed, rule) VALUES (?, ?, ?, ?)",
        [(run_id, page_ids[index], number, rule) for index, number, rule in printed],
    )
    return counts


def segment(
    conn: sqlite3.Connection,
    configs: dict[str, Config],
    sample: list[SampleItem] | None = None,
) -> int:
    """Segment the configured main documents (of the sample, if given); return the id of the new run."""
    correction_run = active_run(conn, CORRECTION_STEP)
    if correction_run is None:
        print("warning: no active correction run; matching on the raw text")
    options = {
        "configs": {
            part: {"path": c.path, "sha256": c.sha256} for part, c in configs.items()
        },
        "sample": None
        if sample is None
        else [dataclasses.asdict(item) for item in sample],
    }
    run_id = conn.execute(
        "INSERT INTO segmentation_runs (started_at, correction_run_id, version, options) VALUES (?, ?, ?, ?)",
        (utc_now(), correction_run, git_commit(), json.dumps(options)),
    ).lastrowid
    assert run_id is not None
    parts = sample_parts(sample)
    documents = conn.execute(
        "SELECT id, path, part FROM documents WHERE section = 'main' ORDER BY id"
    ).fetchall()
    for document_id, path, part in documents:
        if part not in configs or (parts is not None and part not in parts):
            continue
        started = time.monotonic()
        counts = segment_document(
            conn, run_id, document_id, configs[part], correction_run
        )
        conn.commit()
        print(f"{path} ({time.monotonic() - started:.0f} s)")
        for name, value in counts.items():
            print(f"  {name}: {value}")
    return run_id


def configure(parser: argparse.ArgumentParser) -> None:
    """Add the arguments of this command to its parser."""
    parser.add_argument("db", type=Path, help="crlb.sqlite")
    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_DIR,
        help="directory of the per-volume configurations",
    )
    add_sample_option(parser)
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Run the segmentation and print the new run id."""
    if not args.db.exists():
        raise SystemExit(f"{args.db} does not exist; run crlb build first")
    conn = db.connect(args.db)
    run_id = segment(conn, load_configs(args.config), args.sample)
    conn.close()
    print(
        f"segmentation run {run_id}. Next:\n"
        f"  check it:       the counts and checks above\n"
        f"  make it active: crlb set-active {args.db} 3 {run_id}   (step 3, run {run_id})"
    )
