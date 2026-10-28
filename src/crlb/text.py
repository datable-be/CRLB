"""The effective text of a range of words: the one way every step after step 1 reads text.

The effective text is the tokens of the active correction run (step 2):

- with a token that crosses the start or end of the range replaced by the raw
  words inside the range;
- with the words inside page furniture of the active segmentation run (step 3)
  left out, so that the text of an entry or field that runs over a page break
  does not contain the running head and page number.

Applying corrections from reviews is added here when that exists. Every token
keeps the ids of its raw words, so each result traces back to coordinates.
"""

import sqlite3
from dataclasses import dataclass

CORRECTION_STEP = "2"
SEGMENTATION_STEP = "3"


@dataclass(frozen=True)
class TextToken:
    """A token of the effective text, with the ids of the raw words it covers."""

    text: str
    first_word_id: int
    last_word_id: int


def active_run(conn: sqlite3.Connection, step: str) -> int | None:
    """Return the active run of a step, or None if none has been set."""
    row = conn.execute(
        "SELECT run_id FROM active_runs WHERE step = ?", (step,)
    ).fetchone()
    return None if row is None else row[0]


def correction_run(conn: sqlite3.Connection, run_id: int | None) -> int:
    """Return the given correction run, or the active one; raise if there is none."""
    run_id = run_id if run_id is not None else active_run(conn, CORRECTION_STEP)
    if run_id is None:
        raise ValueError(
            "no correction run given and none is active (crlb set-active 2 <run>)"
        )
    return run_id


def raw_tokens(
    conn: sqlite3.Connection, first_word_id: int, last_word_id: int
) -> list[TextToken]:
    """Return the raw words of a range as tokens."""
    rows = conn.execute(
        "SELECT id, text FROM words WHERE id BETWEEN ? AND ? ORDER BY id",
        (first_word_id, last_word_id),
    )
    return [TextToken(text, word_id, word_id) for word_id, text in rows]


def furniture_ranges(
    conn: sqlite3.Connection,
    first_word_id: int,
    last_word_id: int,
    segmentation_run: int,
) -> list[tuple[int, int]]:
    """Return the word ranges of the furniture segments of a run that overlap a range."""
    return conn.execute(
        "SELECT first_word_id, last_word_id FROM segments WHERE run_id = ? AND kind = 'furniture'"
        " AND last_word_id >= ? AND first_word_id <= ?",
        (segmentation_run, first_word_id, last_word_id),
    ).fetchall()


def tokens(
    conn: sqlite3.Connection,
    first_word_id: int,
    last_word_id: int,
    run_id: int | None = None,
    segmentation_run: int | None = None,
    skip_furniture: bool = True,
) -> list[TextToken]:
    """Return the effective tokens of the words first_word_id..last_word_id.

    `run_id` and `segmentation_run` default to the active runs of steps 2 and 3;
    without an active segmentation run no furniture is left out.
    """
    run_id = correction_run(conn, run_id)
    rows = conn.execute(
        # The token covering the first word, which may start before the range ...
        "SELECT * FROM (SELECT text, first_word_id, last_word_id FROM corrected_words"
        " WHERE run_id = ? AND first_word_id <= ? ORDER BY first_word_id DESC LIMIT 1)"
        # ... and the tokens starting inside it
        " UNION SELECT text, first_word_id, last_word_id FROM corrected_words"
        " WHERE run_id = ? AND first_word_id > ? AND first_word_id <= ?"
        " ORDER BY first_word_id",
        (run_id, first_word_id, run_id, first_word_id, last_word_id),
    ).fetchall()
    result = []
    for text, first, last in rows:
        if last < first_word_id:
            continue
        if first < first_word_id or last > last_word_id:
            # A token crossing the boundary: keep only the raw words inside the range
            result += raw_tokens(
                conn, max(first, first_word_id), min(last, last_word_id)
            )
        else:
            result.append(TextToken(text, first, last))
    if skip_furniture:
        segmentation_run = (
            segmentation_run
            if segmentation_run is not None
            else active_run(conn, SEGMENTATION_STEP)
        )
        if segmentation_run is not None:
            ranges = furniture_ranges(
                conn, first_word_id, last_word_id, segmentation_run
            )
            result = [
                t
                for t in result
                if not any(a <= t.first_word_id <= b for a, b in ranges)
            ]
    return result


def page_tokens(
    conn: sqlite3.Connection, page_id: int, run_id: int | None = None, raw: bool = False
) -> list[tuple[str, TextToken]]:
    """Return the tokens of a page, each with the separator before it: '' first, a space within a line, a newline between lines, an empty line between blocks.

    With raw=True the raw words are used, laid out the same way, for a fair
    comparison with the corrected text.
    """
    layout = {
        word_id: (block_no, line_no)
        for word_id, block_no, line_no in conn.execute(
            "SELECT id, block_no, line_no FROM words WHERE page_id = ? ORDER BY id",
            (page_id,),
        )
    }
    if not layout:
        return []
    first, last = min(layout), max(layout)
    # Whole pages keep their furniture: they are compared with full-page ground truth
    found = (
        raw_tokens(conn, first, last)
        if raw
        else tokens(conn, first, last, run_id, skip_furniture=False)
    )
    result = []
    previous = None
    for token in found:
        position = layout[token.first_word_id]
        if previous is None:
            separator = ""
        elif position == previous:
            separator = " "
        elif position[0] == previous[0]:
            separator = "\n"
        else:
            separator = "\n\n"
        result.append((separator, token))
        previous = position
    return result


def page_text(
    conn: sqlite3.Connection, page_id: int, run_id: int | None = None, raw: bool = False
) -> str:
    """Return the text of a page rebuilt from its tokens (see page_tokens for the layout)."""
    return "".join(
        separator + token.text
        for separator, token in page_tokens(conn, page_id, run_id, raw)
    )
