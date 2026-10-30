"""Run the provenance of step 4 with rules and a local LLM: rules first, the model for the stages that rules leave.

Needs a running model server (llama.cpp `llama-server`) and the active objects
run (`crlb set-active <db> 4:objects <run>`). Every call is stored in
`llm_calls`. With --compare-rules the model also answers the stages that rules
handled; those answers are only compared with the rules, not stored as rows.
The console shows only counts and timings; the comparison details, which
contain CRLB text, go to a CSV file in the review directory.
"""

import argparse
import csv
import dataclasses
import json
import sqlite3
import time
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from crlb import db, llm
from crlb.extraction import llm_provenance, provenance
from crlb.extraction.extract import object_ids
from crlb.extraction.provenance import Stage
from crlb.extraction.references import object_nodes
from crlb.extraction.source import Entry, Node, load_entries, segmentation_run
from crlb.runs import git_commit, utc_now
from crlb.sample import SampleItem, add_sample_option
from crlb.text import CORRECTION_STEP, active_run

MODELS = Path("data_manifest/models.csv")
# The parts of a stage compared between rules and the model
COMPARED = [
    "kind",
    "holder",
    "place",
    "date_text",
    "organiser",
    "lot",
    "consignor",
    "buyer",
    "price_amount",
    "currency",
    "entry_method",
    "collection_type",
    "uncertain",
]


def model_record(identity: dict[str, str]) -> dict[str, str]:
    """Return the manifest row of the model the server has loaded, matched by file name."""
    name = Path(identity["model_path"]).name
    with MODELS.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["file"] == name:
                return row
    raise SystemExit(f"the server's model {name!r} is not in {MODELS}")


def objects_run(conn: sqlite3.Connection) -> int:
    """Return the active objects run; the provenance rows attach to its objects."""
    run_id = active_run(conn, "4:objects")
    if run_id is None:
        raise SystemExit(
            "no active objects run; accept one first (crlb set-active <db> 4:objects <run>)"
        )
    return run_id


def start_run(
    conn: sqlite3.Connection,
    model: dict[str, str],
    identity: dict[str, str],
    prompt: llm_provenance.Prompt,
    segmentation: int,
    options: Mapping[str, object],
) -> int:
    """Insert the provenance run with its model, runtime and prompt hash; return its id."""
    run_id = conn.execute(
        "INSERT INTO ro_runs (started_at, field, method, model, runtime, prompt_sha, correction_run_id,"
        " segmentation_run_id, version, options) VALUES (?, 'provenance', 'llm', ?, ?, ?, ?, ?, ?, ?)",
        (
            utc_now(),
            json.dumps(model),
            f"llama.cpp server {identity['build']}",
            prompt.sha,
            active_run(conn, CORRECTION_STEP),
            segmentation,
            git_commit(),
            json.dumps(options),
        ),
    ).lastrowid
    assert run_id is not None
    return run_id


def value(stage: Stage | None, name: str, kind: str | None) -> str | None:
    """Return one compared part of a stage, as text."""
    if name == "kind":
        return kind
    if stage is None:
        return None
    found = getattr(stage, name)
    return None if found is None else llm.normalise(str(found))


