"""Compare the answers of two LLM runs on the same stages, from `llm_calls`, without calling a model.

Per part of a stage (kind, holder, place, ...): how often the two models give
the same value. Also the share of rejected answers and the time per call of
each run. The console shows only counts; the differences, which contain CRLB
text, go to a CSV file in the review directory.
"""

import argparse
import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from crlb import db, llm
from crlb.extraction.llm_provenance import LISTS, SPANS, TASK

PARTS = ["kind", *SPANS, *LISTS, "uncertain"]


def answers(
    conn: sqlite3.Connection, run_id: int
) -> tuple[dict[tuple[int, int], dict[str, Any] | None], float]:
    """Return the answers of a run by word range (None if rejected) and its mean seconds per call."""
    rows = conn.execute(
        "SELECT first_word_id, last_word_id, output_json, valid, duration_ms FROM llm_calls"
        " WHERE run_table = 'ro_runs' AND run_id = ? AND task = ?",
        (run_id, TASK),
    ).fetchall()
    if not rows:
        raise SystemExit(f"run {run_id} has no {TASK} calls")
    found = {(row[0], row[1]): json.loads(row[2]) if row[3] else None for row in rows}
    return found, sum(row[4] for row in rows) / len(rows) / 1000


def compare(
    conn: sqlite3.Connection, run_a: int, run_b: int
) -> tuple[Counter[str], list[list[Any]]]:
    """Return the agreement counts of two runs and their differences."""
    a, seconds_a = answers(conn, run_a)
    b, seconds_b = answers(conn, run_b)
    counts: Counter[str] = Counter()
    for name, found, seconds in (("a", a, seconds_a), ("b", b, seconds_b)):
        counts[f"run {name}: calls"] = len(found)
        counts[f"run {name}: rejected"] = sum(1 for v in found.values() if v is None)
        counts[f"run {name}: ms per call"] = round(seconds * 1000)
    details = []
    for key in sorted(a.keys() & b.keys()):
        counts["stages answered by both"] += 1
        first, second = a[key], b[key]
        if first is None or second is None:
            counts["stages rejected in one or both"] += 1
            continue
        for part in PARTS:
            left, right = first.get(part), second.get(part)
            left = llm.normalise(str(left)) if left is not None else None
            right = llm.normalise(str(right)) if right is not None else None
            same = left == right
            counts[f"{part} {'same' if same else 'different'}"] += 1
            if not same:
                details.append([key[0], key[1], part, left, right])
    return counts, details


def configure(parser: argparse.ArgumentParser) -> None:
    """Add the arguments of this command to its parser."""
    parser.add_argument("db", type=Path, help="crlb.sqlite")
    parser.add_argument("run_a", type=int, help="an LLM provenance run (ro_runs)")
    parser.add_argument("run_b", type=int, help="another LLM provenance run")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Print the agreement of two LLM runs and write their differences."""
    conn = db.connect(args.db)
    counts, details = compare(conn, args.run_a, args.run_b)
    models = {
        run_id: json.loads(model or "{}").get("name", "?")
        for run_id, model in conn.execute(
            "SELECT id, model FROM ro_runs WHERE id IN (?, ?)", (args.run_a, args.run_b)
        )
    }
    conn.close()
    print(
        f"run a = {args.run_a} ({models.get(args.run_a)}), run b = {args.run_b} ({models.get(args.run_b)})"
    )
    for name, count in sorted(counts.items()):
        print(f"  {name}: {count}")
    review = args.db.parent / "review"
    review.mkdir(exist_ok=True)
    path = review / f"llm_compare_run{args.run_a}_run{args.run_b}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["first_word_id", "last_word_id", "part", "run_a", "run_b"])
        writer.writerows(details)
    print(f"  differences: {path}")
