"""Note markers: the digits at the end of a word that refer to a note of the entry (`note_refs`).

A marker is a word that ends in digits after a letter or punctuation
('1630?).1', 'stage.2', 'Brussels,22'), in the text of an entry outside its
notes. The numbers run in sequence, so a word counts only with the next
expected number or the one after it (a marker the rules miss does not stop the
sequence), and only if the entry has a note with that number. In born-digital
volumes the digits are set in another style than the word (`words.styles` > 1),
which is required there; the OCR gives them the style of the word.
"""

import re
import sqlite3
from dataclasses import dataclass

# Digits after a letter or closing punctuation; not after an opening bracket or a
# dash, where they are a number or a range ('(3', '11-1')
MARKER = re.compile(r"^(?P<body>.*[^\d\s(\[\-–/])(?P<number>\d{1,3})$")


@dataclass(frozen=True)
class Candidate:
    """A word of an entry's text, with whether its style changes inside it."""

    id: int
    text: str
    mixed_style: bool


@dataclass(frozen=True)
class Marker:
    """A note marker found in the text."""

    word_id: int
    number: str
    mixed_style: bool


def find_markers(
    words: list[Candidate], notes: set[str], requires_style: bool
) -> list[Marker]:
    """Return the note markers among the words of an entry, in sequence from 1."""
    result = []
    expected = 1
    for word in words:
        match = MARKER.match(word.text)
        if not match or (requires_style and not word.mixed_style):
            continue
        number = int(match["number"])
        if number in (expected, expected + 1) and match["number"] in notes:
            result.append(Marker(word.id, match["number"], word.mixed_style))
            expected = number + 1
    return result


def insert_note_refs(
    conn: sqlite3.Connection, run_id: int, document_id: int, requires_style: bool
) -> tuple[int, int]:
    """Store the note markers of every entry and group introduction of a document in a run; return the markers and the notes."""
    markers = notes_total = 0
    furniture = conn.execute(
        "SELECT first_word_id, last_word_id FROM segments"
        " WHERE run_id = ? AND document_id = ? AND kind = 'furniture'",
        (run_id, document_id),
    ).fetchall()
    entries = conn.execute(
        "SELECT id, first_word_id, last_word_id FROM segments"
        " WHERE run_id = ? AND document_id = ? AND kind IN ('entry', 'group') ORDER BY first_word_id",
        (run_id, document_id),
    ).fetchall()
    for entry_id, first, last in entries:
        notes = conn.execute(
            "SELECT n.id, n.label, f.first_word_id, f.last_word_id FROM segments f"
            " JOIN segments n ON n.parent_id = f.id"
            " WHERE f.parent_id = ? AND f.label = 'notes' AND n.kind = 'note'",
            (entry_id,),
        ).fetchall()
        if not notes:
            continue
        notes_total += len(notes)
        by_number = {label: note_id for note_id, label, _, _ in notes}
        start, end = notes[0][2], notes[0][3]
        inside = [(a, b) for a, b in furniture if a <= last and b >= first]
        words = [
            Candidate(word_id, text, styles > 1)
            for word_id, text, styles in conn.execute(
                "SELECT id, text, styles FROM words WHERE id BETWEEN ? AND ?"
                " AND NOT (id BETWEEN ? AND ?) ORDER BY id",
                (first, last, start, end),
            )
            if not any(a <= word_id <= b for a, b in inside)
        ]
        found = find_markers(words, set(by_number), requires_style)
        conn.executemany(
            "INSERT INTO note_refs (run_id, word_id, note_segment_id, rule, confidence)"
            " VALUES (?, ?, ?, ?, ?)",
            [
                (
                    run_id,
                    m.word_id,
                    by_number[m.number],
                    "digits after a word, in sequence",
                    "certain" if m.mixed_style else "probable",
                )
                for m in found
            ],
        )
        markers += len(found)
    return markers, notes_total
