"""The RKD entry instructions that 5b applies by rules, each with the section of the RKD manual it implements.

The manual is `doc/project/Handleiding_RKDdatabases (15).pdf`; the sections
are those of the English part (RKDimages (EN), Screen 6: Herkomst 1). A rule
formats a value the way RKD would enter it where no control-list term is
found; a matched RKD term always takes precedence over the formatted value.

Only the rules the POC values need are implemented. Inventory numbers and lot
numbers are already written without 'inv. no.' and 'lot' by step 4.
"""

import re
import unicodedata
from dataclasses import dataclass

from crlb.extraction.objects import PERSON_PARTICLE, PERSON_STRONG, names_institution

MANUAL = "RKD manual, RKDimages (EN), Screen 6: Herkomst 1, Name of collection"

PARTICLES = {
    "van", "von", "de", "De", "den", "der", "du", "le", "la", "di", "da", "del", "della",
    "des", "ter", "ten", "te", "zu", "y", "d’", "d'", "'t",
}  # fmt: skip
# Titles of nobility follow the first names in RKD ('Vinck de Wesel, Jean François baron')
NOBLE = {
    "baron", "baroness", "count", "countess", "comte", "comtesse", "graf", "gräfin", "duke",
    "duchess", "marquis", "marquess", "prince", "princess", "earl", "lord", "lady",
}  # fmt: skip
# Forms of address go in brackets after the name ('Rothmann, Fritz (dr.)')
ADDRESS = {
    "sir",
    "dr",
    "dr.",
    "mr",
    "mr.",
    "mrs",
    "mrs.",
    "mme",
    "mlle",
    "madame",
    "monsieur",
    "frau",
    "herr",
    "mevrouw",
}
# Words that name a building or an institution, besides those of step 4
BUILDING = re.compile(
    r"\b(?:casa|museo|mus[eé]e|museum|gallery|galleries|galerie|iglesia|[eé]glise|royal|national|reale?)\b",
    re.IGNORECASE,
)
LIFE_DATES = re.compile(r"\s*\(\s*(?:c\.\s*)?\d{3,4}\s*[–\-]\s*(?:c\.\s*)?\d{3,4}\s*\)")
# Unnamed owners and an unknown location, as RKD enters them (manual, items 4 and 6)
UNNAMED = {
    "private collection": "Private collection",
    "art market": "Art dealer",
    "art dealer": "Art dealer",
    "dealer": "Art dealer",
    "whereabouts unknown": "Whereabouts unknown",
}


@dataclass(frozen=True)
class Formatted:
    """A value formatted by an entry instruction, with the rule that did it."""

    value: str
    rule: str | None  # None: unchanged


def strip_life_dates(text: str) -> str:
    """Remove life dates in brackets from a name ('(1747–1811)')."""
    return LIFE_DATES.sub("", text).strip()


def is_person(text: str) -> bool:
    """Return whether a holder is a named person: two or more name words, no institution, not two people."""
    words = text.split()
    return (
        len(words) >= 2
        and not names_institution(text)
        and not BUILDING.search(text)
        and not re.search(r"\band\b|&|,", text)
        and (
            bool(PERSON_STRONG.match(text) or PERSON_PARTICLE.match(text))
            or all(w[:1].isupper() or w in PARTICLES for w in words)
        )
    )


def last_first(name: str) -> str:
    """Return a personal name as 'Last, First particles title' ('Frans van den Hecke' -> 'Hecke, Frans van den')."""
    words = name.split()
    address = [w for w in words if w.lower() in ADDRESS]
    noble = [w for w in words if w.lower() in NOBLE]
    words = [w for w in words if w not in address and w not in noble]
    if len(words) == 1 and address:
        return f"{words[0]} ({' '.join(a.rstrip('.') for a in address)})"
    if len(words) < 2:
        return name
    start = next((k for k, w in enumerate(words) if k > 0 and w in PARTICLES), None)
    if start is None:
        first, particles, last = words[:-1], [], words[-1:]
    else:
        end = start
        while end < len(words) - 1 and words[end] in PARTICLES:
            end += 1
        first, particles, last = words[:start], words[start:end], words[end:]
    result = f"{' '.join(last)}, {' '.join(first + particles + noble)}"
    if address:
        result += f" ({' '.join(a.rstrip('.') for a in address)})"
    return result


def format_holder(text: str) -> Formatted:
    """Format a holder: an unnamed owner as the RKD term, a named person as 'Last, First'."""
    plain = strip_life_dates(text)
    for prefix, term in UNNAMED.items():
        if plain.lower() == prefix or plain.lower().startswith(prefix + " "):
            return Formatted(term, f"unnamed owner ({MANUAL}, items 4 and 6)")
    if is_person(plain) or (
        len(plain.split()) == 2 and plain.split()[0].lower() in ADDRESS
    ):
        formatted = last_first(plain)
        if formatted != text:
            return Formatted(
                formatted, f"personal name as 'Last, First' ({MANUAL}, item 3)"
            )
    if plain != text:
        return Formatted(plain, f"life dates left out ({MANUAL})")
    return Formatted(text, None)


def simplify(text: str) -> str:
    """Return a form for comparison: no accents, case, punctuation, life dates or leading article."""
    text = strip_life_dates(text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"^(?:the|le|la|les|het|de)\s+|\s+(?:the|le|la)$", "", text.strip())
    return " ".join(text.split())
