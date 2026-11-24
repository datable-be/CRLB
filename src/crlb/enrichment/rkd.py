"""Fetch the RKDimages records of the CRLB works and the RKD terms they use (step 5a).

The source is the RKD Knowledge Graph (CIDOC-CRM, public, SPARQL on TriplyDB).
For each RKD ID of the sample's objects (from the RKD links, `ro_object_identifiers`):

1. the record: its own nodes (provenance transfers and activities, and the
   `genid` nodes inside them), level by level, stored as triples in
   `rkd_records`;
2. the RKD terms the record points to (collectors, artists, auctions, places
   in the thesaurus) and, for auctions, the actors in them (auction house,
   seller): their names and, for an auction, its date and place, stored as
   `control_terms`.

Only RKD URIs are sent, never text from the PDFs. Records already fetched
are skipped unless --refresh is given. Prints only counts.
"""

import argparse
import json
import sqlite3
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from crlb import db
from crlb.runs import utc_now
from crlb.sample import SampleItem, add_sample_option
from crlb.text import active_run

ENDPOINT = (
    "https://rkd.triply.cc/_api/datasets/rkd/RKD-Knowledge-Graph/services/SPARQL/sparql"
)
SOURCE = "RKD Knowledge Graph (SPARQL)"
RKD = "https://data.rkd.nl/"
GENID = "/.well-known/genid/"
BATCH = 100
PAUSE = 0.5  # seconds between queries

CRM = "http://www.cidoc-crm.org/cidoc-crm/"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
PREFERRED_NAME = "http://vocab.getty.edu/aat/300404670"
IDENTIFIER = "http://vocab.getty.edu/aat/300444185"
# Predicates of an RKD term that lead to large parts of the graph, not to its own description
SKIPPED = (
    f"{CRM}P67i_is_referred_to_by",
    f"{CRM}P14i_performed",
    f"{CRM}P129i_is_subject_of",
)
# RKD path -> vocabulary of control_terms
VOCABULARIES = {
    "collectors": "rkd_collections",
    "artists": "rkdartists",
    "auctions": "rkd_auctions",
    "actors": "rkd_actors",
    "thesaurus": "rkd_thesaurus",
}

Triple = tuple[
    str, str, str, str
]  # subject, predicate, object, object type ('uri' or 'literal')


@dataclass(frozen=True)
class Description:
    """The label, variant names, CIDOC-CRM class and details (date, place, roles) of an RKD term."""

    label: str
    alt_labels: list[str]
    type: str | None
    detail: dict[str, object]


