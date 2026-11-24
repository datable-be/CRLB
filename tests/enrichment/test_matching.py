"""Tests for matching step 4 values to control terms (step 5b)."""

from dataclasses import replace

from crlb.enrichment import matching
from crlb.enrichment.matching import Term, Value

HOLDER = Value(
    "ro_collection_stays", 1, "holder_text", "Cornelia Verdussen", "holder",
    "XIX (4)", "4", None, "58171", frozenset({61}),
)  # fmt: skip


def index_term(
    term_id: int, label: str, kind: str | None = "person", **fields: object
) -> Term:
    """Return a corpus index term of XIX (4)."""
    return replace(Term(term_id, "crlb_index", label, (), kind, "XIX (4)"), **fields)


def test_first_last_matches_last_first_and_a_page_reference_adds_evidence() -> None:
    """'Cornelia Verdussen' is the index's 'Verdussen, Cornelia'; the reference to its page decides it."""
    found = matching.candidates(
        HOLDER, [index_term(1, "Verdussen, Cornelia", pages=frozenset({61}))]
    )
    assert found[0].similarity == 1.0
    assert found[0].evidence == ["the index refers to the page"]
    assert matching.decide(found) is found[0]


def test_two_close_candidates_are_not_assigned() -> None:
    """Two index entries for the same name: no decision, the value goes to review."""
    terms = [
        index_term(1, "Clerk, John, Lord Eldin", pages=frozenset({61})),
        index_term(2, "Eldin, John Clerk, Lord", pages=frozenset({61})),
    ]
    value = replace(HOLDER, text="John Clerk, Lord Eldin")
    assert matching.decide(matching.candidates(value, terms)) is None


def test_a_name_without_evidence_below_the_threshold_is_not_assigned() -> None:
    """A similar name alone ('Corneille' for 'Cornelia') is a candidate, not a decision."""
    found = matching.candidates(HOLDER, [index_term(1, "Verdussen, Corneille")])
    assert found and matching.decide(found) is None


def test_the_collections_index_confirms_the_current_location_of_a_copy() -> None:
    """A collection listing the object's copy is evidence for its current location; another copy is not."""
    louvre = index_term(
        1, "PARIS, MUSÉE DU LOUVRE", "collection",
        works=(("4", "Copy 1", "After Rubens, drawing"),),
    )  # fmt: skip
    value = replace(
        HOLDER, text="Musée du Louvre", copy="Copy 1", current=True, place="Paris"
    )
    assert (
        "the collections index lists the work here"
        in matching.candidates(value, [louvre])[0].evidence
    )
    other = replace(value, copy="Copy 2")
    assert matching.candidates(other, [louvre])[0].evidence == []


def test_an_rkd_term_of_the_record_of_the_work_is_evidence() -> None:
    """An RKD collector used by the record of the same work scores higher; the index of another part is ignored."""
    rkd = Term(
        2,
        "rkd_collections",
        "Gasser, Hanns",
        ("Gasser, Hans",),
        "E39_Actor",
        records=frozenset({"58171"}),
    )
    elsewhere = replace(index_term(3, "Gasser, Hans"), part="II (1)")
    found = matching.candidates(replace(HOLDER, text="Hans Gasser"), [rkd, elsewhere])
    assert [c.term.id for c in found] == [2]
    assert found[0].evidence == ["used by the RKD record of the work"]


def test_a_sale_matches_an_rkd_auction_by_date_and_place() -> None:
    """The auction's dates contain the sale's date; the same place decides it."""
    auction = Term(4, "rkd_auctions", "La belle et riche collection", (), "E7_Activity",
                   begin="1821-09-05", end="1821-09-05", place="[Abbaye de Magaendale]; Oudenaarde")  # fmt: skip
    sale = replace(HOLDER, column="sale", text="Oudenaarde, 5 September 1821", kind="sale",
                   place="Oudenaarde", date="1821-09-05")  # fmt: skip
    assert matching.decide(matching.candidates(sale, [auction])) is not None
    elsewhere = replace(sale, place="Ghent")
    assert matching.decide(matching.candidates(elsewhere, [auction])) is None


def test_the_same_name_in_two_rkd_lists_keeps_the_list_of_the_kind() -> None:
    """A holder named in both the collections and the actors list is the collections term."""
    terms = [
        Term(5, "rkd_actors", "Oppenheimer, Henry", (), "E39_Actor"),
        Term(6, "rkd_collections", "Oppenheimer, Henry", (), "E39_Actor"),
    ]
    found = matching.candidates(replace(HOLDER, text="Henry Oppenheimer"), terms)
    assert matching.decide(found) is None
    assert [c.term.id for c in matching.without_duplicates(found, "holder")] == [6]
