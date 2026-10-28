"""The object core by rules: heading, material and dimensions, location, date and the copies of an entry.

The parse functions take the effective text of one field and return its
values verbatim, split into the RO properties; list values come from the
mapping tables in vocabularies/. Nothing is invented: what a rule does not
recognise stays empty and is counted.
"""

import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from crlb.extraction import dates, vocabularies
from crlb.extraction.source import Entry, Node, insert

# Leading catalogue number of a heading: 'No. 4.', '12c.', '12a', OCR 'lb .', 'l-5a.', '7dL'
HEADING_NUMBER = re.compile(
    r"^(?:No\.\s*)?(?:(?=[\w«~-]{0,4}\d)|(?=[lI]\w{0,3}\s?\.))[\w«~-]{1,6}\s?[.!]?\s*"
)
FIGURES = re.compile(r"\s*\(\s*figs?\b[^)]*\)", re.IGNORECASE)
TYPE_SEPARATOR = re.compile(r"\s*[:!]\s*(?=[^:!]*$)")
DIMENSIONS = re.compile(
    r"(?P<note>\b(?:c\.|ca\.|approximately|approx\.|appr\.)\s*)?"
    r"(?P<height>\d+(?:[.,]\d+)?)\s*(?:cm|mm)?\s*[×x:]\s*(?P<width>\d+(?:[.,]\d+)?)\s*(?P<unit>cm|mm)\b"
)
# 'Inv. no. 7442', also damaged by OCR: 'lnv. No.', 'Inv, No.', 'No, 267'
INVENTORY = re.compile(r"[.,;]?\s*\b(?:[il]nv[.,]?\s*no[.,]?|no[.,])\s*", re.IGNORECASE)
WHEREABOUTS = re.compile(r"\bwhereabouts unknown\b", re.IGNORECASE)
# 'presumably lost', also damaged by OCR: 'presumably loSt', 'loft', 'loH'
LOST = re.compile(
    r"\b(?:(?:presumably|probably)\s+)?(?:lost|destroyed|burnt|(?<=presumably )lo\S{1,2}\b)(?:\s+in\s+\d{4})?",
    re.IGNORECASE,
)
CAUSES = {"destroyed": "vernietigd", "burnt": "verbrand"}
COPY_MARKER = re.compile(r"^\(\s*\w{1,3}\s*\)\s*")
ATTRIBUTION = re.compile(
    r"(?<!edited )(?<!printed )(?<!published )(?<!retouched )"
    r"\b(?:(?P<qualifier>possibly|probably)\s+)?by\s+(?P<actor>[^,;()]+?)(?=\s+after\b|[,;()]|$)"
)
QUALIFIERS = {"possibly": "mogelijk van", "probably": "waarschijnlijk van"}
# Parts of a copy description that describe the copy, not where it is
COPY_DETAIL = re.compile(
    r"^(?:(?:and )?without|(?:and )?with|in reverse|after|(?:possibly |probably )?by|edited|printed|lettered|recto|verso"
    r"|possibly identical|inscribed|the composition|enlarged|cut)\b",
    re.IGNORECASE,
)
# Numbered fields: the noun of their objects, and the relation to the entry
NUMBERED = {
    "copies": ("Copy", "copy after"),
    "drawings": ("Drawing", "copy after"),
    "prints": ("Print", "copied in print by"),
}


@dataclass
class Heading:
    """The heading of an entry: title and object name, or a cross-reference."""

    title: str | None
    object_name_text: str | None
    cross_reference: str | None = None


@dataclass
class Dimensions:
    """Height and width with their unit, as written."""

    height: float
    width: float
    unit: str
    note: str | None
    text: str


@dataclass
class Material:
    """The material field: the material note, the support and the dimensions."""

    note: str | None
    support_label: str | None
    dimensions: Dimensions | None


