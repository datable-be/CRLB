"""Reading and checking the manifests: documents.csv (one row per PDF) and parts.csv (one row per CRLB part).

The manifests are written by hand and kept in git; they contain paths and
metadata only, no CRLB text. The selection of PDFs to build is the manifest
itself: a document not listed is not built.
"""

import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

DOCUMENT_FIELDS = [
    "path",
    "part",
    "volume",
    "section",
    "text_source",
    "excerpt_of",
    "note",
]
PART_FIELDS = ["part", "title", "year", "authors"]
SECTIONS = {"main", "index"}
TEXT_SOURCES = {"ocr", "born_digital"}


@dataclass(frozen=True)
class DocumentRow:
    """One PDF file, as described in documents.csv."""

    path: str
    part: str
    volume: str | None
    section: str
    text_source: str
    excerpt_of: str | None
    note: str | None


@dataclass(frozen=True)
class PartRow:
    """One CRLB part, as described in parts.csv."""

    part: str
    title: str | None
    year: int | None
    authors: str | None


def read_csv(path: Path, fields: list[str]) -> list[dict[str, str | None]]:
    """Read a manifest CSV with exactly the given columns; empty cells become None."""
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != fields:
            raise SystemExit(
                f"{path}: expected columns {fields}, got {reader.fieldnames}"
            )
        return [{k: (v.strip() or None) for k, v in row.items()} for row in reader]


def read_documents(path: Path) -> list[DocumentRow]:
    """Read documents.csv."""
    return [
        DocumentRow(
            path=row["path"] or "",
            part=row["part"] or "",
            volume=row["volume"],
            section=row["section"] or "",
            text_source=row["text_source"] or "",
            excerpt_of=row["excerpt_of"],
            note=row["note"],
        )
        for row in read_csv(path, DOCUMENT_FIELDS)
    ]


def read_parts(path: Path) -> list[PartRow]:
    """Read parts.csv."""
    rows = read_csv(path, PART_FIELDS)
    return [
        PartRow(
            part=row["part"] or "",
            title=row["title"],
            year=int(row["year"]) if row["year"] else None,
            authors=row["authors"],
        )
        for row in rows
    ]


def validate(
    documents: list[DocumentRow], parts: list[PartRow], root: Path
) -> list[str]:
    """Return the problems in the manifests; an empty list means they can be built."""
    problems = []
    known_parts = {p.part for p in parts}
    paths = Counter(d.path for d in documents)
    problems += [f"{path}: listed {n} times" for path, n in paths.items() if n > 1]
    problems += [
        f"part {p}: listed more than once in parts.csv"
        for p, n in Counter(p.part for p in parts).items()
        if n > 1
    ]
    for d in documents:
        if not (root / d.path).is_file():
            problems.append(f"{d.path}: file not found")
        if d.part not in known_parts:
            problems.append(f"{d.path}: part {d.part!r} is not in parts.csv")
        if d.section not in SECTIONS:
            problems.append(
                f"{d.path}: section {d.section!r} is not one of {sorted(SECTIONS)}"
            )
        if d.text_source not in TEXT_SOURCES:
            problems.append(
                f"{d.path}: text_source {d.text_source!r} is not one of {sorted(TEXT_SOURCES)}"
            )
        if d.excerpt_of is not None and (
            d.excerpt_of not in paths or d.excerpt_of == d.path
        ):
            problems.append(f"{d.path}: excerpt_of {d.excerpt_of!r} is not another row")
    return problems
