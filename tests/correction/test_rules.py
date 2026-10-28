"""Tests for the step 2a rules on hand-made words and a small lexicon."""

from collections import Counter

import pytest

from crlb.correction.rules import (
    InvariantError,
    Lexicon,
    Options,
    Token,
    check_page,
    correct_page,
)
from crlb.correction.tokens import Word

LEXICON = Lexicon(
    born_digital={
        "museum": 400,
        "provenance": 50,
        "a": 9000,
        "part": 300,
        "apart": 40,
        "into": 5000,
        "in": 9000,
        "to": 9000,
        "the": 20000,
        "copies": 800,
        "literature": 900,
        "putto": 120,
        "put": 300,
        "flight": 40,
        "pan": 10,
        "vino": 3,
        "elder": 177,
        "crayer": 138,
        "dec": 4,
        "thee": 9,
        "them": 1941,
        "of": 170518,
        "ofthe": 1,
        "count": 780,
        "de": 60000,
    },
    bigrams={("a", "part"): 30, ("in", "to"): 10},
)


def page(*lines: str, blocks: list[int] | None = None) -> list[Word]:
    """Return the words of a page, one string per line, each line in block 0 unless blocks are given."""
    words = []
    for line_no, line in enumerate(lines):
        block_no = blocks[line_no] if blocks else 0
        words += [
            Word(len(words) + i, text, block_no, line_no)
            for i, text in enumerate(line.split(" "))
        ]
    return words


def corrected(
    *lines: str, blocks: list[int] | None = None, rules: tuple = ("R1", "R2", "R3")
) -> list[Token]:
    """Correct a page and return its tokens, after checking the invariant."""
    words = page(*lines, blocks=blocks)
    tokens, _ = correct_page(words, LEXICON, Options(), rules)
    check_page(words, tokens)
    return tokens


def texts(tokens: list[Token]) -> list[str]:
    """Return the texts of tokens."""
    return [t.text for t in tokens]


def test_r1_joins_letter_spaced_run() -> None:
    """A letter-spaced word in the lexicon is joined, keeping its case."""
    tokens = corrected("P r o v e n a n c e")
    assert texts(tokens) == ["Provenance"] and tokens[0].rule == "R1"


def test_r1_flags_unknown_run() -> None:
    """A run of single letters that is not a known word is flagged, not joined."""
    words = page("x y z w")
    tokens, flags = correct_page(words, LEXICON, Options())
    assert texts(tokens) == ["x", "y", "z", "w"]
    assert [(f.rule, f.candidate) for f in flags] == [("R1", "xyzw")]


@pytest.mark.parametrize("line", ["M useum", "Mu seum", "Museu m", "M u seum"])
def test_r2_joins_split_word(line: str) -> None:
    """A word split by superfluous spaces is joined when a piece is not a word."""
    tokens = corrected(f"the {line} of")
    assert texts(tokens) == ["the", "Museum", "of"] and tokens[1].rule == "R2"


def test_r2_keeps_punctuation_and_case() -> None:
    """Punctuation around the pieces stays in the joined token."""
    assert texts(corrected("(M useum),")) == ["(Museum),"]


def test_r2_never_joins_two_words() -> None:
    """Two real words are only flagged, even if their join is a frequent word ('put to' / 'putto')."""
    words = page("a part put to flight in to")
    tokens, flags = correct_page(words, LEXICON, Options())
    assert texts(tokens) == ["a", "part", "put", "to", "flight", "in", "to"]
    assert [f.candidate for f in flags] == ["apart", "putto", "into"]


def test_single_letter_word_is_not_glued_to_a_fragment() -> None:
    """'pan y vino' stays: 'pany' is no lexicon form once hyphenation fragments are left out."""
    assert texts(corrected("pan y vino")) == ["pan", "y", "vino"]


@pytest.mark.parametrize(
    ("line", "joined"),
    [("C o p ie s:", "Copies:"), ("L ite r a tu r e:", "Literature:")],
)
def test_r1_joins_small_caps_pieces(line: str, joined: str) -> None:
    """ABBYY small caps split into pieces of 1 to 3 letters are joined as one word."""
    tokens = corrected(line)
    assert texts(tokens) == [joined] and tokens[0].rule == "R1"


def test_r2_never_joins_digits() -> None:
    """Tokens with digits are never joined, even if the result looks known."""
    lexicon = Lexicon(born_digital={"no1": 10}, bigrams={})
    words = page("No 1")
    tokens, _ = correct_page(words, lexicon, Options())
    assert texts(tokens) == ["No", "1"]


def test_r2_accepts_form_frequent_in_the_same_document() -> None:
    """A form missing from the born-digital lexicon is accepted if it occurs often enough unsplit in the document."""
    lexicon = Lexicon(born_digital={}, bigrams={}, document=Counter({"rooses": 5}))
    tokens, _ = correct_page(page("R ooses"), lexicon, Options())
    assert texts(tokens) == ["Rooses"]
    lexicon.document["rooses"] = 4
    assert texts(correct_page(page("R ooses"), lexicon, Options())[0]) == ["R", "ooses"]


def test_r3_joins_soft_hyphen_at_line_end() -> None:
    """A soft hyphen at the end of a line joins with the next line; the hyphen is removed."""
    tokens = corrected("the Mu\xad", "seum is")
    assert texts(tokens) == ["the", "Museum", "is"] and tokens[1].rule == "R3"


def test_r3_crosses_blocks_only_into_lowercase() -> None:
    """Across blocks (ABBYY lines), only a next word in lowercase continues the word."""
    assert texts(corrected("Mu\xad", "seum", blocks=[0, 1])) == ["Museum"]
    words = page("Mu\xad", "Seum", blocks=[0, 1])
    tokens, flags = correct_page(words, LEXICON, Options())
    assert texts(tokens) == ["Mu\xad", "Seum"] and flags[0].rule == "R3"


def test_r3_never_joins_on_hard_hyphen() -> None:
    """A hard hyphen at line end may be a compound and is left alone."""
    assert texts(corrected("Rubens-", "House")) == ["Rubens-", "House"]


def test_born_digital_gets_only_r3() -> None:
    """With only R3, superfluous spaces are not touched."""
    assert texts(corrected("M useum Mu\xad", "seum", rules=("R3",))) == [
        "M",
        "useum",
        "Museum",
    ]


def test_check_page_catches_changed_text() -> None:
    """A token that changes a letter violates the invariant."""
    words = page("M useum")
    with pytest.raises(InvariantError, match="differs"):
        check_page(words, [Token(0, 1, "Muse on")])


def test_check_page_catches_skipped_word() -> None:
    """Tokens must cover every word exactly once."""
    words = page("the M useum")
    with pytest.raises(InvariantError):
        check_page(words, [Token(0, 0, "the"), Token(2, 2, "useum")])


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("the E lder", ["the", "Elder"]),
        ("G. de C rayer", ["G.", "de", "Crayer"]),
        ("into the m useu m", ["into", "the", "museum"]),
    ],
)
def test_single_letter_is_not_glued_to_the_word_before(
    line: str, expected: list[str]
) -> None:
    """A single letter after a word starts the next word ('theE', 'deC' and 'them' are refused)."""
    assert texts(corrected(line)) == expected


def test_rare_join_ending_in_a_word_is_refused() -> None:
    """'o f the' does not become 'ofthe', a typo found once in the born-digital text."""
    words = page("C ou n t o f the")
    tokens, _ = correct_page(words, LEXICON, Options())
    assert "ofthe" not in texts(tokens)
    assert texts(tokens)[0] == "Count"