@dataclass
class Location:
    """Where an object is: holder, place and inventory number, or lost."""

    holder: str | None
    place: str | None
    identifier: str | None
    collection_type: str | None
    destruction_text: str | None = None
    destruction_cause: str | None = None


@dataclass
class Attribution:
    """An attribution stated in the text."""

    text: str
    actor: str
    status: str


@dataclass
class CopyObject:
    """A copy, drawing or print: its object name, attribution, location and material."""

    object_name_text: str | None
    attribution: Attribution | None
    location: Location | None
    material: Material
    uncertain: bool = False
    details: list[str] = field(default_factory=list)


def split_spans(text: str, separator: str) -> list[tuple[int, int]]:
    """Return the (start, end) of the parts of text between separator characters outside brackets, without surrounding spaces."""
    spans, depth, start = [], 0, 0
    for k, char in enumerate(text + separator):
        if char in "([":
            depth += 1
        elif char in ")]" and depth > 0:
            depth -= 1
        elif char == separator and (depth == 0 or k == len(text)):
            part = text[start:k]
            left = start + len(part) - len(part.lstrip())
            spans.append((left, max(left, start + len(part.rstrip()))))
            start = k + 1
    return spans


def split_outside_brackets(text: str, separator: str) -> list[str]:
    """Split text at a separator character that is not inside brackets."""
    return [text[a:b] for a, b in split_spans(text, separator)]


def span_text(text: str, spans: list[tuple[int, int]]) -> str:
    """Return the text from the start of the first span to the end of the last, as written."""
    return text[spans[0][0] : spans[-1][1]]


def object_name_label(term: str | None) -> tuple[str | None, bool]:
    """Return the RO object name of a CRLB term, and whether it was matched only approximately (OCR)."""
    if not term:
        return None, False
    table = vocabularies.mapping("object_name_map")
    key = term.lower().strip()
    if key in table:
        return table[key], False
    found = process.extractOne(key, list(table), scorer=fuzz.ratio, score_cutoff=85)
    return (table[found[0]], True) if found else (None, False)


def parse_heading(text: str) -> Heading:
    """Return the title and object name of a heading such as 'No. 4. Study of two Heads: Painting (Fig. 12)'."""
    body = HEADING_NUMBER.sub("", text, count=1).strip()
    if body.lower().startswith("see "):
        return Heading(None, None, cross_reference=body)
    body = FIGURES.sub("", body).strip()
    parts = TYPE_SEPARATOR.split(body, maxsplit=1)
    if len(parts) == 2 and parts[1]:
        return Heading(parts[0].strip() or None, parts[1].strip())
    return Heading(body or None, None)


def parse_dimensions(text: str) -> Dimensions | None:
    """Return the first height × width in a text ('c. 68.5 × 52.5 cm', '63 : 89 cm'), if any."""
    match = DIMENSIONS.search(text)
    if match is None:
        return None
    note = match["note"].strip() if match["note"] else None
    return Dimensions(
        float(match["height"].replace(",", ".")),
        float(match["width"].replace(",", ".")),
        match["unit"],
        note,
        match.group(0).strip(),
    )


def parse_material(text: str) -> Material:
    """Return the material note, support and dimensions of a material text such as 'Oil on panel; 69.9 × 52.1 cm.'."""
    match = DIMENSIONS.search(text)
    dimensions = parse_dimensions(text)
    before = text[: match.start()] if match else text
    # The first sentence holds the material; inscriptions and remarks follow it
    first = split_outside_brackets(before, ";")[0]
    note = re.split(r"\.\s+(?=[A-Z])", first, maxsplit=1)[0].strip(" ;,.")
    return Material(
        note or None,
        vocabularies.longest_keyword(note, "support_map") if note else None,
        dimensions,
    )


