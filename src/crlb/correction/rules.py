"""The rules of step 2a: join tokens by removing superfluous spaces and soft-hyphenated line breaks.

The rules work on the words of one page in stored order and only ever join
consecutive words, so a correction removes whitespace and soft hyphens and
nothing else (checked by `check_page`). When in doubt a rule does not join but
flags the case.

- R1, letter-spaced runs: consecutive short pieces of at most 3 letters on a
  line, as ABBYY writes letter-spaced and small-caps headings (`p r o v e n a n c e`,
  `L ite r a tu r e:`). The longest stretch of 3 or more pieces, with at least 2
  single letters, whose join is in the born-digital lexicon is joined, then the
  rest of the run; a run with 3 or more single letters and no such stretch is
  flagged.
- R2, lexicon join: 2 to 4 consecutive tokens on a line (longest first), joined
  if the result is a known form and at least one piece is not a word
  ("M useum"). If all pieces are words ("a part", "put to"), the case is only
  flagged: a joined form can be a real word too ("apart", "putto").
- Both R1 and R2 refuse a join that puts a single letter after a word ("the E
  lder" -> "theE"; the letter starts the next word), or that ends in a word and
  is rare in the born-digital text ("o f the" -> "ofthe", a typo found once).
- R3, soft hyphen at line end: joined with the first token of the next line in
  the same block, or of the next block if that token starts in lowercase. The
  only rule that also runs on born-digital documents.
"""

import re
import sqlite3
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from crlb.correction.tokens import (
    EDGE_PUNCTUATION,
    SOFT_HYPHEN,
    Word,
    continues_word,
    form,
    lines,
)

ALL_RULES = ("R1", "R2", "R3")
SINGLE_LETTER_WORDS = {"a", "A", "I"}
INVISIBLE = re.compile(rf"[\s{SOFT_HYPHEN}]")


class InvariantError(ValueError):
    """A correction changed more than whitespace and soft hyphens, or lost or repeated a word."""


@dataclass(frozen=True)
class Token:
    """A token of the corrected text: one raw word, or consecutive raw words joined by a rule."""

    first: int  # word id of the first raw word
    last: int  # word id of the last raw word
    text: str
    rule: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class Flag:
    """A join a rule considered but did not apply."""

    first: int
    last: int
    rule: str
    candidate: str
    reason: str


@dataclass
class Lexicon:
    """The born-digital form and bigram counts, plus the form counts of the document being corrected."""

    born_digital: dict[str, int]
    bigrams: dict[tuple[str, str], int]
    document: Counter[str] = field(default_factory=Counter)

    @classmethod
    def load(cls, conn: sqlite3.Connection) -> Lexicon:
        """Load the lexicon tables built by `crlb lexicon`."""
        return cls(
            born_digital=dict(
                conn.execute("SELECT form, born_digital FROM lexicon").fetchall()
            ),
            bigrams={
                (a, b): n
                for a, b, n in conn.execute(
                    "SELECT first, second, born_digital FROM bigrams"
                )
            },
        )

    def is_word(self, text: str) -> bool:
        """Return whether a piece is a word: a born-digital form, with single letters other than a, A and I not counting."""
        core = EDGE_PUNCTUATION.sub("", text)
        if len(core) == 1:
            return core in SINGLE_LETTER_WORDS
        f = form(text)
        return f is not None and f in self.born_digital


@dataclass(frozen=True)
class Options:
    """The thresholds of the rules, recorded in the correction run."""

    min_doc_count: int = 5  # occurrences in the same document that accept a joined form
    max_window: int = 4  # most tokens joined by R2
    min_count_word_end: int = 2  # born-digital count of a join whose last piece is a word ("o f the" / "ofthe")


def join(tokens: list[Token], rule: str, reason: str) -> Token:
    """Join consecutive tokens into one."""
    return Token(
        tokens[0].first, tokens[-1].last, "".join(t.text for t in tokens), rule, reason
    )


def is_single_letter(token: Token) -> bool:
    """Return whether a token is one letter, apart from surrounding punctuation."""
    core = EDGE_PUNCTUATION.sub("", token.text)
    return len(core) == 1 and core.isalpha()


