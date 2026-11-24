"""Tests for the step 2b substitutions on hand-made tokens and a small lexicon."""

import pytest

from crlb.correction.rules import InvariantError, Lexicon
from crlb.correction.substitute import (
    Change,
    Substitution,
    check_changes,
    split_core,
    substitute,
)

TABLE = [
    Substitution("S1", "d", "ct", "any"),
    Substitution("S1", "â", "ct", "any"),
    Substitution("S1", "ft", "ct", "any"),
    Substitution("S1", "ft", "st", "any"),
    Substitution("S1", "S", "st", "inner"),
    Substitution("S2", "St", "st", "inner"),
]
LEXICON = Lexicon(
    born_digital={
        "first": 900,
        "collection": 800,
        "constructions": 20,
        "fact": 300,
        "fast": 40,
        "kunst": 50,
        "august": 60,
        "sem": 5,
    },
    bigrams={},
)


def change(text: str) -> Change | list[str] | None:
    """Return what the substitutions do to one token."""
    return substitute(text, TABLE, LEXICON, 3)


def test_one_substitution_keeps_the_punctuation() -> None:
    """A ligature misreading becomes the lexicon word; edge punctuation stays."""
    assert change("firft") == Change("first", "S1", "ft→st; lexicon bd=900")
    result = change("Colleâion,")
    assert isinstance(result, Change) and result.text == "Collection,"
    assert split_core("“Colleâion,”") == ("“", "Colleâion", ",”")


def test_two_substitutions_then_the_case() -> None:
    """Two misreadings in one word are corrected, and an inner capital of a ligature lowercased."""
    result = change("conStrudions")
    assert isinstance(result, Change)
    assert (result.text, result.rule) == ("constructions", "S1+S2")


def test_several_candidates_are_flagged() -> None:
    """A word that can become two lexicon words is not changed."""
    assert change("faft") == ["fact", "fast"]


def test_a_whole_word_row_decides() -> None:
    """A word row of the table resolves a word with several candidates, keeping its capital."""
    table = [*TABLE, Substitution("S1", "faft", "fact", "word")]
    assert substitute("faft,", table, LEXICON, 3) == Change(
        "fact,", "S1", "faft→fact (word); table"
    )
    result = substitute("Faft", table, LEXICON, 3)
    assert isinstance(result, Change) and result.text == "Fact"
    check_changes({(1, 1): "Faft"}, {(1, 1): Change("Fact", "S1", "")}, table)


def test_skipped_tokens() -> None:
    """Lexicon words, all-capital words, numbers and inner-only substitutions at the start are kept."""
    assert change("first") is None
    assert change("FIRFT") is None
    assert change("1d2") is None
    assert change("Sem") is None


def test_s2_lowercases_an_inner_capital() -> None:
    """The st ligature read with a capital inside a known word."""
    assert change("KunSt") == Change("Kunst", "S2", "St→st; lexicon bd=50")
    assert change("AuguS") == Change("August", "S1", "S→st; lexicon bd=60")


def test_the_invariant_allows_only_the_table() -> None:
    """A change outside the table, or on a token the base run does not have, is refused."""
    tokens = {(1, 1): "firft", (2, 3): "Colleâion"}
    check_changes(tokens, {(1, 1): Change("first", "S1", "")}, TABLE)
    with pytest.raises(InvariantError):
        check_changes(tokens, {(1, 1): Change("fixed", "S1", "")}, TABLE)
    with pytest.raises(InvariantError):
        check_changes(tokens, {(4, 4): Change("first", "S1", "")}, TABLE)