def parse_location(text: str) -> Location:
    """Return holder, place and inventory number of a location such as 'New York, The Metropolitan Museum of Art. Inv. no. 67.87.99'."""
    text = text.strip(" ;,.")
    lost = LOST.search(text)
    if WHEREABOUTS.search(text) or (lost and lost.start() == 0):
        whereabouts = WHEREABOUTS.search(text)
        return Location(
            whereabouts.group(0) if whereabouts else None,
            None,
            None,
            None,
            lost.group(0) if lost else None,
            None if lost is None else cause(lost.group(0)),
        )
    found = INVENTORY.split(text, maxsplit=1)
    where, identifier = found[0], (found[1].strip(" .") if len(found) > 1 else None)
    spans = split_spans(where, ",")
    parts = [where[a:b] for a, b in spans]
    if len(parts) == 1:
        place, holder = None, parts[0]
    elif vocabularies.longest_keyword(parts[0], "collection_type_map") is None:
        # 'New York, The Metropolitan Museum of Art': the place comes first
        place, holder = parts[0], span_text(where, spans[1:])
    elif len(parts[-1].split()) <= 2 and not vocabularies.longest_keyword(
        parts[-1], "collection_type_map"
    ):
        # 'private collection, New York': the place comes last
        place, holder = parts[-1], span_text(where, spans[:-1])
    else:
        place, holder = None, where
    return Location(
        holder or None,
        place,
        identifier or None,
        vocabularies.longest_keyword(holder, "collection_type_map") if holder else None,
        # 'Formerly Brussels, Palace; destroyed by fire 1731'
        lost.group(0) if lost else None,
        cause(lost.group(0)) if lost else None,
    )


def cause(text: str) -> str:
    """Return the RO destruction cause of a text such as 'presumably lost' or 'destroyed in 1945'."""
    lowered = text.lower()
    return next((label for word, label in CAUSES.items() if word in lowered), "vermist")


def parse_attribution(text: str) -> Attribution | None:
    """Return the attribution in a copy description ('possibly by Anthony van Dyck'), if any."""
    match = ATTRIBUTION.search(text)
    if match is None:
        return None
    status = QUALIFIERS.get(match["qualifier"] or "", "huidig")
    return Attribution(match.group(0).strip(), match["actor"].strip(), status)


def parse_copy(text: str) -> CopyObject:
    """Return the parts of a copy description such as '(2) Drawing, by Lucas Vorsterman I, Vienna, Albertina, inv. no. 13294; pen and brown ink, 125 × 117 mm.'."""
    body = COPY_MARKER.sub("", text.strip(), count=1)
    uncertain = body.startswith("?")
    body = body.lstrip("?'. ").strip()
    pieces = split_spans(body, ";")
    identity = body[pieces[0][0] : pieces[0][1]]
    physical = span_text(body, pieces[1:]) if len(pieces) > 1 else ""
    described = FIGURES.sub("", identity)
    spans = [s for s in split_spans(described, ",") if s[1] > s[0]]
    parts = [described[a:b] for a, b in spans]
    head = parts[0] if parts else ""
    table = vocabularies.mapping("object_name_map")
    term = max((t for t in table if head.lower().startswith(t)), key=len, default=None)
    object_name_text = head[: len(term)] if term else None
    rest = list(zip(parts, spans))[1:] if term else list(zip(parts, spans))
    details = [p for p, _ in rest if COPY_DETAIL.match(p)]
    where = [
        span
        for p, span in rest
        if not (
            COPY_DETAIL.match(p)
            or DIMENSIONS.search(p)
            or p.startswith("(")
            or p.lower().startswith("see ")
        )
    ]
    location = parse_location(span_text(described, where)) if where else None
    return CopyObject(
        object_name_text,
        parse_attribution(identity),
        location,
        parse_material(physical)
        if physical
        else Material(None, None, parse_dimensions(body)),
        uncertain,
        details,
    )


def material_field(node: Node) -> Node | None:
    """Return the material field of an entry, unless it only says where the object is."""
    material = node.field("material")
    return None if material and WHEREABOUTS.match(material.text) else material


