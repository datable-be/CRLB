"""Exhibitions and literature of an entry by rules: each item split into the reference and its locator.

An item `Rooses, Oeuvre, 1886–92, IV, pp. 120, 238–39, no. 1032;` becomes the
reference `Rooses, Oeuvre, 1886–92` and the locator `IV, pp. 120, 238–39,
no. 1032`; an exhibition item `New York, 1934, no. 21;` becomes the reference
`New York, 1934` and the catalogue number `21`. Trailing remarks in brackets
(`(as Rubens)`, `(no cat.)`) are the note. Resolving the reference to the
volume's abbreviation list is not done yet.
"""

import re
import sqlite3
from collections import Counter
from dataclasses import dataclass

from crlb.extraction.objects import span_text, split_spans
from crlb.extraction.source import Entry, Node, insert

# The first part of a locator: page (also OCR 'PP-', 'p .'), number, figure, plate, note, column, reproduction
LOCATOR = re.compile(
    r"^(?:pp?\s?[.\-'’]|nos?\b\.?|under\b|figs?\b\.?|pls?\.|plates?\b|cols?\.|repr\.|ill\.|n\.|nn\.|cat\.\s*nos?\b|lot\b|s\.v\.)",
    re.IGNORECASE,
)
# A volume number before the locator: roman (also OCR 'ill', 'hi'), or one or two digits ('11' for II)
VOLUME = re.compile(r"^(?:[IVXLCivxlc]{1,6}|ill|hi|\d{1,2})$")
CATALOGUE_NUMBER = re.compile(r"^(?:cat\.\s*)?nos?\.?\s*(?P<number>.+)$", re.IGNORECASE)
TRAILING_NOTE = re.compile(r"\s*\((?P<note>[^()]*)\)$")


@dataclass
class Reference:
    """A literature or exhibition item split into reference, locator and note."""

    reference: str | None
    locator: str | None
    note: str | None
    continues_previous: bool = False


def clean(text: str) -> str:
    """Return an item without its trailing separator: 'New York, 1934, no. 21;' -> 'New York, 1934, no. 21'."""
    return text.strip().rstrip(";,.-").strip()


def split_note(text: str) -> tuple[str, str | None]:
    """Split a trailing remark in brackets off an item: 'Tormo, 1942, p. 118 (as Rubens)' -> ('Tormo, 1942, p. 118', 'as Rubens')."""
    match = TRAILING_NOTE.search(text)
    if match is None or match.start() == 0:
        return text, None
    return text[: match.start()].rstrip(" ,"), match["note"].strip()


def parse_literature(text: str) -> Reference:
    """Return the reference, locator and note of a literature item."""
    body, note = split_note(clean(text))
    if body.lower().startswith("see "):
        return Reference(None, body, note)
    spans = split_spans(body, ",")
    parts = [body[a:b] for a, b in spans]
    start = next(
        (
            i
            for i, part in enumerate(parts)
            if LOCATOR.match(part)
            or (
                VOLUME.match(part)
                and i + 1 < len(parts)
                and LOCATOR.match(parts[i + 1])
            )
        ),
        len(parts),
    )
    reference = span_text(body, spans[:start]) if start else None
    locator = span_text(body, spans[start:]) if start < len(spans) else None
    # 'V, p. 307' after 'Rooses, 1, p. 57': another volume of the previous reference
    return Reference(reference, locator, note, continues_previous=reference is None)


def parse_exhibition(text: str) -> Reference:
    """Return the reference, catalogue number and note of an exhibition item."""
    body, note = split_note(clean(text))
    spans = split_spans(body, ",")
    parts = [body[a:b] for a, b in spans]
    start = next(
        (i for i, part in enumerate(parts) if i > 0 and LOCATOR.match(part)),
        len(parts),
    )
    locator = span_text(body, spans[start:]) if start < len(spans) else None
    return Reference(span_text(body, spans[:start]) or None, locator, note)


def catalogue_number(locator: str | None) -> tuple[str | None, str | None]:
    """Split an exhibition locator into the catalogue number and the rest: 'pp. 68–69, no. 48' -> ('48', 'pp. 68–69')."""
    text = locator or ""
    spans = split_spans(text, ",")
    for k, (a, b) in enumerate(spans):
        match = CATALOGUE_NUMBER.match(text[a:b])
        if match:
            number = text[a + match.start("number") : spans[-1][1]].strip()
            return number, span_text(text, spans[:k]) if k else None
    return None, locator


def object_nodes(entry: Entry) -> list[Node]:
    """Return the entry and its copies: the nodes whose fields belong to an object."""
    return [
        entry.node,
        *(
            copy
            for numbered in entry.node.children
            if numbered.kind == "field"
            for copy in numbered.children
            if copy.kind == "copy"
        ),
    ]


def extract_entry(
    conn: sqlite3.Connection,
    run_id: int,
    entry: Entry,
    object_ids: dict[int, int],
    counts: Counter[str],
) -> None:
    """Store the exhibition and literature items of an entry and its copies."""
    for owner in object_nodes(entry):
        object_id = object_ids[owner.id]
        for field in owner.fields("exhibited"):
            for item in (c for c in field.children if c.kind == "item"):
                parsed = parse_exhibition(item.text)
                number, other = catalogue_number(parsed.locator)
                insert(
                    conn,
                    "ro_object_exhibitions",
                    item,
                    run_id,
                    object_id=object_id,
                    exhibition_reference=parsed.reference,
                    exhibition_cat_number=number,
                    # A locator that is not a catalogue number ('p. 124') goes with the note
                    exhibition_note="; ".join(n for n in (other, parsed.note) if n)
                    or None,
                    reference_text=clean(item.text),
                )
                counts["exhibitions"] += 1
                counts["exhibitions with a catalogue number"] += number is not None
        previous: str | None = None
        for field in owner.fields("literature"):
            for item in (c for c in field.children if c.kind == "item"):
                parsed = parse_literature(item.text)
                reference = parsed.reference
                note = None
                if (
                    parsed.continues_previous
                    and previous
                    and parsed.locator
                    and not parsed.locator.lower().startswith("see ")
                ):
                    reference, note = previous, "continues the previous reference"
                    counts["literature: continuing the previous reference"] += 1
                insert(
                    conn,
                    "ro_object_sources",
                    item,
                    run_id,
                    object_id=object_id,
                    note=note,
                    source_reference=reference,
                    source_page_reference=parsed.locator,
                    source_note=parsed.note,
                    reference_text=clean(item.text),
                )
                counts["literature"] += 1
                counts["literature without a locator"] += parsed.locator is None
                counts["literature: cross-references within the volume"] += bool(
                    parsed.locator and parsed.locator.lower().startswith("see ")
                )
                previous = reference or previous