class Asker:
    """Calls the model for stages, counts the answers and keeps the time."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        runtime: llm.Runtime,
        prompt: llm_provenance.Prompt,
        run_id: int,
        counts: Counter[str],
    ) -> None:
        """Remember what each call needs."""
        self.conn, self.runtime, self.prompt = conn, runtime, prompt
        self.run_id, self.counts = run_id, counts
        self.seconds = 0.0

    def __call__(self, items: list[Node], index: int) -> llm_provenance.Answer:
        """Ask the model for items[index], with the previous item as context."""
        started = time.monotonic()
        previous = items[index - 1].text.strip() if index else None
        answer = llm_provenance.ask(
            self.conn, self.runtime, self.prompt, self.run_id, items[index], previous
        )
        self.conn.commit()
        elapsed = time.monotonic() - started
        self.seconds += elapsed
        self.counts["llm: calls"] += 1
        self.counts["llm: answers rejected (schema, span or list)"] += not answer.valid
        self.counts["llm: answers 'other' (no holder or sale)"] += (
            answer.kind == "other"
        )
        print(f"  call {self.counts['llm: calls']}: {elapsed:.1f} s", flush=True)
        return answer


def compare_with_rules(
    entries: list[Entry], asker: Asker, counts: Counter[str]
) -> list[list[str | int | None]]:
    """Ask the model for the stages that rules handled; count agreement per part and return the differences."""
    details: list[list[str | int | None]] = []
    for entry in entries:
        for owner in object_nodes(entry):
            items = [
                item
                for field in owner.fields("provenance")
                for item in field.children
                if item.kind == "item"
            ]
            for index, item in enumerate(items):
                rules = provenance.parse_stage(item.text)
                if rules is None or rules.kind == "current":
                    continue
                answer = asker(items, index)
                counts["compared with rules: stages"] += 1
                if not answer.valid:
                    continue
                for name in COMPARED:
                    ours = value(rules, name, rules.kind)
                    theirs = value(answer.stage, name, answer.kind)
                    same = ours == theirs
                    counts[
                        f"compared with rules: {name} {'same' if same else 'different'}"
                    ] += 1
                    if not same:
                        details.append([item.first, item.last, name, ours, theirs])
    return details


def run_llm(
    conn: sqlite3.Connection,
    runtime: llm.Runtime,
    sample: list[SampleItem] | None,
    examples: Path,
    compare: bool,
) -> tuple[int, Counter[str], float, list[list[str | int | None]]]:
    """Run the provenance with rules and the model; return the run id, counts, model seconds and comparison details."""
    segmentation = segmentation_run(conn)
    objects = objects_run(conn)
    entries = load_entries(conn, segmentation, sample)
    if not entries:
        raise SystemExit("no entries in the active segmentation run match the sample")
    try:
        identity = runtime.identity()
    except OSError as error:
        raise SystemExit(f"no model server: {error}") from error
    prompt = llm_provenance.load_prompt(examples)
    options = {
        "sample": None
        if sample is None
        else [dataclasses.asdict(item) for item in sample],
        "objects_run": objects,
        "temperature": 0,
        "seed": llm.SEED,
        "compare_rules": compare,
    }
    run_id = start_run(
        conn, model_record(identity), identity, prompt, segmentation, options
    )
    counts: Counter[str] = Counter()
    asker = Asker(conn, runtime, prompt, run_id, counts)
    ids = object_ids(conn, objects)
    for entry in entries:
        provenance.extract_entry(
            conn,
            run_id,
            entry,
            ids,
            counts,
            lambda items, i: asker(items, i).stage,
        )
    conn.commit()
    details = compare_with_rules(entries, asker, counts) if compare else []
    return run_id, counts, asker.seconds, details


def configure(parser: argparse.ArgumentParser) -> None:
    """Add the arguments of this command to its parser."""
    parser.add_argument("db", type=Path, help="crlb.sqlite")
    parser.add_argument(
        "--llm",
        default="http://127.0.0.1:8080",
        help="URL of the llama.cpp server (default: %(default)s)",
    )
    parser.add_argument(
        "--examples",
        type=Path,
        default=llm_provenance.EXAMPLES,
        help="the prompt examples (default: %(default)s)",
    )
    parser.add_argument(
        "--compare-rules",
        action="store_true",
        help="also ask the model for the stages rules handled, and compare",
    )
    add_sample_option(parser)
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Run the provenance with the model and print counts, timings and the new run id."""
    if not args.db.exists():
        raise SystemExit(f"{args.db} does not exist; run crlb build first")
    conn = db.connect(args.db)
    run_id, counts, seconds, details = run_llm(
        conn, llm.LlamaServer(args.llm), args.sample, args.examples, args.compare_rules
    )
    conn.close()
    print(f"provenance (run {run_id})")
    for name, count in sorted(counts.items()):
        print(f"  {name}: {count}")
    calls = counts["llm: calls"]
    if calls:
        print(f"  llm: {seconds:.0f} s in all, {seconds / calls:.1f} s per call")
    if details:
        review = args.db.parent / "review"
        review.mkdir(exist_ok=True)
        path = review / f"llm_vs_rules_run{run_id}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["first_word_id", "last_word_id", "part", "rules", "llm"])
            writer.writerows(details)
        print(f"  differences with the rules: {path}")
    print(
        "Next:\n"
        "  check it:       the counts above and the review files\n"
        f"  make it active: crlb set-active {args.db} 4:provenance {run_id}"
    )