def entry_location(node: Node) -> tuple[Node, Location] | None:
    """Return the field with the location of an entry and its parsed location."""
    candidates = node.fields("location")
    material = node.field("material")
    # A material field that only says where the object is belongs to the location
    if material and WHEREABOUTS.match(material.text):
        candidates = [material, *candidates]
    return (candidates[-1], parse_location(candidates[-1].text)) if candidates else None


def copy_location(copy: Node) -> tuple[Node, Location] | None:
    """Return the field with the description of a copy and the location parsed from it."""
    node = copy.field("object") or copy
    location = parse_copy(node.text).location
    return (node, location) if location else None


def rkd_id(conn: sqlite3.Connection, link_id: int) -> str | None:
    """Return the RKD id from the URI of an RKD link ('https://rkd.nl/images/58171' -> '58171')."""
    row = conn.execute("SELECT uri FROM links WHERE id = ?", (link_id,)).fetchone()
    match = re.search(r"/images/(\d+)", row[0] or "") if row else None
    return match[1] if match else None


def insert_dimensions(
    conn: sqlite3.Connection, run_id: int, object_id: int, node: Node, dims: Dimensions
) -> None:
    """Store height and width of an object."""
    for kind, value in (("hoogte", dims.height), ("breedte", dims.width)):
        insert(
            conn,
            "ro_dimensions",
            node,
            run_id,
            object_id=object_id,
            dimension_value=value,
            dimension_unit_label=dims.unit,
            dimension_type_label=kind,
            dimension_note=dims.note,
            dimensions_text=dims.text,
        )


def insert_identifiers(
    conn: sqlite3.Connection,
    run_id: int,
    object_id: int,
    node: Node,
    crlb_identifier: str,
    link_id: int | None,
) -> bool:
    """Store the CRLB number and, if there is an RKD link, the RKD id of an object; return whether it has an RKD id."""
    insert(
        conn,
        "ro_object_identifiers",
        node,
        run_id,
        object_id=object_id,
        object_identifier=crlb_identifier,
        object_identifier_type_label="CRLB nummer",
    )
    rkd = rkd_id(conn, link_id) if link_id else None
    if rkd:
        insert(
            conn,
            "ro_object_identifiers",
            node,
            run_id,
            object_id=object_id,
            object_identifier=rkd,
            object_identifier_type_label="RKD ID",
            link_id=link_id,
        )
    return rkd is not None


def extract_entry(
    conn: sqlite3.Connection, run_id: int, entry: Entry, counts: Counter[str]
) -> None:
    """Store the object of an entry, its copies and their identifiers, dimensions, attributions and relations."""
    node = entry.node
    heading_node = node.field("heading") or node
    heading = parse_heading(heading_node.text)
    name_label, approximate = object_name_label(heading.object_name_text)
    material_node = material_field(node)
    material = parse_material(material_node.text) if material_node else None
    found = entry_location(node)
    location = found[1] if found else None
    date_node = node.field("date")
    date = dates.parse_date(date_node.text) if date_node else None
    object_id = insert(
        conn,
        "ro_objects",
        node,
        run_id,
        note="object name matched approximately (OCR)" if approximate else None,
        part=entry.part,
        crlb_number=entry.number,
        title_value=heading.title,
        title_type_label="titel" if heading.title else None,
        object_name_label=name_label,
        object_name_text=heading.object_name_text,
        production_date_label=date_node.text.strip(" .") if date_node else None,
        production_date_start=date.start if date else None,
        production_date_end=date.end if date else None,
        material_note=material.note if material else None,
        material_support_label=material.support_label if material else None,
        destruction_cause=location.destruction_cause if location else None,
        destruction_text=location.destruction_text if location else None,
    )
    counts["objects: entries"] += 1
    counts["entries with an RKD id"] += insert_identifiers(
        conn,
        run_id,
        object_id,
        heading_node,
        f"{entry.part}, No. {entry.number}",
        node.link_id,
    )
    counts_core(counts, "entries", heading, name_label, material, date_node, date)
    if material and material.dimensions and material_node:
        insert_dimensions(conn, run_id, object_id, material_node, material.dimensions)
    if heading.cross_reference:
        insert(
            conn,
            "ro_related_objects",
            heading_node,
            run_id,
            object_id=object_id,
            related_object_artistic_relation_type="related to",
            relation_text=heading.cross_reference,
        )
        counts["entries that are a cross-reference"] += 1
    for label, (noun, relation) in NUMBERED.items():
        for numbered in node.fields(label):
            for copy in (c for c in numbered.children if c.kind == "copy"):
                extract_copy(
                    conn, run_id, entry, object_id, copy, noun, relation, counts
                )


