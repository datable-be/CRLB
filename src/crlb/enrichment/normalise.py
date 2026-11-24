"""Normalise the provenance values of step 4 to the control lists and the RKD entry instructions (step 5b).

Reads the active step 4 runs (objects and provenance) and the control terms
of 5a (`crlb lists indexes`, `crlb lists rkd`). For each holder, place,
auction house, consignor, buyer and sale of the sample's objects:

1. the RKD terms and the index terms of the part are scored (see `matching`);
2. an RKD term that is assigned gives the normalised value (the value as RKD
   enters it); else an assigned index term gives it for a person (the index
   prints `Last, First`); else the entry instructions format the value;
3. values with candidates close to the threshold, or two close candidates,
   get the status `review`;
4. values with the same term, or the same normalised form, share a cluster.

One `enrichment_runs` row per run; the step 4 rows are not changed. Prints
only counts; `crlb normalise review` writes the review file.
"""

import argparse
import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from crlb import db
from crlb.enrichment import matching
from crlb.enrichment.indexes import page_numbers
from crlb.enrichment.instructions import format_holder, simplify
from crlb.enrichment.matching import Candidate, Term, Value
from crlb.runs import git_commit, utc_now
from crlb.sample import SampleItem, add_sample_option
from crlb.segmentation.index import is_capitals
from crlb.text import CORRECTION_STEP, active_run

REVIEW_SCORE = (
    0.8  # a best candidate from this score up, not assigned, is sent to review
)


def load_terms(conn: sqlite3.Connection) -> list[Term]:
    """Return the control terms with their pages, works, records and dates."""
    pages: dict[int, set[int]] = {}
    works: dict[int, set[tuple[str, str | None, str | None]]] = {}
    for term_id, printed, number, copy, attribution in conn.execute(
        "SELECT term_id, printed_page, entry_number, copy_text, attribution FROM index_references"
    ):
        if printed:
            pages.setdefault(term_id, set()).update(page_numbers(printed))
        if number:
            works.setdefault(term_id, set()).add((number, copy, attribution))
    terms = []
    for row in conn.execute("SELECT * FROM control_terms ORDER BY id"):
        extra = json.loads(row["extra"] or "{}")
        terms.append(
            Term(
                row["id"],
                row["vocabulary"],
                row["label"],
                tuple(json.loads(row["alt_labels"] or "[]")),
                row["type"],
                extra.get("part"),
                frozenset(extra.get("records", [])),
                frozenset(pages.get(row["id"], set())),
                tuple(sorted(works.get(row["id"], set()), key=str)),
                extra.get("begin"),
                extra.get("end"),
                extra.get("place"),
            )
        )
    return terms


def run_ids(conn: sqlite3.Connection) -> tuple[int, int]:
    """Return the active step 4 objects and provenance runs."""
    objects, provenance = (
        active_run(conn, "4:objects"),
        active_run(conn, "4:provenance"),
    )
    if objects is None or provenance is None:
        raise SystemExit(
            "accept the step 4 objects and provenance runs first (crlb set-active)"
        )
    return objects, provenance


def printed_pages(
    conn: sqlite3.Connection, segmentation_run: int, first: int, last: int
) -> frozenset[int]:
    """Return the printed page numbers of a word range in a segmentation run."""
    return frozenset(
        int(printed)
        for (printed,) in conn.execute(
            "SELECT DISTINCT pp.printed FROM words w JOIN printed_pages pp ON pp.page_id = w.page_id"
            " WHERE pp.run_id = ? AND w.id BETWEEN ? AND ? AND pp.printed IS NOT NULL",
            (segmentation_run, first, last),
        )
        if printed.isdigit()
    )


