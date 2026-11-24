"""Run step 2b: character substitutions from a per-volume table, on top of a 2a run.

S1 replaces one or two OCR misreadings from the table (`d` for the ct ligature,
`ft` for the st ligature, ...) in a token whose form is not in the born-digital
lexicon, and accepts the result only if exactly one candidate is a lexicon form.
S2 lowercases a capital that the OCR gave to a ligature inside a word (`KunSt`).
Only volumes with rows in the table are changed. The result is a new correction
run, based on the 2a run, with a full token layer: unchanged tokens are copied
with their 2a rule. Every page is checked: the tokens keep their word ranges and
change only by substitutions from the table. The console shows only counts; the
review sample with text goes to a local CSV file.
"""

import argparse
import csv
import dataclasses
import hashlib
import json
import random
import sqlite3
from collections import Counter
from dataclasses import dataclass
from itertools import combinations, pairwise
from pathlib import Path

from crlb import db
from crlb.correction.rules import Flag, InvariantError, Lexicon
from crlb.correction.tokens import EDGE_PUNCTUATION, form
from crlb.runs import git_commit, utc_now
from crlb.sample import add_sample_option, sample_parts
from crlb.text import CORRECTION_STEP, active_run

REVIEW_SAMPLE = 200
CONTEXT = 3  # tokens shown before and after a word in the review file
SEED = 2


@dataclass(frozen=True)
class Substitution:
    """One row of the table: what the OCR read, what was printed, and where it may apply."""

    rule: str  # 'S1' or 'S2'
    ocr: str
    correct: str
    position: (
        str  # 'any'; 'inner': never at the first letter; 'word': the whole word only
    )


@dataclass(frozen=True)
class Change:
    """A substituted token: its new text, rule and reason."""

    text: str
    rule: str
    reason: str


def read_table(path: Path) -> dict[str, list[Substitution]]:
    """Return the substitutions of the table per part."""
    table: dict[str, list[Substitution]] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            table.setdefault(row["part"], []).append(
                Substitution(row["rule"], row["ocr"], row["correct"], row["position"])
            )
    return table


def split_core(text: str) -> tuple[str, str, str]:
    """Split a token into leading punctuation, word core and trailing punctuation."""
    lead = EDGE_PUNCTUATION.match(text)
    start = lead.end() if lead else 0
    trail = EDGE_PUNCTUATION.search(text, start)
    end = trail.start() if trail and trail.end() == len(text) else len(text)
    return text[:start], text[start:end], text[end:]


def variants(
    core: str, subs: list[Substitution], most: int = 2
) -> dict[str, list[str]]:
    """Return every text made by up to `most` non-overlapping substitutions, with the substitutions used."""
    out: dict[str, list[str]] = {}
    for s in subs:
        if s.position == "word" and core in (s.ocr, s.ocr.capitalize()):
            correct = s.correct if core == s.ocr else s.correct.capitalize()
            out[correct] = [f"{core}→{correct} (word)"]
    places = [
        (i, i + len(s.ocr), s)
        for s in subs
        if s.position != "word"
        for i in range(len(core))
        if core.startswith(s.ocr, i) and not (s.position == "inner" and i == 0)
    ]
    for n in range(1, most + 1):
        for chosen in combinations(sorted(places, key=lambda p: p[0]), n):
            if any(a[1] > b[0] for a, b in pairwise(chosen)):
                continue
            text, last = [], 0
            for start, end, s in chosen:
                text += [core[last:start], s.correct]
                last = end
            text.append(core[last:])
            out.setdefault("".join(text), [f"{s.ocr}→{s.correct}" for *_, s in chosen])
    return out


def s1(
    core: str, subs: list[Substitution], lexicon: Lexicon, min_count: int
) -> tuple[str, str] | list[str] | None:
    """Return the one lexicon candidate of an unknown word with its reason, the candidates if there are several, or None."""
    f = form(core)
    if f is None or f in lexicon.born_digital or (len(core) > 1 and core.isupper()):
        return None
    # A whole-word row decides a word the lexicon cannot ('faft': fact or fast)
    words = variants(core, [s for s in subs if s.position == "word"])
    if words:
        text, used = next(iter(words.items()))
        return text, f"{', '.join(used)}; table"
    found = {}
    for text, used in variants(core, subs).items():
        count = lexicon.born_digital.get(form(text) or "", 0)
        if count >= min_count:
            found[text] = f"{', '.join(used)}; lexicon bd={count}"
    if len(found) == 1:
        return next(iter(found.items()))
    return sorted(found) or None