def counts_core(
    counts: Counter[str],
    kind: str,
    heading: Heading | None,
    name_label: str | None,
    material: Material | None,
    date_node: Node | None,
    date: dates.DateRange | None,
) -> None:
    """Count the core values that rules found or could not parse."""
    if heading is not None and heading.object_name_text and not name_label:
        counts[f"{kind}: object name not in the mapping table"] += 1
    if material is not None and material.dimensions is None:
        counts[f"{kind}: material without parsed dimensions"] += 1
    if material is not None and material.note and not material.support_label:
        counts[f"{kind}: material without a mapped support"] += 1
    if date_node is not None and date is None:
        counts[f"{kind}: date not parsed"] += 1


def extract_copy(
    conn: sqlite3.Connection,
    run_id: int,
    entry: Entry,
    entry_object_id: int,
    copy: Node,
    noun: str,
    relation: str,
    counts: Counter[str],
) -> None:
    """Store a copy, drawing or print as its own object, related to the entry."""
    object_node = copy.field("object") or copy
    parsed = parse_copy(object_node.text)
    name_label, approximate = object_name_label(parsed.object_name_text)
    number = (copy.label or "").strip("() ")
    location = parsed.location
    notes = [
        n
        for n in (
            "uncertain copy ('?')" if parsed.uncertain else None,
            "object name matched approximately (OCR)" if approximate else None,
        )
        if n
    ]
    object_id = insert(
        conn,
        "ro_objects",
        copy,
        run_id,
        note="; ".join(notes) or None,
        part=entry.part,
        crlb_number=f"{entry.number}, {noun} {number}",
        object_name_label=name_label,
        object_name_text=parsed.object_name_text,
        material_note=parsed.material.note,
        material_support_label=parsed.material.support_label,
        destruction_cause=location.destruction_cause if location else None,
        destruction_text=location.destruction_text if location else None,
    )
    counts[f"objects: {noun.lower()}"] += 1
    counts["copies with an RKD id"] += insert_identifiers(
        conn,
        run_id,
        object_id,
        object_node,
        f"{entry.part}, No. {entry.number}, {noun} {number}",
        copy.link_id,
    )
    heading = Heading(None, parsed.object_name_text)
    counts_core(counts, "copies", heading, name_label, parsed.material, None, None)
    if parsed.object_name_text is None:
        counts["copies: object name not recognised"] += 1
    if parsed.material.dimensions:
        insert_dimensions(
            conn, run_id, object_id, object_node, parsed.material.dimensions
        )
    if parsed.attribution:
        insert(
            conn,
            "ro_attributions",
            object_node,
            run_id,
            object_id=object_id,
            production_attribution_status=parsed.attribution.status,
            production_actor_label=parsed.attribution.actor,
            attribution_text=parsed.attribution.text,
            is_current=1,
        )
        counts["copies with an attribution"] += 1
    # A copy is a copy after the entry; a print copies the entry
    source, target = (
        (entry_object_id, object_id)
        if relation == "copied in print by"
        else (object_id, entry_object_id)
    )
    insert(
        conn,
        "ro_related_objects",
        copy,
        run_id,
        object_id=source,
        related_object_id=target,
        related_object_artistic_relation_type=relation,
    )
