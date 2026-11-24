"""Tests for the index entries of step 3 (rule 10)."""

from crlb.segmentation import index
from crlb.segmentation.model import Document, Line, Seg, Word

HEIGHT, WIDTH = 800.0, 500.0


class IndexPages:
    """Build index pages of lines with consecutive word ids, each line at its own x."""

    def __init__(self) -> None:
        """Start with no pages."""
        self.pages: list[list[Line]] = []
        self.next_id = 1

    def page(self, *lines: tuple[float, str], introduction: int = 0) -> None:
        """Add a page; each line is (x of its first word, text); the first lines can form an introduction block."""
        result = []
        for k, (x, text) in enumerate(lines):
            block = 0 if k < introduction else 1
            y0 = 100 + 12 * k
            words = []
            for i, t in enumerate(text.split(" ")):
                words.append(
                    Word(
                        self.next_id,
                        t,
                        "Palatino",
                        8.9,
                        0,
                        x + 20 * i,
                        y0,
                        x + 20 * i + 18,
                        y0 + 9,
                        block,
                    )
                )
                self.next_id += 1
            result.append(Line(len(self.pages), HEIGHT, WIDTH, words, corrected=text))
        self.pages.append(result)

    def items(self, layout: str, indent: float = 10.0, hanging: int = 2) -> list[Seg]:
        """Return the index items of all pages as one section."""
        doc = Document(1, "test.pdf", "XIX (4)", self.pages, [], [])
        section = Seg("section", "index", 1, self.next_id - 1, "test", "certain")
        return index.index_items(doc, section, indent, hanging, layout, set())


def texts(pages: IndexPages, segs: list[Seg]) -> list[tuple[str, list]]:
    """Return each item's own text (without its sub-items) and its sub-items, recursively."""
    words = {w.id: w.text for page in pages.pages for line in page for w in line.words}

    def own(seg: Seg) -> str:
        """Return the text of an item before its first sub-item."""
        end = seg.children[0].first - 1 if seg.children else seg.last
        return " ".join(words[i] for i in range(seg.first, end + 1))

    return [(own(s), texts(pages, s.children)) for s in segs]


def test_sub_entries_by_indentation_and_continuation_lines() -> None:
    """A line one step in is a sub-entry; page references and a hanging indent continue an item."""
    pages = IndexPages()
    pages.page(
        (80, "Bellori, Giovanni Pietro"),
        (90, "Le Vite de’ pittori 11 n. 4,"),
        (110, "16, 46, 48"),
        (80, "Berlin 64, 92, 93 n. 6,"),
        (110, "141"),
        (90, "Stiftung Preußischer Kulturbesitz"),
        (100, "Staatliche Museen zu Berlin"),
        (110, "Gemäldegalerie 12, 15 n. 23"),
        (80, "Bonhams (auctioneer) 94, 96"),
    )
    found = texts(pages, pages.items(index.NAMES))
    assert found == [
        ("Bellori, Giovanni Pietro", [("Le Vite de’ pittori 11 n. 4, 16, 46, 48", [])]),
        (
            "Berlin 64, 92, 93 n. 6, 141",
            [
                (
                    "Stiftung Preußischer Kulturbesitz",
                    [
                        (
                            "Staatliche Museen zu Berlin",
                            [("Gemäldegalerie 12, 15 n. 23", [])],
                        )
                    ],
                )
            ],
        ),
        ("Bonhams (auctioneer) 94, 96", []),
    ]


