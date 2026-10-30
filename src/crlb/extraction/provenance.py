"""Provenance by rules: the fixed forms of a provenance stage, and the chain of collection stays and auctions.

Rules recognise the frequent forms:

- a sale: `[holder,] [his|her] sale, Place (House), date, lot n (note), sold for 260 florins to Buyer`;
- a holder: `[probably] Holder [(life dates)], Place[, date]`, also `with the dealer Holder, ...`;
- a buyer: `sold to Holder`, `purchased by Holder`;
- the last stage into the current location: `by whom bequeathed to the museum`.

Every other stage is left for the LLM (step 4, part 2); its position in the
chain is kept. Dates are parsed by `dates.parse_date`. The chain adds the
current location as the last collection stay, takes the consignor of `his sale`
from the previous stage and the removal date of a stay from the next stage
(both marked as derived).
"""

import itertools
import re
import sqlite3
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from crlb.extraction import dates, vocabularies
from crlb.extraction.dates import DASH, MONTH
from crlb.extraction.objects import (
    Location,
    copy_location,
    entry_location,
    split_outside_brackets,
)
from crlb.extraction.references import object_nodes, split_note
from crlb.extraction.source import Entry, Node, insert

UNCERTAIN = re.compile(r"^(?:\?\s*|(?:probably|possibly|perhaps)\s+)", re.IGNORECASE)
# A note number after the final punctuation: 'In the collections ever since.1'
NOTE_MARKER = re.compile(r"(?<=[.;,)])\d{1,2}$")
SALE = re.compile(
    r"^(?:(?P<consignor>.+?)[,\s]\s*)??(?P<label>(?:(?:his|her|their)\s+)?sale)\b,?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
LOT = re.compile(r"^(?:lot|no\.)\s*(?P<lot>.+)$", re.IGNORECASE)
PRICE = re.compile(
    r"\bfor\s+(?P<amount>£\s*[\d.,]+|[\d.,]+)\s*(?P<currency>[A-Za-z]+)?", re.IGNORECASE
)
BUYER = re.compile(
    r"\b(?:sold|bought|purchased)\b(?:\s+for\s+[^,;()]+?)?\s+(?:to|by)\s+(?P<buyer>[^,;()]+)"
    r"|\(to\s+(?P<buyer2>[^()]+)\)",
    re.IGNORECASE,
)
# 'with the dealer X', 'with X': in the CRLB both name a dealer
DEALER = re.compile(r"^with (?:the )?(?:(?:art )?dealers?\s+)?", re.IGNORECASE)
BUYER_STAGE = re.compile(
    r"^(?P<verb>sold|purchased|bought|acquired|inherited)\s+(?:to|by)\s+(?P<rest>.+)$",
    re.IGNORECASE,
)
TO_CURRENT = re.compile(
    r"^(?:by whom |where |whence |hence |and )?\w+\b.*\b(?:to|by) the museum$",
    re.IGNORECASE,
)
# Words that make a stage more than a holder with place and date
VERBS = re.compile(
    r"\b(?:acquired|purchased|purchase|bought|sold|bequeathed|bequest|gift|given|presented|inherited|brought|mentioned|saved"
    r"|deposited|held|according|identical|transferred|seen|recorded|lent|loan|exhibited|offered"
    r"|returned|confiscated|stolen|integrated|said|until|since|from|whom|where|when|hence|thence"
    r"|then|after|before|by|as|in|on|at|sale|unknown)\b",
    re.IGNORECASE,
)
DATE_PART = re.compile(
    rf"^\(?\s*(?:(?:before|by|until|in|since|after|c\.|as of)\s+)*(?:\d{{1,2}}\s+)?(?:{MONTH}\s+)?"
    rf"\d{{4}}(?:{DASH}\d{{2,4}})?\s*\)?\s*\??$",
    re.IGNORECASE,
)
PLACE = re.compile(
    r"^[A-Z’'][\w’'.-]*(?:\s+(?:[A-Z(][\w’'.()-]*|de|di|du|van|von|am|an|der|la|le|sur|upon|on))*$"
)


@dataclass
class Stage:
    """One provenance stage as parsed by rules: a collection stay or an auction."""

    kind: (
        str  # 'collection', 'auction' or 'current' (the move into the current location)
    )
    uncertain: bool = False
    holder: str | None = None
    place: str | None = None
    date_text: str | None = None
    entry_method: str | None = None
    collection_type: str | None = None
    label: str | None = None
    organiser: str | None = None
    lot: str | None = None
    consignor: str | None = None
    buyer: str | None = None
    price_amount: str | None = None
    currency: str | None = None
    notes: list[str] = field(default_factory=list)

    def date(self) -> dates.DateRange | None:
        """Return the parsed date of the stage."""
        return dates.parse_date(self.date_text) if self.date_text else None


def clean(text: str) -> str:
    """Return a stage without its final punctuation and note number."""
    return NOTE_MARKER.sub("", text.strip()).strip().rstrip(";,.").strip()


def is_date(text: str) -> bool:
    """Return whether a part of a stage is only a date ('1925-26', 'before 1956', '(December 1934)')."""
    return bool(DATE_PART.match(text)) and dates.parse_date(text) is not None


def parse_sale(match: re.Match[str], uncertain: bool) -> Stage:
    """Return an auction stage from a match of SALE."""
    consignor = (match["consignor"] or "").strip(" ,") or None
    stage = Stage("auction", uncertain, label=match["label"], consignor=consignor)
    rest = match["rest"]
    parts = [p for p in split_outside_brackets(rest, ",") if p]
    # 'sale of the Van Leyden collection, Amsterdam, ...'
    if parts and parts[0].lower().startswith("of "):
        stage.label = f"{stage.label} {parts.pop(0)}"
    if parts and not dates.parse_date(parts[0]):
        where = parts.pop(0)
        body, inside = split_note(where)
        # 'London (Christie’s)', but also 'Christie’s (London)'
        if inside and re.search(r"[’']s$", body):
            body, inside = inside, body
        stage.place, stage.organiser = body or None, inside
    for part in parts:
        body, note = split_note(part)
        if stage.date_text is None and dates.parse_date(body):
            stage.date_text = body
        elif stage.lot is None and (lot := LOT.match(body)):
            stage.lot = lot["lot"].strip()
        else:
            stage.notes.append(body)
            continue
        if note:
            stage.notes.append(note)
    price = PRICE.search(rest)
    if price:
        amount = price["amount"]
        currency_word = "£" if amount.startswith("£") else (price["currency"] or "")
        stage.price_amount = amount.lstrip("£ ")
        stage.currency = vocabularies.mapping("currency_map").get(currency_word.lower())
    buyer = BUYER.search(rest)
    if buyer:
        stage.buyer = (buyer["buyer"] or buyer["buyer2"]).strip()
    return stage


def parse_holder(
    text: str, uncertain: bool, kind_hint: str | None = None
) -> Stage | None:
    """Return a collection stay 'Holder, Place[, date]', or None if the text is not of that form."""
    parts = split_outside_brackets(text, ",")
    if not 1 <= len(parts) <= 3:
        return None
    holder, note = split_note(parts[0])
    if note and re.search(r"\d{4}", note) and not re.search(r"[A-Za-z]{3}", note):
        holder, note = parts[0], None  # life dates stay with the holder
    if ";" in holder:
        return None
    # A holder is a name ('baron Ferdinand du Bois') or a kind of collection ('private collection')
    if not re.search(r"[A-Z]", holder) and not vocabularies.longest_keyword(
        holder, "collection_type_map"
    ):
        return None
    if VERBS.search(re.sub(r"\([^()]*\)", "", holder)) or re.search(
        r"\d{4}", re.sub(r"\([^()]*\)", "", holder)
    ):
        return None
    stage = Stage("collection", uncertain, holder=holder)
    if note and is_date(note):
        stage.date_text = note  # 'baron Ferdinand du Bois (1767–1848) (until 1828)'
    elif note:
        stage.notes.append(note)
    for part in parts[1:]:
        body, inner = split_note(part)
        if is_date(part):
            stage.date_text = part.strip("() ")
        elif (
            stage.place is None
            and PLACE.match(body)
            and (inner is None or is_date(inner))
        ):
            stage.place = body
            if inner:
                stage.date_text = inner
        else:
            return None
    stage.collection_type = kind_hint or vocabularies.longest_keyword(
        holder, "collection_type_map"
    )
    return stage


def parse_stage(text: str) -> Stage | None:
    """Return a provenance stage parsed by rules, or None if it is not one of the fixed forms."""
    body = clean(text)
    uncertain = False
    while match := UNCERTAIN.match(body):
        uncertain = True
        body = body[match.end() :]
    if body.endswith("?"):
        uncertain, body = True, body.rstrip(" ?")
    if not body:
        return None
    sale = SALE.match(body)
    if sale and not re.search(r"\b(?:for|at|in|the|a)$", sale["consignor"] or ""):
        return parse_sale(sale, uncertain)
    if TO_CURRENT.match(body) and len(body.split()) <= 8:
        method = next(
            (
                label
                for term, label in vocabularies.mapping("transfer_method_map").items()
                if re.search(rf"\b{term}\b", body, re.IGNORECASE)
            ),
            None,
        )
        return Stage("current", uncertain, entry_method=method, notes=[body])
    if dealer := DEALER.match(body):
        return parse_holder(body[dealer.end() :], uncertain, "kunsthandel")
    if buyer := BUYER_STAGE.match(body):
        stage = parse_holder(buyer["rest"], uncertain)
        if stage:
            stage.entry_method = vocabularies.mapping("transfer_method_map").get(
                buyer["verb"].lower()
            )
        return stage
    return parse_holder(body, uncertain)


@dataclass
class ChainRow:
    """A stage placed in the chain: its position, source node and the values derived from its neighbours."""

    position: int
    node: Node
    stage: Stage | None  # None: left for the LLM, or no holder or sale
    method: str = "rules"
    removal_date: str | None = None
    removal_derived: bool = False
    consignor_derived: bool = False
    is_current: bool = False
    location: Location | None = None


def stage_start(stage: Stage | None) -> str | None:
    """Return the start date of a stage, for the removal date of the stay before it."""
    if stage is None or stage.kind == "current":
        return None
    date = stage.date()
    return date.start if date else None


def build_chain(
    items: list[Node],
    current: tuple[Node, Location] | None,
    model: Callable[[int], Stage | None] | None = None,
) -> list[ChainRow]:
    """Return the chain of an object: its provenance items in order, then the current location.

    Rules parse each stage; with a model, the stages that rules leave are given
    to model(index of the item), before the values derived from neighbours.
    """
    rows = [
        ChainRow(i + 1, item, parse_stage(item.text)) for i, item in enumerate(items)
    ]
    # The move into the current location is only recognised as the last stage
    for row in rows[:-1]:
        if row.stage and row.stage.kind == "current":
            row.stage = None
    if model is not None:
        for i, row in enumerate(rows):
            if row.stage is None:
                row.stage, row.method = model(i), "llm"
    merged = (
        rows[-1].stage
        if rows and rows[-1].stage and rows[-1].stage.kind == "current"
        else None
    )
    if merged:
        rows.pop()
    if current is not None and current[1].holder:
        rows.append(
            ChainRow(
                len(rows) + 1, current[0], merged, is_current=True, location=current[1]
            )
        )
    for previous, row in itertools.pairwise(rows):
        stage = row.stage
        if (
            stage
            and stage.kind == "auction"
            and stage.consignor is None
            and stage.label
            and stage.label.lower() != "sale"
            and previous.stage
            and previous.stage.kind == "collection"
        ):
            stage.consignor = previous.stage.holder
            row.consignor_derived = True
    for row, following in itertools.pairwise(rows):
        if row.stage and row.stage.kind == "collection":
            date = row.stage.date()
            if date and date.end and date.end != date.start:
                row.removal_date = date.end
            elif (start := stage_start(following.stage)) is not None:
                row.removal_date, row.removal_derived = start, True
    return rows


def insert_row(
    conn: sqlite3.Connection, run_id: int, object_id: int, row: ChainRow
) -> None:
    """Store one row of the chain as a collection stay or an auction."""
    stage = row.stage
    assert stage is not None or row.is_current
    if row.is_current:
        location = row.location
        assert location is not None
        insert(
            conn,
            "ro_collection_stays",
            row.node,
            run_id,
            object_id=object_id,
            note="the last provenance stage is merged into the current location"
            if stage
            else None,
            method=row.method,
            position=row.position,
            holder_text=location.holder,
            collection_type_label=location.collection_type,
            collection_place_label=location.place,
            collection_identifier=location.identifier,
            collection_entry_method=stage.entry_method if stage else None,
            collection_entry_note="; ".join(stage.notes) if stage else None,
            collection_is_current=1,
        )
        return
    assert stage is not None
    date = stage.date()
    if stage.kind == "auction":
        insert(
            conn,
            "ro_auctions",
            row.node,
            run_id,
            object_id=object_id,
            method=row.method,
            position=row.position,
            auction_label=stage.label,
            auction_organizer_label=stage.organiser,
            auction_place_label=stage.place,
            auction_date_start=date.start if date else None,
            auction_date_end=date.end if date else None,
            auction_date_text=stage.date_text,
            auction_lot_number=stage.lot,
            auction_consignor=stage.consignor,
            auction_consignor_derived=int(row.consignor_derived),
            auction_buyer=stage.buyer,
            auction_price_amount=stage.price_amount,
            auction_price_currency=stage.currency,
            auction_note="; ".join(stage.notes) or None,
            uncertain=int(stage.uncertain),
        )
        return
    until = bool(stage.date_text and stage.date_text.lower().startswith("until"))
    insert(
        conn,
        "ro_collection_stays",
        row.node,
        run_id,
        object_id=object_id,
        method=row.method,
        position=row.position,
        holder_text=stage.holder,
        collection_type_label=stage.collection_type,
        collection_place_label=stage.place,
        collection_entry_date=None if until or date is None else date.start,
        collection_entry_date_text=stage.date_text,
        collection_entry_method=stage.entry_method,
        collection_entry_note="; ".join(stage.notes) or None,
        collection_removal_date=row.removal_date,
        collection_removal_derived=int(row.removal_derived),
        collection_is_current=0,
        uncertain=int(stage.uncertain),
    )


def extract_entry(
    conn: sqlite3.Connection,
    run_id: int,
    entry: Entry,
    object_ids: dict[int, int],
    counts: Counter[str],
    model: Callable[[list[Node], int], Stage | None] | None = None,
) -> None:
    """Store the provenance chains of an entry and its copies.

    Without a model, the stages that rules leave are only counted; with one,
    model(items, index) gives their stage.
    """
    for owner in object_nodes(entry):
        items = [
            item
            for provenance in owner.fields("provenance")
            for item in provenance.children
            if item.kind == "item"
        ]
        current = entry_location(owner) if owner is entry.node else copy_location(owner)
        ask = None if model is None else (lambda i, items=items: model(items, i))
        for row in build_chain(items, current, ask):
            if row.stage is None and not row.is_current:
                counts[
                    "provenance: stages left for the LLM"
                    if model is None
                    else "provenance: stages without a row (no holder or sale, or answer rejected)"
                ] += 1
                continue
            insert_row(conn, run_id, object_ids[owner.id], row)
            if row.is_current:
                counts["provenance: current locations"] += 1
                counts["provenance: last stage merged into the current location"] += (
                    row.stage is not None
                )
            else:
                assert row.stage is not None
                by = "rules" if row.method == "rules" else "the LLM"
                counts[f"provenance: {row.stage.kind} stages by {by}"] += 1
                counts["provenance: removal dates derived from the next stage"] += (
                    row.removal_derived
                )
                counts["provenance: consignors taken from the previous stage"] += (
                    row.consignor_derived
                )
                if row.stage.date_text and row.stage.date() is None:
                    counts["provenance: dates not parsed"] += 1
        counts["provenance: stages"] += len(items)
