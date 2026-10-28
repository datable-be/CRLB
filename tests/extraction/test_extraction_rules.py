"""Tests for the step 4 rules: dates, the object core, references and provenance."""

import pytest

from crlb.extraction import dates, objects, provenance, references, vocabularies
from crlb.extraction.objects import Location
from crlb.extraction.source import Node


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("c. 1598–1600", "1598", "1600"),
        ("1925-26", "1925", "1926"),
        ("1829–42", "1829", "1842"),
        ("26 May 1777", "1777-05-26", "1777-05-26"),
        ("20–21 July 2011", "2011-07-20", "2011-07-21"),
        ("15ff. June 1874", "1874-06-15", None),
        ("10 July 1936 et seqq.", "1936-07-10", None),
        ("December 1856", "1856-12", "1856-12"),
        ("in 1796 ?", "1796", "1796"),
        ("between 17 March 1613 and 2 May 1616", "1613-03-17", "1616-05-02"),
        ("(1612 - 23 October 1652)", "1612", "1652-10-23"),
        ("until 1931", None, "1931"),
    ],
)
def test_dates(text: str, start: str | None, end: str | None) -> None:
    """Verbatim dates give the right ISO start and end."""
    assert dates.parse_date(text) == dates.DateRange(start, end)


def test_text_without_a_date() -> None:
    """A text without a plausible year has no date."""
    assert dates.parse_date("lot 37") is None
    assert dates.parse_date("no. 1032") is None


@pytest.mark.parametrize(
    ("text", "height", "width", "unit", "note"),
    [
        ("Oil on panel; 69.9 × 52.1 cm.", 69.9, 52.1, "cm", None),
        ("Oil on panel; 63 : 89 cm.", 63.0, 89.0, "cm", None),
        ("Oil on panel; c. 68.5 × 52.5 cm. Inscribed", 68.5, 52.5, "cm", "c."),
        ("panel, 66,5 × 51 cm", 66.5, 51.0, "cm", None),
        ("panel, 66.2 cm × 51.1 cm.", 66.2, 51.1, "cm", None),
        (
            "Wool and silk; approximately 370 : 320 cm.",
            370.0,
            320.0,
            "cm",
            "approximately",
        ),
        ("pen and brown ink, 204 × 150 mm.", 204.0, 150.0, "mm", None),
    ],
)
def test_dimensions(
    text: str, height: float, width: float, unit: str, note: str | None
) -> None:
    """Dimensions in the different notations give height, width, unit and note."""
    found = objects.parse_dimensions(text)
    assert found is not None
    assert (found.height, found.width, found.unit, found.note) == (
        height,
        width,
        unit,
        note,
    )


def test_material() -> None:
    """The material note stops before the dimensions; the support comes from the mapping table."""
    material = objects.parse_material("Oil on panel; 69.9 × 52.1 cm.")
    assert (material.note, material.support_label) == ("Oil on panel", "paneel (hout)")
    unknown = objects.parse_material("Support and measurements unknown.")
    assert (unknown.note, unknown.dimensions) == (
        "Support and measurements unknown",
        None,
    )


@pytest.mark.parametrize(
    ("text", "title", "name"),
    [
        (
            "No. 4. Study of two Heads (Plato?): Painting (Fig. 12)",
            "Study of two Heads (Plato?)",
            "Painting",
        ),
        (
            "12c. THE TRIUMPH OF FAITH: MODELLO (FigS. 163, 164)",
            "THE TRIUMPH OF FAITH",
            "MODELLO",
        ),
        (
            "lb . THE MONSTRANCE HELD BY TWO CHERUBS: MODELLO",
            "THE MONSTRANCE HELD BY TWO CHERUBS",
            "MODELLO",
        ),
        (
            "THE FOUR EVANGELISTS: TAPESTRY (Fig. 183)",
            "THE FOUR EVANGELISTS",
            "TAPESTRY",
        ),
        (
            "15b. THE DEFENDERS OF THE EUCHARIST (Fig. 192)",
            "THE DEFENDERS OF THE EUCHARIST",
            None,
        ),
    ],
)
def test_heading(text: str, title: str, name: str | None) -> None:
    """The heading gives the title and the verbatim object name, without number and figures."""
    heading = objects.parse_heading(text)
    assert (heading.title, heading.object_name_text) == (title, name)


def test_heading_cross_reference() -> None:
    """A heading that refers to another entry is a cross-reference, not a title."""
    heading = objects.parse_heading("2a. See above, No. 1-5a.")
    assert heading.title is None
    assert heading.cross_reference == "See above, No. 1-5a."