def test_an_entry_continues_in_the_next_column_and_after_an_open_bracket() -> None:
    """The levels are measured from each column's edge; an open bracket and a lower-case line continue."""
    pages = IndexPages()
    pages.page(
        (80, "Beys, Gillis 57, 82"),
        (80, "Bosschaert, Thomas (and J. van"),
        (90, "den Hoecke)"),
        (90, "July and August (cartoon), Vienna,"),
        (300, "Kunsthistorisches Museum 2, 142"),
        (290, "Carpio, Luis Méndez de Haro"),
        (300, "y Guzmán 119-121"),
        (290, "Cardon, C.L. 231"),
    )
    found = texts(pages, pages.items(index.NAMES, hanging=1))
    assert found == [
        ("Beys, Gillis 57, 82", []),
        (
            "Bosschaert, Thomas (and J. van den Hoecke)",
            [
                (
                    "July and August (cartoon), Vienna, Kunsthistorisches Museum 2, 142",
                    [],
                )
            ],
        ),
        ("Carpio, Luis Méndez de Haro y Guzmán 119-121", []),
        ("Cardon, C.L. 231", []),
    ]


def test_collections_with_attributions_and_works() -> None:
    """A line in capitals is a collection, a line ending in ':' an attribution, works run to their number."""
    pages = IndexPages()
    pages.page(
        (60, "ANTWERP, MUSEUM PLANTIN-MORETUS"),
        (60, "Rubens, painting:"),
        (60, "Portrait of Philip the Fair, Duke of Burgundy,"),
        (60, "No. 58; 31, 40, fig. 199"),
        (60, "After Rubens, painting:"),
        (60, "Portrait of Jan Moretus I, No. 2, Copy; 58, fig. 6"),
        (60, "TURIN, MUSEO"),
        (60, "CIVICO"),
        (60, "J. Geubels, J. Raes, J. Fobert and H."),
        (60, "Vervoert, tapestries after Rubens:"),
        (60, "Elijah and the Angel, Cat. 9a, 89-94,"),
        (60, "99, fig. 138"),
        (60, "The Victory of Truth, a t . 17, 253"),
    )
    found = texts(pages, pages.items(index.COLLECTIONS))
    assert found == [
        (
            "ANTWERP, MUSEUM PLANTIN-MORETUS",
            [
                (
                    "Rubens, painting:",
                    [
                        (
                            "Portrait of Philip the Fair, Duke of Burgundy, No. 58; 31, 40, fig. 199",
                            [],
                        )
                    ],
                ),
                (
                    "After Rubens, painting:",
                    [("Portrait of Jan Moretus I, No. 2, Copy; 58, fig. 6", [])],
                ),
            ],
        ),
        (
            "TURIN, MUSEO CIVICO",
            [
                (
                    "J. Geubels, J. Raes, J. Fobert and H. Vervoert, tapestries after Rubens:",
                    [
                        ("Elijah and the Angel, Cat. 9a, 89-94, 99, fig. 138", []),
                        ("The Victory of Truth, a t . 17, 253", []),
                    ],
                )
            ],
        ),
    ]
    assert all(s.confidence == "certain" for s in pages.items(index.COLLECTIONS))


def test_the_introduction_is_no_item() -> None:
    """A block with a line wider than a column is the introduction, a field of its own."""
    pages = IndexPages()
    long = " ".join(["word"] * 16)  # 16 words of 20 pt: wider than half the page
    pages.page(
        (60, long),
        (60, "to place."),
        (60, "AMHERST, AMHERST COLLEGE"),
        (60, "Rubens, modello:"),
        (60, "Charity, Cat. 20b, 43"),
        introduction=2,
    )
    segs = pages.items(index.COLLECTIONS)
    assert [(s.kind, s.label) for s in segs] == [
        ("field", "introduction"),
        ("item", index.ENTRY),
    ]
    assert segs[0].last == segs[1].first - 1


def test_an_entry_without_page_reference_is_probable() -> None:
    """A final entry needs a page reference or a 'see'; otherwise it is kept as probable."""
    pages = IndexPages()
    pages.page(
        (80, "Caesar: see Julius Caesar"),
        (80, "Christie’s (Amsterdam)"),
        (80, "Basel 55"),
    )
    assert [s.confidence for s in pages.items(index.NAMES)] == [
        "certain",
        "probable",
        "certain",
    ]
