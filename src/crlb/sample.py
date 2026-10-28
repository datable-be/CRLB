"""The --sample option: restrict a command to some CRLB parts or catalogue entries.

A sample is a `;`-separated list of items, each a part with an optional
catalogue number: `"XIX (4)/22;II (1)"`. A part alone means the whole part.
Each step maps the sample to its own unit: the documents of the sampled parts
for steps 2 and 3, the entries for steps 4 and 5. Runs store the sample in their
options, so every run records what it covered.
"""

import argparse
from dataclasses import dataclass


@dataclass(frozen=True)
class SampleItem:
    """One item of a sample: a part, optionally narrowed to one catalogue number."""

    part: str
    number: str | None


def parse_sample(spec: str) -> list[SampleItem]:
    """Parse a sample specification such as 'XIX (4)/22;II (1)'."""
    items = []
    for raw in spec.split(";"):
        part, _, number = raw.strip().partition("/")
        part, number = part.strip(), number.strip()
        if not part or ("/" in raw and not number):
            raise argparse.ArgumentTypeError(
                f"invalid sample item {raw!r}; expected 'part' or 'part/number'"
            )
        items.append(SampleItem(part, number or None))
    return items


def sample_parts(sample: list[SampleItem] | None) -> set[str] | None:
    """Return the parts of a sample, or None (everything) if there is no sample."""
    return None if sample is None else {item.part for item in sample}


def add_sample_option(parser: argparse.ArgumentParser) -> None:
    """Add the --sample option to a command."""
    parser.add_argument(
        "--sample",
        type=parse_sample,
        help="only these parts or entries, e.g. 'XIX (4)/22;II (1)'; default: everything",
    )