def s2(
    core: str, subs: list[Substitution], lexicon: Lexicon, min_count: int
) -> tuple[str, str] | None:
    """Return the word with an inner capital of a ligature lowercased, if that is a lexicon word."""
    for s in subs:
        i = core.find(s.ocr, 1)
        if i < 1 or not core[i - 1].islower():
            continue
        text = core[:i] + s.correct + core[i + len(s.ocr) :]
        count = lexicon.born_digital.get(form(text) or "", 0)
        if text[1:].islower() and count >= min_count:
            return text, f"{s.ocr}→{s.correct}; lexicon bd={count}"
    return None


def substitute(
    text: str, subs: list[Substitution], lexicon: Lexicon, min_count: int
) -> Change | list[str] | None:
    """Return the change of a token, the candidates to flag, or None to keep it."""
    lead, core, trail = split_core(text)
    rule, reasons = [], []
    result = s1(core, [s for s in subs if s.rule == "S1"], lexicon, min_count)
    if isinstance(result, list):
        return result
    if result is not None:
        core, reason = result
        rule.append("S1")
        reasons.append(reason)
    cased = s2(core, [s for s in subs if s.rule == "S2"], lexicon, min_count)
    if cased is not None:
        core, reason = cased
        rule.append("S2")
        reasons.append(reason)
    if not rule:
        return None
    return Change(lead + core + trail, "+".join(rule), " | ".join(reasons))


def reachable(old: str, new: str, subs: list[Substitution]) -> bool:
    """Return whether new is old with only substitutions from the table: S1 (up to two), then S2."""
    lead, core, trail = split_core(old)
    s1_subs = [s for s in subs if s.rule == "S1"]
    s2_subs = [s for s in subs if s.rule == "S2"]
    for text in [core, *variants(core, s1_subs)]:
        for final in [text, *variants(text, s2_subs, most=1)]:
            if lead + final + trail == new:
                return True
    return False


def check_changes(
    tokens: dict[tuple[int, int], str],
    changes: dict[tuple[int, int], Change],
    subs: list[Substitution],
) -> None:
    """Raise InvariantError unless every change is on a token of the base run and made only by the table."""
    for key, change in changes.items():
        if key not in tokens:
            raise InvariantError(f"token {key} is not a token of the base run")
        if not reachable(tokens[key], change.text, subs):
            raise InvariantError(
                f"token {key} changed by more than the substitution table"
            )


