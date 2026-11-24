"""Matching a step 4 value to the terms of the control lists: candidates, evidence and the decision (step 5b).

A candidate's score is its name similarity (rapidfuzz, on simplified forms,
also with `First Last` turned into `Last, First`) plus the evidence from the
context:

- the corpus index of the part refers to a printed page of the value;
- the RKD record of the same work uses the RKD term;
- for a current location, the collections index lists the object (its
  catalogue number, and for a copy its copy number or an 'after Rubens'
  attribution) under the collection;
- for a sale, the RKD auction's dates contain the date of the sale.

A term is assigned only when one candidate reaches the threshold and no
other comes within the margin; otherwise the candidates are kept for review.
"""

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from crlb.enrichment.instructions import is_person, last_first, simplify

MIN_SIMILARITY = 0.7  # below this a term is no candidate
THRESHOLD = 0.95  # score needed to assign a term
MARGIN = 0.1  # the next candidate must score at least this much less
PAGE_EVIDENCE = 0.1
RECORD_EVIDENCE = 0.1
COLLECTION_EVIDENCE = 0.15
PLACE_EVIDENCE = 0.15
DATE_SIMILARITY = 0.85  # a sale on a date of an RKD auction

# Index types that can name a holder, a place or an auction house
TYPES = {
    "holder": {"person", "collection", "dealer", "auctioneer", None},
    "place": {"place", None},
    "auction house": {"auctioneer", "dealer", "collection", None},
    "sale": set(),
}
# RKD vocabularies that can name a holder, an auction house or a sale
RKD_VOCABULARIES = {
    "holder": {"rkd_collections", "rkd_actors"},
    "place": set(),
    "auction house": {"rkd_actors", "rkd_collections"},
    "sale": {"rkd_auctions"},
}


@dataclass(frozen=True)
class Term:
    """A control-list term with what matching needs of it."""

    id: int
    vocabulary: str
    label: str
    alt_labels: tuple[str, ...]
    type: str | None
    part: str | None = None  # index terms: the part of the index
    records: frozenset[str] = frozenset()  # RKD terms: the RKD records that use it
    pages: frozenset[int] = frozenset()  # index terms: the printed pages it refers to
    # collections index: (catalogue number, copy as printed, attribution) of the works listed
    works: tuple[tuple[str, str | None, str | None], ...] = ()
    begin: str | None = None  # RKD auctions
    end: str | None = None
    place: str | None = None


@dataclass(frozen=True)
class Value:
    """A step 4 value to normalise, with its context."""

    table: str
    row_id: int
    column: str
    text: str
    kind: str  # holder, place, auction house, sale
    part: str
    number: str  # catalogue number of the object ('4', '12c')
    copy: str | None  # 'Copy 2' for a copy
    rkd_id: str | None  # of the object
    pages: frozenset[int]  # printed pages of the value's words
    current: bool = False
    place: str | None = None  # the place given with a holder or a sale
    date: str | None = None  # of a sale, YYYY[-MM[-DD]]


@dataclass
class Candidate:
    """A term considered for a value, with its score and the evidence for it."""

    term: Term
    similarity: float
    score: float
    evidence: list[str] = field(default_factory=list)


def value_forms(value: Value) -> set[str]:
    """Return the simplified forms of a value to compare: as written, as 'Last, First', and with its place."""
    forms = {simplify(value.text)}
    if is_person(value.text):
        forms.add(simplify(last_first(value.text)))
    if value.place:
        forms.add(simplify(f"{value.place} {value.text}"))
    return {f for f in forms if f}


def term_forms(term: Term) -> set[str]:
    """Return the simplified forms of a term: its labels, without and within brackets, and without a place before the comma."""
    forms = set()
    for label in (term.label, *term.alt_labels):
        forms.add(label)
        forms.add(re.sub(r"\s*\([^)]*\)", "", label))
        forms |= {
            re.sub(r"^(?:probably|possibly)\s+", "", inner, flags=re.IGNORECASE)
            for inner in re.findall(r"\(([^)]*)\)", label)
        }
        if term.type == "collection" and "," in label:
            forms.add(label.split(",", 1)[1])
    return {simplify(f) for f in forms if simplify(f)}


def similarity(value: Value, term: Term) -> float:
    """Return the best name similarity of a value and a term, between 0 and 1."""
    return max(
        (
            fuzz.token_sort_ratio(a, b) / 100
            for a in value_forms(value)
            for b in term_forms(term)
        ),
        default=0.0,
    )


def lists_object(term: Term, value: Value) -> bool:
    """Return whether the collections index lists the value's object under a term."""
    for number, copy, attribution in term.works:
        if number != value.number:
            continue
        if (
            value.copy is None
            and copy is None
            and not re.search(r"\bafter\b", attribution or "")
        ):
            return True
        if value.copy is not None and (
            copy == value.copy
            or (copy is None and re.search(r"\bafter\b", attribution or ""))
        ):
            return True
    return False


def sale_candidate(value: Value, term: Term) -> Candidate | None:
    """Return an RKD auction as a candidate for a sale if its dates contain the sale's date."""
    if not (value.date and term.begin and term.end):
        return None
    if not (term.begin[: len(value.date)] <= value.date <= term.end[: len(value.date)]):
        return None
    candidate = Candidate(
        term,
        DATE_SIMILARITY,
        DATE_SIMILARITY,
        ["the RKD auction's dates contain the date"],
    )
    if value.place and term.place and simplify(value.place) in simplify(term.place):
        candidate.score += PLACE_EVIDENCE
        candidate.evidence.append("same place")
    return candidate


def candidates(value: Value, terms: list[Term]) -> list[Candidate]:
    """Return the candidate terms of a value, best first."""
    result = []
    for term in terms:
        if term.vocabulary == "crlb_index":
            if term.part != value.part or term.type not in TYPES[value.kind]:
                continue
        elif term.vocabulary not in RKD_VOCABULARIES[value.kind]:
            continue
        if value.kind == "sale":
            found = sale_candidate(value, term)
            if found:
                result.append(found)
            continue
        sim = similarity(value, term)
        if sim < MIN_SIMILARITY:
            continue
        candidate = Candidate(term, sim, sim)
        if term.pages & value.pages:
            candidate.score += PAGE_EVIDENCE
            candidate.evidence.append("the index refers to the page")
        if value.rkd_id and value.rkd_id in term.records:
            candidate.score += RECORD_EVIDENCE
            candidate.evidence.append("used by the RKD record of the work")
        if value.current and lists_object(term, value):
            candidate.score += COLLECTION_EVIDENCE
            candidate.evidence.append("the collections index lists the work here")
        result.append(candidate)
    return sorted(result, key=lambda c: (-c.score, c.term.id))


# The RKD list that names a holder or an auction house when both lists have the same name
PREFERRED = {"holder": "rkd_collections", "auction house": "rkd_actors"}


def without_duplicates(found: list[Candidate], kind: str) -> list[Candidate]:
    """Drop an RKD candidate whose name another RKD list also has, keeping the list preferred for the kind."""
    preferred = PREFERRED.get(kind)
    names = {simplify(c.term.label) for c in found if c.term.vocabulary == preferred}
    return [
        c
        for c in found
        if c.term.vocabulary == preferred
        or c.term.vocabulary == "crlb_index"
        or simplify(c.term.label) not in names
    ]


def decide(found: list[Candidate]) -> Candidate | None:
    """Return the candidate to assign: above the threshold, with no other within the margin."""
    if not found or found[0].score < THRESHOLD:
        return None
    if len(found) > 1 and found[0].score - found[1].score < MARGIN:
        return None
    return found[0]