def load_values(
    conn: sqlite3.Connection, sample: list[SampleItem] | None
) -> list[Value]:
    """Return the provenance values of the active step 4 runs to normalise, restricted to the sample."""
    objects_run, provenance_run = run_ids(conn)
    segmentation_run = conn.execute(
        "SELECT segmentation_run_id FROM ro_runs WHERE id = ?", (provenance_run,)
    ).fetchone()[0]
    rkd = dict(
        conn.execute(
            "SELECT object_id, object_identifier FROM ro_object_identifiers"
            " WHERE run_id = ? AND object_identifier_type_label = 'RKD ID'",
            (objects_run,),
        ).fetchall()
    )
    wanted = None if sample is None else {(s.part, s.number) for s in sample}
    values = []

    def add(
        row: sqlite3.Row,
        table: str,
        column: str,
        text: str | None,
        kind: str,
        current: bool = False,
        place: str | None = None,
        date: str | None = None,
    ) -> None:
        """Add a value of a row, if it has text and its object is in the sample."""
        number, _, copy = row["crlb_number"].partition(", ")
        if not text or (
            wanted is not None
            and (row["part"], number) not in wanted
            and (row["part"], None) not in wanted
        ):
            return
        values.append(
            Value(
                table,
                row["id"],
                column,
                text,
                kind,
                row["part"],
                number,
                copy or None,
                rkd.get(row["object_id"]),
                printed_pages(
                    conn, segmentation_run, row["first_word_id"], row["last_word_id"]
                ),
                current,
                place,
                date,
            )
        )

    for row in conn.execute(
        "SELECT s.*, o.part, o.crlb_number FROM ro_collection_stays s JOIN ro_objects o ON o.id = s.object_id"
        " WHERE s.run_id = ? ORDER BY s.object_id, s.position",
        (provenance_run,),
    ):
        add(row, "ro_collection_stays", "holder_text", row["holder_text"], "holder",
            bool(row["collection_is_current"]), row["collection_place_label"])  # fmt: skip
        add(
            row,
            "ro_collection_stays",
            "collection_place_label",
            row["collection_place_label"],
            "place",
        )
    for row in conn.execute(
        "SELECT a.*, o.part, o.crlb_number FROM ro_auctions a JOIN ro_objects o ON o.id = a.object_id"
        " WHERE a.run_id = ? ORDER BY a.object_id, a.position",
        (provenance_run,),
    ):
        add(
            row,
            "ro_auctions",
            "auction_organizer_label",
            row["auction_organizer_label"],
            "auction house",
        )
        add(
            row,
            "ro_auctions",
            "auction_place_label",
            row["auction_place_label"],
            "place",
        )
        if not row["auction_consignor_derived"]:
            add(
                row,
                "ro_auctions",
                "auction_consignor",
                row["auction_consignor"],
                "holder",
            )
        add(row, "ro_auctions", "auction_buyer", row["auction_buyer"], "holder")
        sale = ", ".join(
            p
            for p in (
                row["auction_organizer_label"],
                row["auction_place_label"],
                row["auction_date_text"],
            )
            if p
        )
        add(
            row,
            "ro_auctions",
            "sale",
            sale,
            "sale",
            place=row["auction_place_label"],
            date=row["auction_date_start"],
        )
    return values


def index_form(term: Term) -> str | None:
    """Return the spelling of an index term to use as a normalised name: not a collection in capitals, without a final bracket ('(dealer)')."""
    if term.type == "collection" or is_capitals(term.label):
        return None
    return re.sub(r"\s*\([^)]*\)$", "", term.label)


def normalised(
    value: Value, rkd: Candidate | None, index: Candidate | None
) -> tuple[str, str]:
    """Return the normalised value and the rule that gave it."""
    if rkd is not None:
        return rkd.term.label, "matched: RKD term"
    if value.kind != "place" and index is not None and index_form(index.term):
        return index_form(
            index.term
        ) or value.text, "matched: corpus index (its spelling)"
    if value.kind == "holder":
        formatted = format_holder(value.text)
        if formatted.rule:
            return formatted.value, f"entry instruction: {formatted.rule}"
    if index is not None:
        return value.text, "matched: corpus index"
    return value.text, "unchanged"


@dataclass
class Decision:
    """The result for one value: its candidates, the terms assigned and its normalised form."""

    value: Value
    found: list[Candidate]
    rkd: Candidate | None
    index: Candidate | None
    text: str
    rule: str
    review: bool


def decide(value: Value, terms: list[Term]) -> Decision:
    """Score the candidates of a value and decide its terms and normalised form."""
    found = matching.candidates(value, terms)
    rkd = matching.decide(
        matching.without_duplicates(
            [c for c in found if c.term.vocabulary != "crlb_index"], value.kind
        )
    )
    index = matching.decide([c for c in found if c.term.vocabulary == "crlb_index"])
    text, rule = normalised(value, rkd, index)
    review = (
        rkd is None and index is None and bool(found) and found[0].score >= REVIEW_SCORE
    )
    return Decision(value, found, rkd, index, text, rule, review)


def keys(decision: Decision) -> list[tuple[str, ...]]:
    """Return what makes two values one cluster: the same assigned term, or the same kind and normalised form (place and date for a sale)."""
    value = decision.value
    result: list[tuple[str, ...]] = [
        ("term", str(c.term.id)) for c in (decision.rkd, decision.index) if c
    ]
    if value.kind == "sale":
        result.append(("sale", simplify(value.place or ""), value.date or value.text))
    elif not decision.review:
        result.append((value.kind, simplify(decision.text)))
    return result


def clusters_of(decisions: list[Decision]) -> list[int]:
    """Return the cluster number of each decision: values sharing a key, directly or through others, are one cluster."""
    parent = list(range(len(decisions)))

    def root(k: int) -> int:
        """Return the representative of a decision's cluster."""
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    first: dict[tuple[str, ...], int] = {}
    for k, decision in enumerate(decisions):
        for key in keys(decision):
            if key in first:
                parent[root(k)] = root(first[key])
            else:
                first[key] = k
    return [root(k) for k in range(len(decisions))]


def cluster_term(members: list[Decision]) -> tuple[Term | None, str]:
    """Return the term and label of a cluster: an RKD term of a member, else an index term, else the first normalised form."""
    rkd = Counter(m.rkd.term for m in members if m.rkd).most_common(1)
    if rkd:
        return rkd[0][0], rkd[0][0].label
    index = next((m.index.term for m in members if m.index), None)
    if index is not None and members[0].value.kind != "place" and index_form(index):
        return index, index_form(index) or members[0].text
    return index, members[0].text