def test_object_names() -> None:
    """Object names map to the RO list, approximately for OCR damage."""
    assert objects.object_name_label("BOZZETTO") == ("olieverfschets", False)
    assert objects.object_name_label("TAPBSTRY") == ("wandtapijt", True)
    assert objects.object_name_label("Sculpture") == (None, False)


def test_location() -> None:
    """A location gives place, holder, inventory number and collection type."""
    location = objects.parse_location(
        "New York, The Metropolitan Museum of Art. Inv. no. 67.87.99"
    )
    assert (location.place, location.holder, location.identifier) == (
        "New York",
        "The Metropolitan Museum of Art",
        "67.87.99",
    )
    assert location.collection_type == "museum (instelling)"
    private = objects.parse_location("private collection, New York")
    assert (private.place, private.holder) == ("New York", "private collection")


def test_lost_location() -> None:
    """'Whereabouts unknown; presumably lost' is a location with a destruction cause, also with OCR damage."""
    location = objects.parse_location("Whereabouts unknown; presumably loSt.")
    assert location.holder == "Whereabouts unknown"
    assert (location.destruction_text, location.destruction_cause) == (
        "presumably loSt",
        "vermist",
    )


def test_copy() -> None:
    """A copy gives its object name, attribution, location and material."""
    copy = objects.parse_copy(
        "(6) Drawing (Fig. 30), possibly by Anthony van Dyck, London, The British Museum,"
        " inv. no. 1858,0724.2; pen and brown ink, 125 × 95 mm."
    )
    assert copy.object_name_text == "Drawing"
    assert copy.attribution == objects.Attribution(
        "possibly by Anthony van Dyck", "Anthony van Dyck", "mogelijk van"
    )
    assert copy.location is not None
    assert (copy.location.place, copy.location.holder, copy.location.identifier) == (
        "London",
        "The British Museum",
        "1858,0724.2",
    )
    assert copy.material.note == "pen and brown ink"
    assert copy.material.dimensions is not None


def test_copy_details_are_not_a_location() -> None:
    """'edited by' is not an attribution, and dimensions and details are not a location."""
    copy = objects.parse_copy(
        "(14) Engraving by N. Lauwers, edited by N. Lauwers, 640 : 895 mm. (Fig. 165)"
    )
    assert copy.attribution is not None and copy.attribution.actor == "N. Lauwers"
    assert copy.location is None


def test_literature() -> None:
    """A literature item splits into reference, locator and note."""
    item = references.parse_literature(
        "Rooses, Oeuvre, 1886–92, IV, pp. 120, 238–39, no. 1032;"
    )
    assert (item.reference, item.locator) == (
        "Rooses, Oeuvre, 1886–92",
        "IV, pp. 120, 238–39, no. 1032",
    )
    noted = references.parse_literature("Tormo, 1942, p. 118 (as Rubens) ;")
    assert (noted.reference, noted.locator, noted.note) == (
        "Tormo, 1942",
        "p. 118",
        "as Rubens",
    )
    catalogue = references.parse_literature(
        "Liedtke, Cat. New York (Flemish Paintings), 1984, I, pp. 168–172"
    )
    assert catalogue.reference == "Liedtke, Cat. New York (Flemish Paintings), 1984"


def test_literature_continuing_the_previous_reference() -> None:
    """An item that starts with a volume continues the previous reference."""
    item = references.parse_literature("V, p. 307;")
    assert item.reference is None and item.continues_previous
    assert item.locator == "V, p. 307"


def test_exhibition() -> None:
    """An exhibition item splits into reference, catalogue number and note."""
    item = references.parse_exhibition("Denver, 1940 (no cat.);")
    assert (item.reference, item.locator, item.note) == (
        "Denver, 1940",
        None,
        "no cat.",
    )
    numbered = references.parse_exhibition("Rotterdam, 1953–54, pp. 68–69, no. 48;")
    assert numbered.reference == "Rotterdam, 1953–54"
    assert references.catalogue_number(numbered.locator) == ("48", "pp. 68–69")


