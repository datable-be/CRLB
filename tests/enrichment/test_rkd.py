"""Tests for reading RKD records and terms (step 5a), without the network."""

from crlb.enrichment import rkd

CRM = rkd.CRM
REC = "https://data.rkd.nl/images/58171"
COLLECTOR = "https://data.rkd.nl/collectors/20862"
NAME = "https://data.rkd.nl/.well-known/genid/a1"


def fake_endpoint(triples: list[rkd.Triple]):
    """Return a query function that answers the subjects of a VALUES query from a list of triples."""

    def query(text: str) -> list[dict[str, dict[str, str]]]:
        """Answer a query with the triples of its subjects."""
        subjects = {t[0] for t in triples if f"<{t[0]}>" in text}
        return [
            {"s": {"value": s}, "p": {"value": p}, "o": {"value": o, "type": kind}}
            for s, p, o, kind in triples
            if s in subjects
        ]

    return query


def test_a_record_graph_follows_its_own_nodes_but_not_other_terms() -> None:
    """The transfer inside the record is followed; the collector it points to is not part of the record."""
    triples = [
        (
            REC,
            f"{CRM}P30i_custody_transferred_through",
            f"{REC}/provenance/transfer/1",
            "uri",
        ),
        (
            f"{REC}/provenance/transfer/1",
            f"{CRM}P29_custody_received_by",
            COLLECTOR,
            "uri",
        ),
        (COLLECTOR, rkd.RDFS_LABEL, "Moretus, Balthasar", "literal"),
    ]
    found = rkd.record_graph("58171", fake_endpoint(triples))
    assert {t[0] for t in found} == {REC, f"{REC}/provenance/transfer/1"}
    assert rkd.vocabulary(COLLECTOR) == "rkd_collections"
    assert rkd.vocabulary(NAME) is None


def test_a_term_is_described_by_its_preferred_and_other_names() -> None:
    """The preferred name is the label unless there is an rdfs:label; identifiers are no names."""
    triples = [
        (COLLECTOR, f"{CRM}P1_is_identified_by", NAME, "uri"),
        (NAME, f"{CRM}P190_has_symbolic_content", "Gasser, Hanns", "literal"),
        (NAME, f"{CRM}P2_has_type", rkd.PREFERRED_NAME, "uri"),
        (COLLECTOR, f"{CRM}P1_is_identified_by", NAME + "b", "uri"),
        (NAME + "b", f"{CRM}P190_has_symbolic_content", "Gasser, Hans", "literal"),
        (COLLECTOR, f"{CRM}P1_is_identified_by", NAME + "c", "uri"),
        (NAME + "c", f"{CRM}P190_has_symbolic_content", "10107", "literal"),
        (NAME + "c", f"{CRM}P2_has_type", rkd.IDENTIFIER, "uri"),
    ]
    info = rkd.describe(COLLECTOR, triples)
    assert (info.label, info.alt_labels) == ("Gasser, Hanns", ["Gasser, Hans"])