def is_short_piece(token: Token) -> bool:
    """Return whether a token can be a piece of a letter-spaced word: 1 to 3 letters, apart from surrounding punctuation."""
    core = EDGE_PUNCTUATION.sub("", token.text)
    return token.rule is None and 1 <= len(core) <= 3 and core.isalpha()


def lookup(lexicon: Lexicon, text: str) -> tuple[int, int]:
    """Return the born-digital and document counts of the form of a joined text."""
    f = form(text)
    if f is None:
        return 0, 0
    return lexicon.born_digital.get(f, 0), lexicon.document[f]


def implausible(
    pieces: list[str], bd: int, lexicon: Lexicon, options: Options
) -> str | None:
    """Return why joining the pieces is implausible although the result is a known form, or None."""
    *rest, last = pieces
    last_core = EDGE_PUNCTUATION.sub("", last)
    if (
        len(last_core) == 1
        and not lexicon.is_word(last)
        and all(lexicon.is_word(p) for p in rest)
    ):
        # "the E lder", "de C rayer": the letter starts the next word
        return "a single letter after a word starts the next word"
    if (
        len(last_core) >= 2
        and lexicon.is_word(last)
        and bd < options.min_count_word_end
    ):
        return f"ends in a word and the join is rare (bd={bd} < {options.min_count_word_end})"
    return None


def join_spaced(run: list[Token], lexicon: Lexicon, options: Options) -> list[Token]:
    """Join the longest stretch of a run of short pieces that forms a plausible born-digital word, then the rest on either side."""
    for n in range(len(run), 2, -1):
        for start in range(len(run) - n + 1):
            window = run[start : start + n]
            if sum(is_single_letter(t) for t in window) < 2:
                continue
            pieces = [t.text for t in window]
            bd, _ = lookup(lexicon, "".join(pieces))
            if bd and not implausible(pieces, bd, lexicon, options):
                joined = join(window, "R1", f"pieces: {'|'.join(pieces)}; bd={bd}")
                return (
                    join_spaced(run[:start], lexicon, options)
                    + [joined]
                    + join_spaced(run[start + n :], lexicon, options)
                )
    return run


def apply_r1(
    tokens: list[Token], lexicon: Lexicon, options: Options, flags: list[Flag]
) -> list[Token]:
    """Join letter-spaced words in runs of short pieces; flag runs of single letters that form no known word."""
    result: list[Token] = []
    i = 0
    while i < len(tokens):
        j = i
        while j < len(tokens) and is_short_piece(tokens[j]):
            j += 1
        if j == i:
            result.append(tokens[i])
            i += 1
            continue
        run = tokens[i:j]
        joined = join_spaced(run, lexicon, options)
        result.extend(joined)
        if (
            not any(t.rule for t in joined)
            and sum(is_single_letter(t) for t in run) >= 3
        ):
            candidate = "".join(t.text for t in run)
            flags.append(
                Flag(
                    run[0].first,
                    run[-1].last,
                    "R1",
                    candidate,
                    "not in the born-digital lexicon",
                )
            )
        i = j
    return result


def judge_r2(
    window: list[Token], lexicon: Lexicon, options: Options
) -> tuple[bool | None, str]:
    """Decide on joining a window: True (join), False (flag) or None (not a candidate), with the reason."""
    pieces = [t.text for t in window]
    bd, doc = lookup(lexicon, "".join(pieces))
    if bd < 1 and doc < options.min_doc_count:
        return None, ""
    counts = f"bd={bd}; doc={doc}"
    if not all(lexicon.is_word(p) for p in pieces):
        if reason := implausible(pieces, bd, lexicon, options):
            return False, f"{reason}; {counts}"
        return True, f"pieces: {'|'.join(pieces)}; {counts}"
    # Two real words may also form a real word ("put to" / "putto"): never join, only flag
    reason = f"all {len(window)} pieces are words; {counts}"
    if len(window) == 2:
        first, second = form(pieces[0]), form(pieces[1])
        bigram = lexicon.bigrams.get((first, second), 0) if first and second else 0
        reason += f"; bigram={bigram}"
    return False, reason


