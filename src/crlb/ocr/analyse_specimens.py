"""Compare corrected ground truth (gt.txt) with the OCR text (ocr.txt) of each specimen.

Results are written as CSV files to the specimens directory; the console shows
only counts and error rates, never text.
"""

import argparse
import csv
import re
import unicodedata
from collections import Counter
from pathlib import Path

from rapidfuzz.distance import Levenshtein

GROUP_KEYS = ["file", "ocr_year", "section"]
TOP_CONFUSIONS = 200


def normalise(text: str) -> str:
    """Join soft-hyphenated line breaks and collapse whitespace, keeping case and punctuation."""
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"\xad\s*", "", text)
    return " ".join(text.split())


def loosen(text: str) -> str:
    """Lowercase and drop punctuation from normalised text."""
    kept = "".join(
        c for c in text.lower() if not unicodedata.category(c).startswith("P")
    )
    return " ".join(kept.split())


def compare(gt: str, ocr: str) -> dict[str, int]:
    """Return edit counts between ground truth and OCR at character and word level."""
    gt_n, ocr_n = normalise(gt), normalise(ocr)
    ops = Counter(op.tag for op in Levenshtein.editops(gt_n, ocr_n))
    gt_loose = loosen(gt_n)
    return {
        "gt_chars": len(gt_n),
        "char_errors": Levenshtein.distance(gt_n, ocr_n),
        "substitutions": ops["replace"],
        "insertions": ops["insert"],
        "deletions": ops["delete"],
        "gt_words": len(gt_n.split()),
        "word_errors": Levenshtein.distance(gt_n.split(), ocr_n.split()),
        "gt_chars_loose": len(gt_loose),
        "char_errors_loose": Levenshtein.distance(gt_loose, loosen(ocr_n)),
    }


def confusions(gt: str, ocr: str) -> Counter[tuple[str, str]]:
    """Count (ground truth, OCR) segment pairs, merging adjacent edits into one confusion."""
    gt_n, ocr_n = normalise(gt), normalise(ocr)
    found: Counter[tuple[str, str]] = Counter()
    span: list[int] | None = (
        None  # [gt_start, gt_end, ocr_start, ocr_end] of the current edit run
    )
    for op in Levenshtein.opcodes(gt_n, ocr_n):
        if op.tag != "equal":
            if span is None:
                span = [op.src_start, op.src_end, op.dest_start, op.dest_end]
            else:
                span[1], span[3] = op.src_end, op.dest_end
        elif span is not None:
            found[(gt_n[span[0] : span[1]], ocr_n[span[2] : span[3]])] += 1
            span = None
    if span is not None:
        found[(gt_n[span[0] : span[1]], ocr_n[span[2] : span[3]])] += 1
    return found


def rates(counts: dict[str, int]) -> dict[str, float]:
    """Return CER, loose CER and WER as fractions of the ground-truth length."""
    return {
        "cer": counts["char_errors"] / max(counts["gt_chars"], 1),
        "cer_loose": counts["char_errors_loose"] / max(counts["gt_chars_loose"], 1),
        "wer": counts["word_errors"] / max(counts["gt_words"], 1),
    }


def summarise(rows: list[dict]) -> list[dict]:
    """Aggregate error counts overall and per group, pooling counts before computing rates."""
    summary = []
    groups = [("all", "all")] + sorted(
        {(key, str(row[key])) for row in rows for key in GROUP_KEYS}
    )
    count_fields = [
        "gt_chars",
        "char_errors",
        "gt_words",
        "word_errors",
        "gt_chars_loose",
        "char_errors_loose",
    ]
    for key, value in groups:
        members = [row for row in rows if key == "all" or str(row[key]) == value]
        totals = {field: sum(row[field] for row in members) for field in count_fields}
        summary.append(
            {
                "group": key,
                "value": value,
                "specimens": len(members),
                **totals,
                **rates(totals),
            }
        )
    return summary


def write_csv(path: Path, rows: list[dict]) -> None:
    """Write a list of dicts to a CSV file."""
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def analyse(specimens_dir: Path) -> tuple[list[dict], list[dict], int]:
    """Compare every corrected specimen and return result rows, summary rows and the skipped count."""
    with (specimens_dir / "manifest.csv").open(encoding="utf-8") as f:
        manifest = list(csv.DictReader(f))

    rows, skipped, all_confusions = [], 0, Counter()
    for entry in manifest:
        specimen_dir = specimens_dir / entry["specimen_id"]
        gt = (specimen_dir / "gt.txt").read_text(encoding="utf-8")
        ocr = (specimen_dir / "ocr.txt").read_text(encoding="utf-8")
        # An unchanged gt.txt means the specimen has not been corrected yet
        if gt == ocr:
            skipped += 1
            continue
        counts = compare(gt, ocr)
        rows.append({**entry, **counts, **rates(counts)})
        all_confusions += confusions(gt, ocr)

    if rows:
        summary = summarise(rows)
        write_csv(specimens_dir / "results.csv", rows)
        write_csv(specimens_dir / "summary.csv", summary)
        top = [
            {"gt": g, "ocr": o, "count": n}
            for (g, o), n in all_confusions.most_common(TOP_CONFUSIONS)
        ]
        if top:
            write_csv(specimens_dir / "confusions.csv", top)
    else:
        summary = []
    return rows, summary, skipped


def configure(parser: argparse.ArgumentParser) -> None:
    """Add the arguments of this command to its parser."""
    parser.add_argument(
        "specimens_dir", type=Path, help="directory written by `crlb ocr sample`"
    )
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Run the analysis and print the summary rates."""
    rows, summary, skipped = analyse(args.specimens_dir)
    print(
        f"{len(rows)} corrected specimens analysed, {skipped} not yet corrected (skipped)"
    )
    for s in summary:
        print(
            f"{s['group']:>8} {s['value']:<55} n={s['specimens']:<3} "
            f"CER {s['cer']:6.2%}  CER loose {s['cer_loose']:6.2%}  WER {s['wer']:6.2%}"
        )
    if rows:
        print(
            f"Details in {args.specimens_dir}/results.csv, summary.csv, confusions.csv"
        )
