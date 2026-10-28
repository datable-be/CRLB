"""Run step 4 by rules: objects, then exhibitions and literature, then provenance, each as its own run.

Reads the entries of the active segmentation run (step 3) with the text of the
active correction run (step 2), restricted to --sample. Writes one `ro_runs`
row per field; the references and provenance runs attach their rows to the
objects of the objects run made in the same call. The console shows only counts.
"""

import argparse
import dataclasses
import json
import sqlite3
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from crlb import db
from crlb.extraction import objects, provenance, references
from crlb.extraction.source import joined_text, load_entries, segmentation_run
from crlb.runs import git_commit, utc_now
from crlb.sample import SampleItem, add_sample_option
from crlb.text import CORRECTION_STEP, active_run

FIELDS = ("objects", "references", "provenance")

# The columns that hold text as written, per table: each must occur in the text of its source
VERBATIM = {
    "ro_objects": [
        "title_value",
        "object_name_text",
        "production_date_label",
        "material_note",
        "destruction_text",
    ],
    "ro_dimensions": ["dimensions_text", "dimension_note"],
    "ro_attributions": ["production_actor_label", "attribution_text"],
    "ro_collection_stays": [
        "holder_text",
        "collection_place_label",
        "collection_identifier",
        "collection_entry_date_text",
    ],
    "ro_auctions": [
        "auction_label",
        "auction_organizer_label",
        "auction_place_label",
        "auction_date_text",
        "auction_lot_number",
        "auction_buyer",
        "auction_price_amount",
    ],
    "ro_object_exhibitions": [
        "exhibition_reference",
        "exhibition_cat_number",
        "reference_text",
    ],
    "ro_object_sources": [
        "source_page_reference",
        "source_note",
        "reference_text",
    ],
}


def start_run(
    conn: sqlite3.Connection,
    field: str,
    segmentation: int,
    sample: list[SampleItem] | None,
    **options: int,
) -> int:
    """Insert a rules run for one field and return its id."""
    run_id = conn.execute(
        "INSERT INTO ro_runs (started_at, field, method, correction_run_id, segmentation_run_id, version, options)"
        " VALUES (?, ?, 'rules', ?, ?, ?, ?)",
        (
            utc_now(),
            field,
            active_run(conn, CORRECTION_STEP),
            segmentation,
            git_commit(),
            json.dumps(
                {
                    "sample": None
                    if sample is None
                    else [dataclasses.asdict(item) for item in sample],
                    **options,
                }
            ),
        ),
    ).lastrowid
    assert run_id is not None
    return run_id


def normalise(text: str) -> str:
    """Return text with runs of whitespace as one space."""
    return " ".join(text.split())


def verbatim_violations(conn: sqlite3.Connection, run_ids: list[int]) -> int:
    """Return the number of verbatim values of the runs that do not occur in the text of their source."""
    sources: dict[tuple[int, int], str] = {}
    missing = 0
    marks = ",".join("?" * len(run_ids))
    for table, columns in VERBATIM.items():
        rows = conn.execute(
            f"SELECT first_word_id, last_word_id, {', '.join(columns)} FROM {table} WHERE run_id IN ({marks})",
            run_ids,
        )
        for row in rows:
            key = (row[0], row[1])
            if key not in sources:
                sources[key] = normalise(joined_text(conn, *key))
            missing += sum(
                1
                for value in row[2:]
                if value is not None and normalise(value) not in sources[key]
            )
    return missing


def object_ids(conn: sqlite3.Connection, objects_run: int) -> dict[int, int]:
    """Return the objects of an objects run by the id of their entry or copy segment."""
    return dict(
        conn.execute(
            "SELECT segment_id, id FROM ro_objects WHERE run_id = ?", (objects_run,)
        ).fetchall()
    )


def extract(
    conn: sqlite3.Connection, sample: list[SampleItem] | None
) -> tuple[dict[str, tuple[int, Counter[str]]], int]:
    """Run the three rules runs on the entries of the sample; return each run's id and counts, and the number of entries."""
    segmentation = segmentation_run(conn)
    entries = load_entries(conn, segmentation, sample)
    if not entries:
        raise SystemExit("no entries in the active segmentation run match the sample")
    results: dict[str, tuple[int, Counter[str]]] = {}
    objects_run = start_run(conn, "objects", segmentation, sample)
    counts: Counter[str] = Counter()
    for entry in entries:
        objects.extract_entry(conn, objects_run, entry, counts)
    results["objects"] = (objects_run, counts)
    ids = object_ids(conn, objects_run)
    steps: list[tuple[str, Callable[..., None]]] = [
        ("references", references.extract_entry),
        ("provenance", provenance.extract_entry),
    ]
    for field, function in steps:
        run_id = start_run(conn, field, segmentation, sample, objects_run=objects_run)
        counts = Counter()
        for entry in entries:
            function(conn, run_id, entry, ids, counts)
        results[field] = (run_id, counts)
    conn.commit()
    results["objects"][1]["verbatim values not in their source (all runs)"] = (
        verbatim_violations(conn, [run_id for run_id, _ in results.values()])
    )
    return results, len(entries)


def print_results(results: dict[str, tuple[int, Counter[str]]], entries: int) -> None:
    """Print the counts of each run."""
    print(f"{entries} entries")
    for field, (run_id, counts) in results.items():
        print(f"{field} (run {run_id})")
        for name, value in sorted(counts.items()):
            print(f"  {name}: {value}")


def configure(parser: argparse.ArgumentParser) -> None:
    """Add the arguments of this command to its parser."""
    parser.add_argument("db", type=Path, help="crlb.sqlite")
    add_sample_option(parser)
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Run the extraction by rules and print the new run ids."""
    if not args.db.exists():
        raise SystemExit(f"{args.db} does not exist; run crlb build first")
    conn = db.connect(args.db)
    results, entries = extract(conn, args.sample)
    conn.close()
    print_results(results, entries)
    runs = " ".join(f"4:{field} {run_id}" for field, (run_id, _) in results.items())
    print(
        "Next:\n"
        "  check it:       the counts above\n"
        f"  make it active: crlb set-active {args.db} <step> <run> for each of: {runs}"
    )
