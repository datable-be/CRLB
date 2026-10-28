"""Tests for counting word forms and building the lexicon."""

import sqlite3
from collections import Counter
from pathlib import Path

from crlb.correction.lexicon import build_lexicon, count_page
from crlb.correction.tokens import Word, form


def words(*lines: str, blocks: list[int] | None = None) -> list[Word]:
    """Return words, one string per line."""
    result = []
    for line_no, line in enumerate(lines):
        block_no = blocks[line_no] if blocks else 0
        result += [Word(len(result), t, block_no, line_no) for t in line.split(" ")]
    return result


def counted(*lines: str, blocks: list[int] | None = None) -> Counter[str]:
    """Return the form counts of a page."""
    forms: Counter[str] = Counter()
    count_page(words(*lines, blocks=blocks), forms)
    return forms


def test_form_strips_punctuation_and_folds_case() -> None:
    """Forms are casefolded without edge punctuation and soft hyphens; digits give no form."""
    assert form("(Museum),") == "museum"
    assert form("Bio\xadgraphy") == "biography"
    assert form("1625") is None and form("p.12") is None and form("—") is None


def test_soft_hyphen_at_line_end_is_joined_before_counting() -> None:
    """A soft-hyphenated word counts as one form, also into a next block in lowercase."""
    assert counted("the biogra\xad", "phy of") == Counter(
        {"the": 1, "biography": 1, "of": 1}
    )
    assert counted("biogra\xad", "phy", blocks=[0, 1])["biography"] == 1


def test_hard_hyphen_at_line_end_is_not_counted() -> None:
    """Both halves of a word broken by a hard hyphen are left out: they may be fragments ('com-' + 'pany')."""
    assert counted("the com-", "pany of") == Counter({"the": 1, "of": 1})
    assert counted("the Rubens-", "House") == Counter({"the": 1})


def test_lexicon_is_built_from_the_sources(
    corpus_db: sqlite3.Connection, tmp_path: Path
) -> None:
    """Building from a PDF fills the lexicon, bigrams and sources; OCR pieces never become born-digital forms."""
    n_sources, n_forms, n_bigrams = build_lexicon(corpus_db, tmp_path, ["bd.pdf"])
    assert (
        n_sources == 1 and n_forms == 10 and n_bigrams == 1
    )  # only ('a', 'part'): 'apart' is a form
    lexicon = dict(
        corpus_db.execute("SELECT form, born_digital FROM lexicon").fetchall()
    )
    assert lexicon["museum"] == 2 and "useum" not in lexicon
    ocr = dict(corpus_db.execute("SELECT form, ocr FROM lexicon").fetchall())
    assert ocr["antwerp"] == 1
    source = corpus_db.execute("SELECT path, pages FROM lexicon_sources").fetchone()
    assert tuple(source) == ("bd.pdf", 1)
