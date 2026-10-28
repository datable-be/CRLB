"""Built-in checks of a segmentation, reported as counts."""

import itertools

from crlb.segmentation.config import Config
from crlb.segmentation.model import Document, Seg
from crlb.segmentation.rules import follows, number_key


def entry_checks(
    doc: Document,
    catalogue: Seg,
    entries: list[Seg],
    dropped: list[str],
    config: Config,
) -> dict[str, int]:
    """Return the counts of the entry checks for one catalogue section."""
    keys = [number_key(e.label or "", config) for e in entries]
    gaps = sum(1 for a, b in itertools.pairwise(keys) if a and b and not follows(a, b))
    heading_links = {e.link_id for e in entries if e.link_id is not None}
    words = {
        w.id
        for line in doc.lines
        if catalogue.first <= line.first <= catalogue.last
        for w in line.words
    }
    catalogue_links = {
        link.id
        for link in doc.links
        for line in doc.pages[link.page_index]
        if line.first in words and any(link.covers(w) for w in line.words)
    }
    return {
        "entries": len(entries),
        "entries with an RKD link": len(heading_links),
        "numbering gaps": gaps,
        "numbers dropped (out of sequence)": len(dropped),
        "RKD links in the catalogue not on a heading": len(
            catalogue_links - heading_links
        ),
    }


def page_checks(printed: list[tuple[int, str | None, str]]) -> dict[str, int]:
    """Return the counts of the printed page number checks."""
    read = sum(1 for _, _, rule in printed if rule == "furniture")
    interpolated = sum(
        1
        for _, number, rule in printed
        if rule == "interpolated" and number is not None
    )
    numbers = [(i, int(n)) for i, n, _ in printed if n is not None]
    decreasing = sum(
        1 for (i, a), (j, b) in itertools.pairwise(numbers) if b - a != j - i and b <= a
    )
    return {
        "printed page numbers read": read,
        "interpolated": interpolated,
        "unnumbered": sum(1 for _, n, _ in printed if n is None),
        "not increasing": decreasing,
    }