def test_sale() -> None:
    """A sale gives place, house, date, lot, price, currency, buyer and note."""
    stage = provenance.parse_stage(
        "sale, Antwerp (Timmermans), 26 May 1777, lot 2 (Le Buste de Platon, sold for 260 florins to Mertens);"
    )
    assert stage is not None and stage.kind == "auction"
    assert (stage.place, stage.organiser, stage.date_text, stage.lot) == (
        "Antwerp",
        "Timmermans",
        "26 May 1777",
        "2",
    )
    assert (stage.price_amount, stage.currency, stage.buyer) == (
        "260",
        "florijnen",
        "Mertens",
    )
    assert stage.notes == ["Le Buste de Platon, sold for 260 florins to Mertens"]


def test_sale_with_house_first_and_consignor() -> None:
    """'Christie’s (London)' puts the house in the organiser; a name before 'sale' is the consignor."""
    stage = provenance.parse_stage(
        "Henry Oppenheimer, sale, Christie’s (London), 10 July 1936 et seqq., lot 308 b;"
    )
    assert stage is not None
    assert (stage.consignor, stage.place, stage.organiser, stage.lot) == (
        "Henry Oppenheimer",
        "London",
        "Christie’s",
        "308 b",
    )
    his = provenance.parse_stage(
        "his sale, London (Christie’s), 20–21 July 2011, lot 550."
    )
    assert his is not None and (his.label, his.consignor) == ("his sale", None)


def test_holder() -> None:
    """A holder with place and date, uncertain with 'probably', with life dates kept."""
    stage = provenance.parse_stage("probably Hans Gasser, Vienna;")
    assert stage is not None
    assert (stage.kind, stage.holder, stage.place, stage.uncertain) == (
        "collection",
        "Hans Gasser",
        "Vienna",
        True,
    )
    dated = provenance.parse_stage("baron Ferdinand du Bois (1767–1848) (until 1828);")
    assert dated is not None
    assert (dated.holder, dated.date_text) == (
        "baron Ferdinand du Bois (1767–1848)",
        "until 1828",
    )
    dealer = provenance.parse_stage(
        "with the dealer René Van den Broeck, Brussels, 1971;"
    )
    assert dealer is not None
    assert (dealer.holder, dealer.collection_type, dealer.date_text) == (
        "René Van den Broeck",
        "kunsthandel",
        "1971",
    )
    buyer = provenance.parse_stage("sold to Adelaide Milton de Groot (1876–1967);")
    assert (
        buyer is not None and buyer.entry_method == "purchase (method of acquisition)"
    )


@pytest.mark.parametrize(
    "text",
    [
        "acquired by Balthasar Moretus between 17 March 1613 and 2 May 1616;",
        "mentioned in the apartments of the court painters at the Madrid Palace, 1 August 1694);",
        "Sir Wathen Arthur Waller (1881– 1947), 5th Baronet;",
        "Imperial Collection Vienna as of 1733.",
    ],
)
def test_stages_left_for_the_llm(text: str) -> None:
    """Stages that are not one of the fixed forms are left for the LLM."""
    assert provenance.parse_stage(text) is None


def item(number: int, text: str) -> Node:
    """Return a provenance item node with consecutive word ids."""
    return Node(number, "item", str(number), number * 10, number * 10 + 9, None, text)


def test_chain() -> None:
    """The chain takes the consignor of 'his sale' and removal dates from neighbours, and ends with the current location."""
    items = [
        item(1, "Albert Fonson;"),
        item(2, "his sale, Oudenaarde, 5 September 1821, lot 180;"),
        item(3, "acquired by someone in a way no rule knows;"),
        item(4, "Van Diemen-Lilienfeld, New York, by 1934–1940;"),
        item(5, "by whom bequeathed to the museum."),
    ]
    location = Location(
        "The Metropolitan Museum of Art", "New York", "67.87.99", "museum (instelling)"
    )
    current = Node(9, "field", "location", 90, 99, None, "")
    chain = provenance.build_chain(items, (current, location))
    assert [row.position for row in chain] == [1, 2, 3, 4, 5]
    fonson, sale, unknown, dealer, museum = chain
    assert fonson.removal_date == "1821-09-05" and fonson.removal_derived
    assert sale.stage is not None and sale.stage.consignor == "Albert Fonson"
    assert sale.consignor_derived
    assert unknown.stage is None
    assert (dealer.removal_date, dealer.removal_derived) == ("1940", False)
    assert museum.is_current and museum.node is current
    assert museum.stage is not None
    assert museum.stage.entry_method == "bequest (method of acquisition)"


def test_mapping_tables_use_list_values() -> None:
    """Every label in a mapping table is a value of its RO list."""
    for table, values in vocabularies.MAPS.items():
        assert set(vocabularies.mapping(table).values()) <= vocabularies.labels(
            values
        ), table
