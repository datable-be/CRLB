"""Make a run the active run of its step: the run that later steps and exports use.

A run becomes active only by this explicit command, after it has been
measured, never automatically. Older runs stay in the database for comparison.
"""

import argparse
from pathlib import Path

from crlb import db
from crlb.extraction.extract import FIELDS
from crlb.runs import utc_now

# The run table of each step; step 4 has one active run per field, all in ro_runs
RUN_TABLES = {
    "2": "correction_runs",
    "3": "segmentation_runs",
    **{f"4:{field}": "ro_runs" for field in FIELDS},
}


def configure(parser: argparse.ArgumentParser) -> None:
    """Add the arguments of this command to its parser."""
    parser.add_argument("db", type=Path, help="crlb.sqlite")
    parser.add_argument(
        "step",
        choices=sorted(RUN_TABLES),
        help="the step, e.g. 2 (correction) or 4:provenance (extraction)",
    )
    parser.add_argument(
        "run_id", help="id of the run in the run table of the step, or 'latest'"
    )
    parser.add_argument("--note", help="why this run is made active")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Set the active run of a step after checking that the run exists."""
    conn = db.connect(args.db)
    table = RUN_TABLES[args.step]
    # A step 4 run belongs to one field
    _, _, field = args.step.partition(":")
    where, params = ("field = ?", (field,)) if field else ("1", ())
    suffix = f" for field {field}" if field else ""
    if args.run_id == "latest":
        run_id = conn.execute(
            f"SELECT max(id) FROM {table} WHERE {where}", params
        ).fetchone()[0]
        if run_id is None:
            raise SystemExit(f"no run in {table} yet{suffix}")
    elif not args.run_id.isdigit():
        raise SystemExit(f"run id must be a number or 'latest', not {args.run_id!r}")
    else:
        run_id = int(args.run_id)
        if (
            conn.execute(
                f"SELECT 1 FROM {table} WHERE id = ? AND {where}", (run_id, *params)
            ).fetchone()
            is None
        ):
            raise SystemExit(f"no run {run_id} in {table}{suffix}")
    conn.execute(
        "INSERT INTO active_runs (step, run_id, set_at, note) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (step) DO UPDATE SET run_id = excluded.run_id, set_at = excluded.set_at, note = excluded.note",
        (args.step, run_id, utc_now(), args.note),
    )
    conn.commit()
    conn.close()
    print(f"step {args.step}: run {run_id} is active")