def run_substitution(
    conn: sqlite3.Connection,
    table_path: Path,
    based_on: int,
    min_count: int,
    parts: set[str] | None,
) -> tuple[int, list[dict[str, str]]]:
    """Write a 2b run on top of a correction run; return its id and the changes and flags for review."""
    lexicon = Lexicon.load(conn)
    if not lexicon.born_digital:
        raise SystemExit("the lexicon is empty; run crlb lexicon first")
    table = read_table(table_path)
    options = {
        "min_count": min_count,
        "table": {
            "file": table_path.name,
            "sha256": hashlib.sha256(table_path.read_bytes()).hexdigest(),
            "rows": {
                p: [dataclasses.asdict(s) for s in subs] for p, subs in table.items()
            },
        },
        "parts": None if parts is None else sorted(parts),
    }
    run_id = conn.execute(
        "INSERT INTO correction_runs (started_at, step, based_on, version, options) VALUES (?, '2b', ?, ?, ?)",
        (utc_now(), based_on, git_commit(), json.dumps(options, ensure_ascii=False)),
    ).lastrowid
    assert run_id is not None
    review: list[dict[str, str]] = []
    documents = conn.execute(
        "SELECT id, path, part FROM documents ORDER BY id"
    ).fetchall()
    for document_id, path, part in documents:
        if parts is not None and part not in parts:
            continue
        subs = table.get(part, [])
        # The whole token layer of the base run, copied unchanged ...
        conn.execute(
            "INSERT INTO corrected_words (run_id, page_id, first_word_id, last_word_id, text, x0, y0, x1, y1, rule, reason)"
            " SELECT ?, c.page_id, c.first_word_id, c.last_word_id, c.text, c.x0, c.y0, c.x1, c.y1, c.rule, c.reason"
            " FROM corrected_words c JOIN pages p ON p.id = c.page_id"
            " WHERE c.run_id = ? AND p.document_id = ? ORDER BY c.id",
            (run_id, based_on, document_id),
        )
        rules: Counter[str] = Counter()
        flags: list[tuple[int, Flag]] = []
        if subs:
            rows = conn.execute(
                "SELECT c.page_id, p.page_index, c.first_word_id, c.last_word_id, c.text"
                " FROM corrected_words c JOIN pages p ON p.id = c.page_id"
                " WHERE c.run_id = ? AND p.document_id = ? ORDER BY c.id",
                (based_on, document_id),
            ).fetchall()
            texts = {(r[2], r[3]): r[4] for r in rows}
            changes: dict[tuple[int, int], Change] = {}
            pages: dict[tuple[int, int], int] = {}
            for i, (page_id, page_index, first, last, text) in enumerate(rows):
                result = substitute(text, subs, lexicon, min_count)
                if result is None:
                    continue
                before = " ".join(
                    r[4] for r in rows[max(i - CONTEXT, 0) : i] if r[0] == page_id
                )
                after = " ".join(
                    r[4] for r in rows[i + 1 : i + 1 + CONTEXT] if r[0] == page_id
                )
                if isinstance(result, Change):
                    changes[(first, last)] = result
                    pages[(first, last)] = page_id
                    rules[result.rule] += 1
                    review.append(
                        {
                            "kind": "change",
                            "document": Path(path).name,
                            "page": str(page_index + 1),
                            "before": before,
                            "original": text,
                            "corrected": result.text,
                            "rule": result.rule,
                            "after": after,
                            "reason": result.reason,
                        }
                    )
                elif result:
                    flag = Flag(
                        first,
                        last,
                        "S1",
                        " | ".join(result),
                        "several lexicon candidates",
                    )
                    flags.append((page_id, flag))
                    review.append(
                        {
                            "kind": "flag",
                            "document": Path(path).name,
                            "page": str(page_index + 1),
                            "before": before,
                            "original": text,
                            "corrected": flag.candidate,
                            "rule": "S1",
                            "after": after,
                            "reason": flag.reason,
                        }
                    )
            check_changes(texts, changes, subs)
            # ... with the substituted tokens updated
            conn.executemany(
                "UPDATE corrected_words SET text = ?, rule = ?, reason = ?"
                " WHERE run_id = ? AND page_id = ? AND first_word_id = ? AND last_word_id = ?",
                [
                    (c.text, c.rule, c.reason, run_id, pages[(a, b)], a, b)
                    for (a, b), c in changes.items()
                ],
            )
            conn.executemany(
                "INSERT INTO correction_flags (run_id, page_id, first_word_id, last_word_id, rule, candidate, reason)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (run_id, p, f.first, f.last, f.rule, f.candidate, f.reason)
                    for p, f in flags
                ],
            )
        conn.commit()
        print(
            f"{path}: substitutions {dict(sorted(rules.items()))}, flags {len(flags)}"
        )
    return run_id, review


def write_review(path: Path, review: list[dict[str, str]]) -> int:
    """Write a random sample of the changes and all flags to a CSV file; return the number of rows."""
    changes = [r for r in review if r["kind"] == "change"]
    sample = random.Random(SEED).sample(changes, min(REVIEW_SAMPLE, len(changes)))
    rows = sample + [r for r in review if r["kind"] == "flag"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            [
                "kind",
                "document",
                "page",
                "before",
                "original",
                "after",
                "corrected",
                "rule",
                "reason",
                "ok",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def configure(parser: argparse.ArgumentParser) -> None:
    """Add the arguments of this command to its parser."""
    parser.add_argument("db", type=Path, help="crlb.sqlite")
    parser.add_argument(
        "table", type=Path, help="substitutions.csv: the substitutions per part"
    )
    parser.add_argument(
        "--based-on",
        type=int,
        help="the correction run to build on; default: the active one",
    )
    parser.add_argument(
        "--min-count",
        type=int,
        default=3,
        help="born-digital count a candidate needs to be accepted",
    )
    parser.add_argument(
        "--review",
        type=Path,
        help="CSV file for the review sample; default: review/ next to the database",
    )
    add_sample_option(parser)
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Run the substitutions and print the new run id."""
    conn = db.connect(args.db)
    based_on = (
        args.based_on
        if args.based_on is not None
        else active_run(conn, CORRECTION_STEP)
    )
    if based_on is None:
        raise SystemExit(
            "no correction run given and none is active (crlb set-active 2 <run>)"
        )
    run_id, review = run_substitution(
        conn, args.table, based_on, args.min_count, sample_parts(args.sample)
    )
    conn.close()
    out = (
        args.review or args.db.parent / "review" / f"substitute_run{run_id}_sample.csv"
    )
    rows = write_review(out, review)
    print(
        f"correction run {run_id} (2b, based on run {based_on}); {rows} rows for review in {out}. Next:\n"
        f"  check it:       crlb correct measure {args.db} <specimens_dir> <split.csv> --run {run_id}\n"
        f"  make it active: crlb set-active {args.db} 2 {run_id}"
    )
