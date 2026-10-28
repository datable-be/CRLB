"""The per-volume segmentation configuration: one TOML file per CRLB part, on top of shared defaults.

The files live in `data_manifest/segmentation/` (in git): `defaults.toml` and
one file per part, which names its `part` and overrides any default key.
"""

import hashlib
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULTS = "defaults.toml"


@dataclass(frozen=True)
class Band:
    """A furniture band: lines entirely inside it, within the size range, are page furniture."""

    label: str  # 'running_head', 'page_number', ...
    top: float  # fraction of the page height
    bottom: float
    min_size: float = 0.0
    max_size: float = 1000.0


@dataclass(frozen=True)
class Fields:
    """How the fields, copies, notes and items of an entry are found."""

    labels: dict[
        str, list[str]
    ]  # field name -> labels, compared without spaces, casefolded
    separator: re.Pattern[str]  # what may follow a label
    date: re.Pattern[str]
    heading_bold_lines: bool  # the heading continues over the following bold lines
    description_new_block: (
        bool  # the description starts at a new block after a full stop
    )
    description_min_size: float | None  # the description is set in at least this size
    notes_max_size: float
    note_number: re.Pattern[str]
    item_fields: list[str]
    numbered_fields: list[
        str
    ]  # fields that list works as "(1) ..., (2) ...": copies, prints, drawings
    copy_marker: re.Pattern[str]
    copy_labels: dict[str, list[str]]


@dataclass(frozen=True)
class Config:
    """The segmentation configuration of one part."""

    part: str
    path: str  # the volume file, for provenance
    sha256: str  # of defaults and volume file together
    furniture: list[Band]
    link_tool_fonts: list[str]
    section_source: str  # 'bookmarks' or 'running_heads'
    section_level: int  # bookmark levels that start a section
    head_name: re.Pattern[str]  # section name from a running head
    section_names: dict[str, re.Pattern[str]]  # normalised name -> pattern on the title
    heading: re.Pattern[str]  # entry heading on a visual line, with group 'number'
    heading_with_link: (
        re.Pattern[str] | None
    )  # weaker pattern, accepted with an RKD link on the line
    heading_damaged_with_link: (
        re.Pattern[str] | None
    )  # title pattern with an unreadable number, accepted with an RKD link
    heading_bold: bool
    heading_min_size: float
    heading_max_size: float
    number: re.Pattern[str]  # entry number, with groups 'prefix', 'digits', 'letter'
    prefixes: list[str]
    fields: Fields


def merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge override into base: nested tables are merged, other values replaced."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result


def parse(raw: dict[str, Any], path: str, sha256: str) -> Config:
    """Turn a merged configuration table into a Config."""
    sections = raw.get("sections", {})
    heading = raw["heading"]
    with_link = heading.get("pattern_with_link")
    damaged = heading.get("pattern_damaged_with_link")
    fields = raw.get("fields", {})
    copies = raw.get("copies", {})
    return Config(
        part=raw["part"],
        path=path,
        sha256=sha256,
        furniture=[Band(**band) for band in raw.get("furniture", [])],
        link_tool_fonts=raw.get("link_tool_fonts", []),
        section_source=sections.get("source", "bookmarks"),
        section_level=sections.get("level", 1),
        head_name=re.compile(sections.get("head_name", "^(.*)$")),
        section_names={
            k: re.compile(v, re.IGNORECASE)
            for k, v in sections.get("names", {}).items()
        },
        heading=re.compile(heading["pattern"]),
        heading_with_link=re.compile(with_link) if with_link else None,
        heading_damaged_with_link=re.compile(damaged) if damaged else None,
        heading_bold=heading.get("bold", False),
        heading_min_size=heading.get("min_size", 0.0),
        heading_max_size=heading.get("max_size", 1000.0),
        number=re.compile(heading["number"]),
        prefixes=heading.get("prefixes", [""]),
        fields=Fields(
            labels=fields.get("labels", {}),
            separator=re.compile(fields.get("separator", ":")),
            date=re.compile(fields.get("date", "$^")),
            heading_bold_lines=fields.get("heading_bold_lines", False),
            description_new_block=fields.get("description_new_block", False),
            description_min_size=fields.get("description_min_size"),
            notes_max_size=fields.get("notes_max_size", 0.0),
            note_number=re.compile(fields.get("note_number", "$^")),
            item_fields=fields.get("item_fields", []),
            numbered_fields=fields.get("numbered_fields", []),
            copy_marker=re.compile(copies.get("marker", "$^")),
            copy_labels=copies.get("labels", {}),
        ),
    )


def load_configs(directory: Path) -> dict[str, Config]:
    """Load every volume configuration in a directory, keyed by part."""
    defaults_bytes = (directory / DEFAULTS).read_bytes()
    defaults = tomllib.loads(defaults_bytes.decode("utf-8"))
    configs = {}
    for path in sorted(directory.glob("*.toml")):
        if path.name == DEFAULTS:
            continue
        data = path.read_bytes()
        config = parse(
            merge(defaults, tomllib.loads(data.decode("utf-8"))),
            path.as_posix(),
            hashlib.sha256(defaults_bytes + data).hexdigest(),
        )
        if config.part in configs:
            raise SystemExit(f"two configuration files for part {config.part}")
        configs[config.part] = config
    return configs
