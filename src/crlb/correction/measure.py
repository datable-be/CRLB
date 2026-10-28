"""Measure a correction run against the hand-corrected specimen pages, raw text against corrected text.

Only the specimens whose PDF is in the database are measured. The split file
assigns each specimen to the development set (for tuning the rules) or the
test set (for the final figures). Superfluous and wrongly removed spaces are
counted from the edit operations against the ground truth. The console shows
only numbers.
"""

import argparse
import csv
import sqlite3
from pathlib import Path

from rapidfuzz.distance import Levenshtein

from crlb import db
from crlb.ocr.analyse_specimens import compare, normalise, rates
from crlb.text import page_text


def space_errors(gt: str, text: str) -> tuple[int, int]:
    """Return the spaces in text that are not in the ground truth, and the ground-truth spaces missing from text."""
    gt_n, text_n = normalise(gt), normalise(text)
    extra = missing = 0
    for op in Levenshtein.editops(gt_n, text_n):
        if op.tag in ("insert", "replace") and text_n[op.dest_pos] == " ":
            extra += 1
        if op.tag in ("delete", "replace") and gt_n[op.src_pos] == " ":
            missing += 1
    return extra, missing


def latest_run(conn: sqlite3.Connection) -> int:
    """Return the id of the most recent correction run."""
    run_id = conn.execute("SELECT max(id) FROM correction_runs").fetchone()[0]
    if run_id is None:
        raise SystemExit("no correction run yet; run crlb correct run first")
    return run_id


def measure_page(
    conn: sqlite3.Connection, page_id: int, run_id: int, gt: str
) -> dict[str, float]:
    """Return the error rates and space counts of one page, raw and corrected."""
    raw = page_text(conn, page_id, raw=True)
    corrected = page_text(conn, page_id, run_id)
    raw_extra, raw_missing = space_errors(gt, raw)
    extra, missing = space_errors(gt, corrected)
    return {
        **{f"{k}_raw": v for k, v in rates(compare(gt, raw)).items()},
        **{f"{k}_corrected": v for k, v in rates(compare(gt, corrected)).items()},
        "superfluous_spaces_raw": raw_extra,
        "superfluous_spaces_corrected": extra,
        "spaces_wrongly_removed": max(missing - raw_missing, 0),
    }


def measure(
    conn: sqlite3.Connection, specimens_dir: Path, split: Path, run_id: int
) -> list[dict]:
    """Measure every specimen whose document is in the database; return one row per specimen."""
    sets = {
        row["specimen_id"]: row["set"]
        for row in csv.DictReader(split.open(encoding="utf-8"))
    }
    documents = {
        Path(path).name: doc_id
        for doc_id, path in conn.execute("SELECT id, path FROM documents")
    }
    rows = []
    with (specimens_dir / "manifest.csv").open(encoding="utf-8") as f:
        for specimen in csv.DictReader(f):
            if specimen["file"] not in documents:
                continue
            page_id = conn.execute(
                "SELECT id FROM pages WHERE document_id = ? AND page_index = ?",
                (documents[specimen["file"]], int(specimen["page"]) - 1),
            ).fetchone()[0]
            gt = (specimens_dir / specimen["specimen_id"] / "gt.txt").read_text(
                encoding="utf-8"
            )
            rows.append(
                {
                    "specimen_id": specimen["specimen_id"],
                    "set": sets[specimen["specimen_id"]],
                    **measure_page(conn, page_id, run_id, gt),
                }
            )
    return rows


def configure(parser: argparse.ArgumentParser) -> None:
    """Add the arguments of this command to its parser."""
    parser.add_argument("db", type=Path, help="crlb.sqlite")
    parser.add_argument(
        "specimens_dir", type=Path, help="the specimen directory of crlb ocr sample"
    )
    parser.add_argument(
        "split", type=Path, help="specimen_split.csv: development or test per specimen"
    )
    parser.add_argument(
        "--run", type=int, help="correction run to measure; default: the latest"
    )
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Print the measurement per specimen, development pages first."""
    conn = db.connect(args.db)
    run_id = args.run if args.run is not None else latest_run(conn)
    rows = measure(conn, args.specimens_dir, args.split, run_id)
    print(f"correction run {run_id}, {len(rows)} specimens in the database")
    print(
        f"{'specimen':<28} {'set':<12} {'CER raw':>8} {'CER corr':>8} {'WER raw':>8} {'WER corr':>8}"
        f" {'extra sp raw':>12} {'extra sp corr':>13} {'wrongly removed':>15}"
    )
    for row in sorted(
        rows, key=lambda r: (r["set"] != "development", r["specimen_id"])
    ):
        print(
            f"{row['specimen_id']:<28} {row['set']:<12} {row['cer_raw']:>8.2%} {row['cer_corrected']:>8.2%}"
            f" {row['wer_raw']:>8.2%} {row['wer_corrected']:>8.2%} {row['superfluous_spaces_raw']:>12}"
            f" {row['superfluous_spaces_corrected']:>13} {row['spaces_wrongly_removed']:>15}"
        )
    conn.close()