def candidate_json(found: list[Candidate]) -> str:
    """Return the top candidates as JSON for review."""
    return json.dumps(
        [
            {
                "term_id": c.term.id,
                "vocabulary": c.term.vocabulary,
                "label": c.term.label,
                "similarity": round(c.similarity, 2),
                "score": round(c.score, 2),
                "evidence": c.evidence,
            }
            for c in found[:3]
        ],
        ensure_ascii=False,
    )


def normalise(
    conn: sqlite3.Connection, sample: list[SampleItem] | None
) -> tuple[int, Counter[str]]:
    """Run 5b on the sample and store the result; return the run id and counts."""
    terms = load_terms(conn)
    if not terms:
        raise SystemExit(
            "no control terms; run crlb lists indexes and crlb lists rkd first"
        )
    values = load_values(conn, sample)
    objects_run, provenance_run = run_ids(conn)
    segmentation_run = conn.execute(
        "SELECT segmentation_run_id FROM ro_runs WHERE id = ?", (provenance_run,)
    ).fetchone()[0]
    options = {
        "sample": None
        if sample is None
        else [f"{s.part}/{s.number or ''}" for s in sample],
        "threshold": matching.THRESHOLD,
        "margin": matching.MARGIN,
        "review_score": REVIEW_SCORE,
        "control_terms": dict(Counter(t.vocabulary for t in terms)),
    }
    run_id = conn.execute(
        "INSERT INTO enrichment_runs (started_at, part_of_step, method, ro_run_ids, correction_run_id,"
        " segmentation_run_id, version, options) VALUES (?, '5b', 'rules', ?, ?, ?, ?, ?)",
        (
            utc_now(),
            json.dumps([objects_run, provenance_run]),
            active_run(conn, CORRECTION_STEP),
            segmentation_run,
            git_commit(),
            json.dumps(options, ensure_ascii=False),
        ),
    ).lastrowid
    assert run_id is not None
    counts: Counter[str] = Counter()
    decisions = [decide(value, terms) for value in values]
    numbers = clusters_of(decisions)
    cluster_ids: dict[int, int] = {}
    for number in dict.fromkeys(numbers):
        members = [d for d, n in zip(decisions, numbers, strict=True) if n == number]
        term, label = cluster_term(members)
        cluster_id = conn.execute(
            "INSERT INTO clusters (run_id, type, label, term_id) VALUES (?, ?, ?, ?)",
            (run_id, members[0].value.kind, label, term.id if term else None),
        ).lastrowid
        assert cluster_id is not None
        cluster_ids[number] = cluster_id
        for member in members:
            # A cluster with an RKD term is normalised once: every name in it gets the RKD name
            if (
                term is not None
                and term.vocabulary != "crlb_index"
                and member.rkd is None
            ):
                member.text, member.rule = (
                    label,
                    "cluster: the RKD term of the same holder",
                )
    for decision, number in zip(decisions, numbers, strict=True):
        value, found = decision.value, decision.found
        conn.execute(
            "INSERT INTO normalised_values (run_id, table_name, row_id, column_name, value_text, normalised_value,"
            " cluster_id, rule, score, candidates, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                value.table,
                value.row_id,
                value.column,
                value.text,
                decision.text,
                cluster_ids[number],
                "review: candidates close to the threshold or to each other"
                if decision.review
                else decision.rule,
                round(found[0].score, 3) if found else None,
                candidate_json(found),
                "review" if decision.review else "unreviewed",
            ),
        )
        counts[f"{value.kind}: values"] += 1
        counts[f"{value.kind}: RKD term assigned"] += decision.rkd is not None
        counts[f"{value.kind}: index term assigned"] += (
            decision.rkd is None and decision.index is not None
        )
        counts[f"{value.kind}: RKD term through its cluster"] += (
            decision.rule.startswith("cluster")
        )
        counts[f"{value.kind}: sent to review"] += decision.review
        counts[f"{value.kind}: formatted by an entry instruction"] += (
            decision.rule.startswith("entry instruction") and not decision.review
        )
        counts[f"{value.kind}: without candidates"] += not found
    counts["clusters"] = len(cluster_ids)
    counts["clusters with more than one value"] = conn.execute(
        "SELECT COUNT(*) FROM (SELECT cluster_id FROM normalised_values WHERE run_id = ?"
        " GROUP BY cluster_id HAVING COUNT(*) > 1)",
        (run_id,),
    ).fetchone()[0]
    conn.commit()
    return run_id, counts


def configure(parser: argparse.ArgumentParser) -> None:
    """Add the arguments of this command to its parser."""
    parser.add_argument("db", type=Path, help="crlb.sqlite")
    add_sample_option(parser)
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Run the normalisation and print the counts."""
    conn = db.connect(args.db)
    run_id, counts = normalise(conn, args.sample)
    conn.close()
    print(f"normalisation run {run_id}")
    for name, value in sorted(counts.items()):
        print(f"  {name}: {value}")
