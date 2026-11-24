"""Tests for the normalised values and clusters of step 5b."""

from dataclasses import replace

from crlb.enrichment import normalise
from crlb.enrichment.matching import Term, Value

GASSER = Term(
    1,
    "rkd_collections",
    "Gasser, Hanns",
    ("Gasser, Hans",),
    "E39_Actor",
    records=frozenset({"58171"}),
)
INDEX = Term(
    2,
    "crlb_index",
    "Gasser (probably Gasser, Hans)",
    (),
    "person",
    "XIX (4)",
    pages=frozenset({61}),
)
HOLDER = Value(
    "ro_collection_stays", 1, "holder_text", "Hans Gasser", "holder",
    "XIX (4)", "4", None, "58171", frozenset({61}),
)  # fmt: skip


def test_values_sharing_a_term_are_one_cluster_with_the_rkd_name() -> None:
    """'Hans Gasser' gets the RKD and the index term; the buyer 'Gasser' only the index term, and joins its cluster."""
    buyer = replace(
        HOLDER, table="ro_auctions", row_id=2, column="auction_buyer", text="Gasser"
    )
    other = replace(HOLDER, row_id=3, text="Albert Fonson")
    decisions = [normalise.decide(v, [GASSER, INDEX]) for v in (HOLDER, buyer, other)]
    assert decisions[0].rkd is not None and decisions[0].index is not None
    assert decisions[1].rkd is None and decisions[1].index is not None
    numbers = normalise.clusters_of(decisions)
    assert numbers[0] == numbers[1] != numbers[2]
    term, label = normalise.cluster_term(decisions[:2])
    assert term == GASSER and label == "Gasser, Hanns"


def test_an_index_term_gives_its_spelling_and_a_collection_in_capitals_does_not() -> (
    None
):
    """A person of the index is normalised to the index's form; a collection keeps the value."""
    vinck = Term(
        3, "crlb_index", "Vinck du Bois", (), None, "XIX (4)", pages=frozenset({61})
    )
    decision = normalise.decide(replace(HOLDER, text="Vinck du Bois"), [vinck])
    assert (decision.text, decision.rule) == (
        "Vinck du Bois",
        "matched: corpus index (its spelling)",
    )
    met = Term(4, "crlb_index", "NEW YORK, THE METROPOLITAN MUSEUM OF ART", (), "collection", "XIX (4)",
               pages=frozenset({61}))  # fmt: skip
    decision = normalise.decide(
        replace(HOLDER, text="The Metropolitan Museum of Art"), [met]
    )
    assert (
        decision.index is not None and decision.text == "The Metropolitan Museum of Art"
    )
