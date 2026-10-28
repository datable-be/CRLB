"""Words, lines and word forms, shared by the lexicon and the correction rules."""

import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import groupby

SOFT_HYPHEN = "\xad"
EDGE_PUNCTUATION = re.compile(r"^\W+|\W+$")


@dataclass(frozen=True)
class Word:
    """A raw word as stored in `words` (or read from a PDF, with id = position)."""

    id: int
    text: str
    block_no: int
    line_no: int


def form(text: str) -> str | None:
    """Return the lexicon form of a token: NFC, soft hyphens and edge punctuation removed, casefolded; None for no form."""
    core = EDGE_PUNCTUATION.sub(
        "", unicodedata.normalize("NFC", text.replace(SOFT_HYPHEN, ""))
    )
    if not core or any(c.isdigit() for c in core):
        return None
    return core.casefold()


def lines(words: Iterable[Word]) -> Iterator[list[Word]]:
    """Group words into lines by (block_no, line_no), keeping the stored order."""
    for _, line in groupby(words, key=lambda w: (w.block_no, w.line_no)):
        yield list(line)


def continues_word(previous_block: int, block_no: int, next_text: str) -> bool:
    """Return whether the next line continues a word broken by a soft hyphen at the end of the previous line.

    That is the case for the next line of the same block, or for the first line
    of the next block if it starts in lowercase: ABBYY puts most lines in a block
    of their own.
    """
    return block_no == previous_block or next_text[:1].islower()


def logical_words(words: list[Word]) -> Iterator[list[str]]:
    """Yield the word texts of each line for counting, with soft-hyphenated line breaks joined.

    A word ending a line with a soft hyphen is joined to the first word of the
    next line if `continues_word`. A word ending a line with a hard hyphen is
    left out, together with the word that continues it on the next line: either
    half may be a fragment ("com-" + "pany") or part of a compound ("Rubens-" +
    "House"), and fragments must not become lexicon forms.
    """
    carry = ""
    after_hard_hyphen = False
    previous_block = -1
    for line in lines(words):
        texts = [w.text for w in line]
        continues = continues_word(previous_block, line[0].block_no, texts[0])
        if carry and continues:
            texts[0] = carry + texts[0]
        elif after_hard_hyphen and continues:
            texts.pop(0)
        carry = ""
        after_hard_hyphen = False
        if texts and texts[-1].endswith(SOFT_HYPHEN):
            carry = texts.pop().rstrip(SOFT_HYPHEN)
        elif texts and texts[-1].endswith("-") and len(texts[-1]) > 1:
            texts.pop()
            after_hard_hyphen = True
        previous_block = line[0].block_no
        yield texts
