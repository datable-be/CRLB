"""Built-in checks of a segmentation, reported as counts."""

import itertools
from bisect import bisect_right
from collections import Counter

from crlb.segmentation.config import Config
from crlb.segmentation.model import Document, Seg
from crlb.segmentation.rules import follows, number_key


def walk(segs: list[Seg]) -> list[Seg]:
    """Return segments and all their descendants, depth first."""
    result = []
    for seg in segs:
        result.append(seg)
        result += walk(seg.children)
    return result


def entry_checks(
    doc: Document,
    catalogue: Seg,
    entries: list[Seg],
    dropped: list[str],
    furniture: list[Seg],
    config: Config,
) -> dict[str, int]:
    """Return the counts of the entry, field and link checks for one catalogue section."""
    keys = [number_key(e.label or "", config) for e in entries]
    gaps = sum(1 for a, b in itertools.pairwise(keys) if a and b and not follows(a, b))
    all_segs = walk(entries)
    # A link is anchored if it lies on a heading field or starts a copy
    heading_links = {
        entry.label: doc.links_on(field.first, field.last)
        for entry in entries
        for field in entry.children
        if field.label == "heading"
    }
    anchored = {s.link_id for s in all_segs if s.link_id is not None}.union(
        *heading_links.values()
    )
    fields = Counter(s.label for s in all_segs if s.kind == "field" and s.label)
    unanchored = doc.links_on(catalogue.first, catalogue.last) - anchored
    moved = set().union(
        *(
            doc.links_on(s.first, s.last)
            for s in furniture
            if s.label == "moved_by_link_tool"
        )
    )
    return {
        "entries": len(entries),
        "numbering gaps": gaps,
        "numbers dropped (out of sequence)": len(dropped),
        "entries with an RKD link on the heading": sum(
            1 for links in heading_links.values() if links
        ),
        "entries with material or location": sum(
            1
            for e in entries
            if any(f.label in ("material", "location") for f in e.children)
        ),
        **{f"fields: {name}": n for name, n in sorted(fields.items())},
        "copies": sum(1 for s in all_segs if s.kind == "copy"),
        "items": sum(1 for s in all_segs if s.kind == "item"),
        "notes": sum(1 for s in all_segs if s.kind == "note"),
        "cross-references": sum(
            1 for s in all_segs if "cross-reference" in (s.reason or "")
        ),
        # Labels that step 2 left letter-spaced: feedback for the OCR correction
        "labels matched only on the raw words": sum(
            1 for s in all_segs if "raw words" in (s.reason or "")
        ),
        # Copy numbers re-set by the link tool lie outside the reading order
        "RKD links on text moved by the link tool": len(unanchored & moved),
        "RKD links in the catalogue not on a heading or copy": len(unanchored - moved),
    }


def boundary_conflicts(segs: list[Seg], joined: list[tuple[int, int]]) -> int:
    """Return the number of segments with a boundary inside a joined token of the correction run.

    `joined` holds the (first, last) word ids of corrected tokens that cover
    more than one raw word. A boundary inside one means a wrong join (step 2)
    or a wrong boundary (step 3); the effective text then uses the raw words.
    """
    starts = sorted(joined)
    firsts = [a for a, _ in starts]

    def inside(word_id: int, at_start: bool) -> bool:
        """Return whether a boundary at word_id splits a joined token."""
        k = bisect_right(firsts, word_id) - 1
        if k < 0:
            return False
        a, b = starts[k]
        return a < word_id <= b if at_start else a <= word_id < b

    return sum(
        1
        for seg in segs
        if seg.kind != "furniture"
        and (inside(seg.first, True) or inside(seg.last, False))
    )


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