def sparql(query: str) -> list[dict[str, dict[str, str]]]:
    """Run a SPARQL SELECT query on the RKD endpoint and return its bindings."""
    request = urllib.request.Request(
        ENDPOINT,
        data=urllib.parse.urlencode({"query": query}).encode(),
        headers={"Accept": "application/sparql-results+json", "User-Agent": "crlb"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)["results"]["bindings"]


def triples_of(
    subjects: list[str], query: Callable[[str], list] = sparql
) -> list[Triple]:
    """Return the triples of some subjects, without the skipped predicates."""
    values = " ".join(f"<{s}>" for s in subjects)
    skipped = ", ".join(f"<{p}>" for p in SKIPPED)
    rows = query(
        f"SELECT ?s ?p ?o WHERE {{ VALUES ?s {{ {values} }} ?s ?p ?o FILTER(?p NOT IN ({skipped})) }}"
    )
    time.sleep(PAUSE)
    return [
        (r["s"]["value"], r["p"]["value"], r["o"]["value"], r["o"]["type"])
        for r in rows
    ]


def graph(
    roots: Iterable[str],
    inner: Callable[[str], bool],
    depth: int,
    query: Callable[[str], list] = sparql,
) -> list[Triple]:
    """Return the triples of the roots and of the inner nodes reachable from them, up to a depth."""
    result: list[Triple] = []
    seen: set[str] = set()
    level = list(dict.fromkeys(roots))
    for _ in range(depth + 1):
        level = [s for s in level if s not in seen]
        if not level:
            break
        seen |= set(level)
        found: list[Triple] = []
        for k in range(0, len(level), BATCH):
            found += triples_of(level[k : k + BATCH], query)
        result += found
        level = [o for _, _, o, kind in found if kind == "uri" and inner(o)]
    return result


def record_uri(rkd_id: str) -> str:
    """Return the URI of an RKDimages record."""
    return f"{RKD}images/{rkd_id}"


def vocabulary(uri: str) -> str | None:
    """Return the control-list vocabulary of an RKD term URI, or None if it is no term."""
    if not uri.startswith(RKD) or GENID in uri:
        return None
    return VOCABULARIES.get(uri[len(RKD) :].split("/")[0])


def record_graph(rkd_id: str, query: Callable[[str], list] = sparql) -> list[Triple]:
    """Return the triples of a record and of its own nodes."""
    root = record_uri(rkd_id)
    return graph(
        [root], lambda u: u.startswith(root + "/") or GENID in u, depth=8, query=query
    )


def describe(uri: str, triples: list[Triple]) -> Description:
    """Return the label, variant names, type and details of an RKD term from its triples and those of its name, place and time nodes."""
    by_subject: dict[str, list[Triple]] = defaultdict(list)
    for t in triples:
        by_subject[t[0]].append(t)

    def values(subject: str, predicate: str) -> list[str]:
        """Return the objects of a subject and predicate."""
        return [o for _, p, o, _ in by_subject[subject] if p == predicate]

    names, preferred = [], []
    for node in values(uri, f"{CRM}P1_is_identified_by"):
        types = values(node, f"{CRM}P2_has_type")
        for name in values(node, f"{CRM}P190_has_symbolic_content"):
            if IDENTIFIER in types:
                continue
            (preferred if PREFERRED_NAME in types else names).append(name)
    labels = values(uri, RDFS_LABEL)
    label = (labels or preferred or names or [uri])[0]
    detail: dict[str, object] = {}
    for span in values(uri, f"{CRM}P4_has_time-span"):
        detail["begin"] = next(
            iter(values(span, f"{CRM}P82a_begin_of_the_begin")), None
        )
        detail["end"] = next(iter(values(span, f"{CRM}P82b_end_of_the_end")), None)
    for place in values(uri, f"{CRM}P7_took_place_at"):
        detail["place"] = next(iter(values(place, RDFS_LABEL)), None)
    roles = [
        [
            next(iter(values(node, f"{CRM}P02_has_range")), None),
            next(iter(values(node, f"{CRM}P14.1_in_the_role_of")), None),
        ]
        for node in values(uri, f"{CRM}P01i_is_domain_of")
    ]
    if roles:
        detail["roles"] = roles
    kinds = [t.rsplit("/", 1)[-1] for t in values(uri, RDF_TYPE)]
    return Description(
        label,
        sorted(set(preferred + names) - {label}),
        kinds[0] if kinds else None,
        detail,
    )


def rkd_ids(conn: sqlite3.Connection, sample: list[SampleItem] | None) -> list[str]:
    """Return the RKD IDs of the objects of the active step 4 objects run, restricted to the sample."""
    run_id = active_run(conn, "4:objects")
    if run_id is None:
        raise SystemExit(
            "no active step 4 objects run (crlb set-active <db> 4:objects <run>)"
        )
    rows = conn.execute(
        "SELECT o.part, o.crlb_number, i.object_identifier FROM ro_object_identifiers i"
        " JOIN ro_objects o ON o.id = i.object_id"
        " WHERE i.run_id = ? AND i.object_identifier_type_label = 'RKD ID'",
        (run_id,),
    ).fetchall()
    wanted = None if sample is None else {(s.part, s.number) for s in sample}
    return sorted(
        {
            rkd_id
            for part, number, rkd_id in rows
            if wanted is None
            or (part, number.split(",")[0]) in wanted
            or (part, None) in wanted
        }
    )


def store_term(
    conn: sqlite3.Connection,
    uri: str,
    info: Description,
    records: list[str],
    now: str,
) -> None:
    """Insert or replace one RKD term."""
    extra = {"records": records} | {k: v for k, v in info.detail.items() if v}
    conn.execute(
        "INSERT INTO control_terms (vocabulary, uri, label, alt_labels, type, extra, source, retrieved_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT (vocabulary, uri) WHERE uri IS NOT NULL DO UPDATE SET label = excluded.label,"
        " alt_labels = excluded.alt_labels, type = excluded.type, extra = excluded.extra,"
        " source = excluded.source, retrieved_at = excluded.retrieved_at",
        (
            vocabulary(uri),
            uri,
            info.label,
            json.dumps(info.alt_labels, ensure_ascii=False),
            info.type,
            json.dumps(extra, ensure_ascii=False),
            SOURCE,
            now,
        ),
    )


def fetch(
    conn: sqlite3.Connection,
    ids: list[str],
    refresh: bool,
    query: Callable[[str], list] = sparql,
) -> Counter[str]:
    """Fetch and store the records and the terms they use; return counts."""
    counts: Counter[str] = Counter()
    have = {row[0] for row in conn.execute("SELECT rkd_id FROM rkd_records")}
    now = utc_now()
    for rkd_id in ids:
        if rkd_id in have and not refresh:
            counts["records already fetched"] += 1
            continue
        triples = record_graph(rkd_id, query)
        if not triples:
            counts["records not found"] += 1
            continue
        conn.execute(
            "INSERT OR REPLACE INTO rkd_records (rkd_id, data, source, retrieved_at) VALUES (?, ?, ?, ?)",
            (rkd_id, json.dumps(triples, ensure_ascii=False), SOURCE, now),
        )
        counts["records fetched"] += 1
        counts["record triples"] += len(triples)
    conn.commit()
    # The terms of all stored records of the sample, with the records using each
    users: dict[str, set[str]] = defaultdict(set)
    for rkd_id in ids:
        row = conn.execute(
            "SELECT data FROM rkd_records WHERE rkd_id = ?", (rkd_id,)
        ).fetchone()
        for _, _, o, kind in json.loads(row[0]) if row else []:
            if kind == "uri" and vocabulary(o):
                users[o].add(rkd_id)
    terms = graph(users, lambda u: GENID in u, depth=2, query=query)
    # The actors of the auctions (auction house, seller), used through those auctions
    for s, _, o, kind in terms:
        if kind == "uri" and vocabulary(o) == "rkd_actors" and vocabulary(s) is None:
            auction = next(a for a, _, node, _ in terms if node == s)
            users[o] |= users.get(auction, set())
    terms += graph(
        [u for u in users if vocabulary(u) == "rkd_actors"],
        lambda u: GENID in u,
        depth=1,
        query=query,
    )
    for uri, records in users.items():
        info = describe(uri, terms)
        store_term(conn, uri, info, sorted(records), now)
        counts[f"terms: {vocabulary(uri)}"] += 1
    conn.commit()
    return counts


def configure(parser: argparse.ArgumentParser) -> None:
    """Add the arguments of this command to its parser."""
    parser.add_argument("db", type=Path, help="crlb.sqlite")
    add_sample_option(parser)
    parser.add_argument(
        "--refresh", action="store_true", help="fetch records already stored again"
    )
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Fetch the RKD data of the sample and print the counts."""
    conn = db.connect(args.db)
    ids = rkd_ids(conn, args.sample)
    print(f"RKD IDs: {len(ids)}")
    for name, value in sorted(fetch(conn, ids, args.refresh).items()):
        print(f"  {name}: {value}")
    conn.close()
