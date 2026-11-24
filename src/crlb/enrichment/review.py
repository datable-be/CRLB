"""Write the review file of a normalisation run (step 5b): one CSV row per value.

Each row gives the entry, the column, the value, the source text of its
provenance stage, the normalised value with its rule and status, the cluster,
the three best candidates with their scores and evidence, and an empty `ok`
column for the reviewer. Prints only counts.
"""

import argparse
import csv
import json
import sqlite3
from pathlib import Path

from crlb import db
from crlb.extraction.source import joined_text

REVIEW_FILE = Path("data/poc/review/normalisation.csv")


def review_rows(conn: sqlite3.Connection, run_id: int) -> list[dict[str, str]]:
    """Return one review row per normalised value of a run, with the source text of its row."""
    rows = []
    for row in conn.execute(
        "SELECT n.*, c.label AS cluster_label, c.id AS cluster FROM normalised_values n"
        " JOIN clusters c ON c.id = n.cluster_id WHERE n.run_id = ? ORDER BY n.id",
        (run_id,),
    ).fetchall():
        source = conn.execute(
            f"SELECT s.first_word_id, s.last_word_id, o.part, o.crlb_number FROM {row['table_name']} s"
            " JOIN ro_objects o ON o.id = s.object_id WHERE s.id = ?",
            (row["row_id"],),
        ).fetchone()
        found = json.loads(row["candidates"] or "[]")
        entry = {
            "id": str(row["id"]),
            "entry": f"{source['part']} {source['crlb_number']}",
            "column": row["column_name"],
            "value": row["value_text"],
            "source text": joined_text(
                conn, source["first_word_id"], source["last_word_id"]
            ),
            "normalised": row["normalised_value"] or "",
            "rule": row["rule"],
            "status": row["status"],
            "cluster": f"{row['cluster']}: {row['cluster_label']}",
        }
        for k in range(3):
            c = found[k] if k < len(found) else None
            entry[f"candidate {k + 1}"] = (
                f"{c['label']} [{c['vocabulary']}] {c['score']} ({'; '.join(c['evidence']) or 'name only'})"
                if c
                else ""
            )
        entry["ok"] = ""
        rows.append(entry)
    return rows


def configure(parser: argparse.ArgumentParser) -> None:
    """Add the arguments of the review command to its parser."""
    parser.add_argument("db", type=Path, help="crlb.sqlite")
    parser.add_argument(
        "--run", type=int, help="normalisation run (default: the latest)"
    )
    parser.add_argument(
        "--out", type=Path, default=REVIEW_FILE, help="CSV file to write"
    )
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Write the review file of a normalisation run and print its counts."""
    conn = db.connect(args.db)
    run_id = (
        args.run
        or conn.execute(
            "SELECT MAX(id) FROM enrichment_runs WHERE part_of_step = '5b'"
        ).fetchone()[0]
    )
    if run_id is None:
        raise SystemExit("no normalisation run yet; run crlb normalise run first")
    rows = review_rows(conn, run_id)
    conn.close()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["id"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"{args.out}: {len(rows)} values of normalisation run {run_id}")
