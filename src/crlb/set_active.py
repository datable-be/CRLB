"""Make a run the active run of its step: the run that later steps and exports use.

A run becomes active only by this explicit command, after it has been
measured, never automatically. Older runs stay in the database for comparison.
"""

import argparse
from pathlib import Path

from crlb import db
from crlb.runs import utc_now

# The run table of each step; later steps add theirs
RUN_TABLES = {"2": "correction_runs"}


def configure(parser: argparse.ArgumentParser) -> None:
    """Add the arguments of this command to its parser."""
    parser.add_argument("db", type=Path, help="crlb.sqlite")
    parser.add_argument(
        "step", choices=sorted(RUN_TABLES), help="the step, e.g. 2 (correction)"
    )
    parser.add_argument(
        "run_id", type=int, help="id of the run in the run table of the step"
    )
    parser.add_argument("--note", help="why this run is made active")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Set the active run of a step after checking that the run exists."""
    conn = db.connect(args.db)
    table = RUN_TABLES[args.step]
    if (
        conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (args.run_id,)).fetchone()
        is None
    ):
        raise SystemExit(f"no run {args.run_id} in {table}")
    conn.execute(
        "INSERT INTO active_runs (step, run_id, set_at, note) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (step) DO UPDATE SET run_id = excluded.run_id, set_at = excluded.set_at, note = excluded.note",
        (args.step, args.run_id, utc_now(), args.note),
    )
    conn.commit()
    conn.close()
    print(f"step {args.step}: run {args.run_id} is active")
