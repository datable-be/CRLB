"""The RO value lists and the CRLB-to-RO mapping tables, read from the CSV files in vocabularies/.

The value lists (`object_names.csv`, `material_support.csv`, ...) are copied
from the RO data model; the mapping tables (`*_map.csv`) map a CRLB term to
the Dutch label of a value in one of those lists.
"""

import csv
import re
from functools import cache
from importlib.resources import files

VOCABULARY_DIR = files("crlb.extraction") / "vocabularies"

# Each mapping table and the value list its labels come from
MAPS = {
    "object_name_map": "object_names",
    "support_map": "material_support",
    "collection_type_map": "collection_type",
    "currency_map": "currencies",
    "transfer_method_map": "transfer_method",
}


@cache
def labels(name: str) -> frozenset[str]:
    """Return the Dutch labels of an RO value list."""
    with (VOCABULARY_DIR / f"{name}.csv").open(encoding="utf-8") as f:
        return frozenset(row["label_nl"] for row in csv.DictReader(f))


@cache
def mapping(name: str) -> dict[str, str]:
    """Return a mapping table as {CRLB term (lower case): RO label}."""
    with (VOCABULARY_DIR / f"{name}.csv").open(encoding="utf-8") as f:
        rows = list(csv.reader(f))[1:]
    return {term.lower(): label for term, label in rows}


def longest_keyword(text: str, name: str) -> str | None:
    """Return the label of the longest keyword of a mapping table found as a whole word in text (case-insensitive)."""
    lowered = text.lower()
    found = [
        term
        for term in mapping(name)
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", lowered)
    ]
    return mapping(name)[max(found, key=len)] if found else None