def apply_r2(
    tokens: list[Token], lexicon: Lexicon, options: Options, flags: list[Flag]
) -> list[Token]:
    """Join windows of 2 to max_window tokens, longest first and left to right, as judged by judge_r2."""
    result: list[Token] = []
    i = 0
    while i < len(tokens):
        for n in range(min(options.max_window, len(tokens) - i), 1, -1):
            window = tokens[i : i + n]
            # Numbers are data, and tokens already joined or without a form are left alone
            if any(
                t.rule or form(t.text) is None or any(c.isdigit() for c in t.text)
                for t in window
            ):
                continue
            decision, reason = judge_r2(window, lexicon, options)
            if decision:
                result.append(join(window, "R2", reason))
                i += n
                break
            if decision is False:
                flags.append(
                    Flag(
                        window[0].first,
                        window[-1].last,
                        "R2",
                        "".join(t.text for t in window),
                        reason,
                    )
                )
        else:
            result.append(tokens[i])
            i += 1
    return result


def apply_r3(
    line_tokens: list[tuple[int, list[Token]]], flags: list[Flag]
) -> list[Token]:
    """Join a token ending a line with a soft hyphen to the first token of the next line, if `continues_word`; flag it otherwise."""
    merged: list[tuple[int, list[Token]]] = []
    for block_no, tokens in line_tokens:
        tokens = list(tokens)
        if merged:
            previous_block, previous = merged[-1]
            if previous and previous[-1].text.endswith(SOFT_HYPHEN):
                head, nxt = previous[-1], tokens[0]
                candidate = head.text.removesuffix(SOFT_HYPHEN) + nxt.text
                if continues_word(previous_block, block_no, nxt.text):
                    where = "same block" if block_no == previous_block else "next block"
                    reason = "; ".join(
                        r
                        for r in (
                            f"soft hyphen at line end, {where}",
                            head.reason,
                            nxt.reason,
                        )
                        if r
                    )
                    previous[-1] = Token(head.first, nxt.last, candidate, "R3", reason)
                    tokens.pop(0)
                    if not tokens:
                        # The whole line was absorbed; the next line may continue the same word
                        continue
                else:
                    flags.append(
                        Flag(
                            head.first,
                            nxt.last,
                            "R3",
                            candidate,
                            "next block does not start in lowercase",
                        )
                    )
        merged.append((block_no, tokens))
    return [t for _, tokens in merged for t in tokens]


def correct_page(
    words: list[Word],
    lexicon: Lexicon,
    options: Options,
    rules: Iterable[str] = ALL_RULES,
) -> tuple[list[Token], list[Flag]]:
    """Apply the given rules to the words of one page; return the tokens covering every word, and the flags."""
    rules = set(rules)
    flags: list[Flag] = []
    line_tokens = []
    for line in lines(words):
        tokens = [Token(w.id, w.id, w.text) for w in line]
        if "R1" in rules:
            tokens = apply_r1(tokens, lexicon, options, flags)
        if "R2" in rules:
            tokens = apply_r2(tokens, lexicon, options, flags)
        line_tokens.append((line[0].block_no, tokens))
    if "R3" in rules:
        return apply_r3(line_tokens, flags), flags
    return [t for _, tokens in line_tokens for t in tokens], flags


def check_page(words: list[Word], tokens: list[Token]) -> None:
    """Raise InvariantError unless the tokens cover every word exactly once, in order, and change only whitespace and soft hyphens."""
    position = {w.id: i for i, w in enumerate(words)}
    expected = 0
    for token in tokens:
        if (
            position.get(token.first) != expected
            or position.get(token.last, -1) < expected
        ):
            raise InvariantError(
                f"token {token.first}-{token.last} does not continue at word {expected}"
            )
        expected = position[token.last] + 1
    if expected != len(words):
        raise InvariantError(f"tokens cover {expected} of {len(words)} words")
    raw = INVISIBLE.sub("", "".join(w.text for w in words))
    corrected = INVISIBLE.sub("", "".join(t.text for t in tokens))
    if raw != corrected:
        raise InvariantError(
            "the corrected text differs from the raw text in more than whitespace and soft hyphens"
        )
