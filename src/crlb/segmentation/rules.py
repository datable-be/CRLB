"""The segmentation rules: pure functions from a document view and its configuration to segments.

The rules run in order, each on the result of the previous one:

1. furniture: lines inside a configured band (running heads, page numbers),
   and words set by the RKD link tool, which are stored out of reading order;
   the page numbers give the printed page numbers;
2. sections: from the bookmarks, or from the running heads;
3. entries: in the catalogue section, at heading lines matching the volume's
   pattern (and style), kept only if their numbers increase.
"""

import re
from bisect import bisect_left
from collections.abc import Iterable

from crlb.segmentation.config import Config
from crlb.segmentation.model import Document, Line, Seg

DIGITS = re.compile(r"^\d+$")


def is_furniture(line: Line, config: Config) -> str | None:
    """Return the label of the furniture band a line lies in, or None."""
    for band in config.furniture:
        if (
            band.top <= line.top
            and line.bottom <= band.bottom
            and band.min_size <= line.size <= band.max_size
        ):
            return band.label
    return None


def furniture(doc: Document, config: Config) -> list[Seg]:
    """Return the furniture segments: band lines, and runs of words in a link-tool font."""
    result = []
    for line in doc.lines:
        if label := is_furniture(line, config):
            result.append(
                Seg(
                    "furniture",
                    label,
                    line.first,
                    line.last,
                    "band",
                    "certain",
                    f"{label} band; {line.size:.1f} pt",
                )
            )
            continue
        # Consecutive words in a link-tool font form one segment
        runs: list[list[int]] = []
        previous_tool = False
        for word in line.words:
            tool = word.font in config.link_tool_fonts
            if tool and previous_tool:
                runs[-1].append(word.id)
            elif tool:
                runs.append([word.id])
            previous_tool = tool
        result += [
            Seg(
                "furniture",
                "moved_by_link_tool",
                run[0],
                run[-1],
                "font",
                "certain",
                "text set by the RKD link tool, out of reading order",
            )
            for run in runs
        ]
    return result


def printed_pages(
    doc: Document, furniture_segs: list[Seg]
) -> list[tuple[int, str | None, str]]:
    """Return (page index, printed number, rule) per page: read from the page-number furniture, else interpolated.

    A read number is used only if it is all digits and agrees with a neighbour
    read number; between two agreeing read numbers, missing pages are filled
    in. Pages that cannot be placed (plates, unnumbered pages) get None.
    """
    by_first = {s.first: s for s in furniture_segs if s.label == "page_number"}
    read: dict[int, int] = {}
    for index, page in enumerate(doc.pages):
        for line in page:
            if line.first in by_first and DIGITS.match(line.text.replace(" ", "")):
                read[index] = int(line.text.replace(" ", ""))
                break
    # Keep a read number only if a neighbouring read number gives the same offset
    offsets = {i: n - i for i, n in read.items()}
    known = sorted(offsets)
    trusted = {}
    for k, i in enumerate(known):
        neighbours = [offsets[j] for j in known[max(k - 1, 0) : k + 2] if j != i]
        if offsets[i] in neighbours:
            trusted[i] = read[i]
    result = []
    keys = sorted(trusted)
    for index in range(len(doc.pages)):
        if index in trusted:
            result.append((index, str(trusted[index]), "furniture"))
            continue
        pos = bisect_left(keys, index)
        if 0 < pos < len(keys):
            before, after = keys[pos - 1], keys[pos]
            if trusted[before] - before == trusted[after] - after:
                result.append(
                    (index, str(trusted[before] + index - before), "interpolated")
                )
                continue
        result.append((index, None, "interpolated"))
    return result


def section_name(title: str, config: Config) -> str:
    """Return the normalised name of a section title, or the title in lowercase."""
    for name, pattern in config.section_names.items():
        if pattern.search(title):
            return name
    return title.strip().lower()


def page_range_words(
    doc: Document, first_page: int, last_page: int
) -> tuple[int, int] | None:
    """Return the first and last word id of a range of pages, or None if they have no words."""
    lines = [line for page in doc.pages[first_page : last_page + 1] for line in page]
    return (lines[0].first, lines[-1].last) if lines else None


def section_starts(
    doc: Document, config: Config, furniture_segs: list[Seg]
) -> list[tuple[int, str, str]]:
    """Return (first page index, name, title) for each section, in page order."""
    if config.section_source == "bookmarks":
        starts = [
            (page, section_name(title, config), title)
            for level, title, page in doc.toc
            if level <= config.section_level and page is not None
        ]
        if not starts or starts[0][0] > 0:
            starts.insert(0, (0, "front matter", "front matter"))
        return starts
    # Running heads: each page takes the section of its head, a page without a head
    # that of the next page with one (section opening pages have no head)
    heads = {s.first: s for s in furniture_segs if s.label == "running_head"}
    per_page: list[str | None] = []
    for page in doc.pages:
        title = next((line.text for line in page if line.first in heads), None)
        if title is not None:
            match = config.head_name.match(title)
            title = match.group(1) if match else title
        per_page.append(title)
    following = None
    for index in range(len(per_page) - 1, -1, -1):
        if per_page[index] is None:
            per_page[index] = following
        following = per_page[index]
    starts = []
    for index, title in enumerate(per_page):
        title = title or "untitled"
        if not starts or starts[-1][2] != title:
            starts.append((index, section_name(title, config), title))
    return starts


def sections(doc: Document, config: Config, furniture_segs: list[Seg]) -> list[Seg]:
    """Return the section segments, together covering every word of the document."""
    starts = section_starts(doc, config, furniture_segs)
    result = []
    for k, (first_page, name, title) in enumerate(starts):
        last_page = starts[k + 1][0] - 1 if k + 1 < len(starts) else len(doc.pages) - 1
        words = page_range_words(doc, first_page, last_page)
        if words:
            rule = (
                "bookmarks" if config.section_source == "bookmarks" else "running heads"
            )
            result.append(
                Seg(
                    "section",
                    name,
                    words[0],
                    words[1],
                    rule,
                    "certain",
                    f"{title!r}, pdf pages {first_page + 1}-{last_page + 1}",
                )
            )
    return result


def number_key(number: str, config: Config) -> tuple[int, int, str] | None:
    """Return the sort key of an entry number ('10a' -> (0, 10, 'a')), or None if it does not parse."""
    match = config.number.match(number)
    if not match or match["prefix"] not in config.prefixes:
        return None
    return config.prefixes.index(match["prefix"]), int(match["digits"]), match["letter"]


def increasing(keys: list[tuple[int, int, str]]) -> set[int]:
    """Return the positions of a longest strictly increasing subsequence of keys."""
    tails: list[tuple[int, int, str]] = []
    tail_pos: list[int] = []
    parent = [-1] * len(keys)
    for i, key in enumerate(keys):
        k = bisect_left(tails, key)
        if k == len(tails):
            tails.append(key)
            tail_pos.append(i)
        else:
            tails[k] = key
            tail_pos[k] = i
        parent[i] = tail_pos[k - 1] if k else -1
    result = set()
    i = tail_pos[-1] if tail_pos else -1
    while i >= 0:
        result.add(i)
        i = parent[i]
    return result


def follows(previous: tuple[int, int, str], key: tuple[int, int, str]) -> bool:
    """Return whether an entry number directly follows another: 10 -> 10a or 11, 10a -> 10b or 11, last -> next prefix."""
    prefix, digits, letter = previous
    next_letter = chr(ord(letter) + 1) if letter else "a"
    return key in {
        (prefix, digits, next_letter),
        (prefix, digits + 1, ""),
        (prefix + 1, 1, ""),
    }


def number_text(key: tuple[int, int, str], config: Config) -> str:
    """Return the entry number of a key: (0, 10, 'a') -> '10a'."""
    return f"{config.prefixes[key[0]]}{key[1]}{key[2]}"


def infer_key(
    previous: tuple[int, int, str], following: tuple[int, int, str] | None
) -> tuple[int, int, str] | None:
    """Return the one number that fits between two entry numbers, or None if there is not exactly one."""
    prefix, digits, letter = previous
    next_letter = chr(ord(letter) + 1) if letter else "a"
    options = [
        (prefix, digits, next_letter),
        (prefix, digits + 1, ""),
        (prefix + 1, 1, ""),
    ]
    fitting = [k for k in options if following is None or follows(k, following)]
    return fitting[0] if len(fitting) == 1 else None


def heading_candidate(
    line: Line, doc: Document, config: Config
) -> tuple[str, str, int | None, list[str]] | None:
    """Return (number as printed, confidence, link id, evidence) if a line looks like an entry heading.

    With the damaged pattern the number may be unreadable or empty; the caller
    then infers it from the sequence.
    """
    text = line.corrected or line.text
    link = next(
        (
            lk
            for lk in doc.links
            if lk.page_index == line.page_index
            and any(lk.covers(w) for w in line.words)
        ),
        None,
    )
    evidence = []
    match = config.heading.match(text)
    if match:
        evidence.append("heading pattern")
    elif (
        link
        and config.heading_with_link
        and (match := config.heading_with_link.match(text))
    ):
        evidence.append("heading pattern without full stop, with RKD link")
    elif (
        link
        and config.heading_damaged_with_link
        and (match := config.heading_damaged_with_link.match(text))
    ):
        evidence.append("title pattern with RKD link")
    if not match:
        return None
    first = line.words[0]
    if config.heading_bold:
        if (
            not first.flags & 16
            or not config.heading_min_size <= first.size <= config.heading_max_size
        ):
            return None
        evidence.append(f"bold {first.size:.1f} pt")
    if link:
        evidence.append("RKD link")
    confidence = "certain" if link and evidence[0] == "heading pattern" else "probable"
    return (
        match["number"].replace(" ", ""),
        confidence,
        link.id if link else None,
        evidence,
    )


def entries(
    doc: Document, section: Seg, config: Config, skipped: Iterable[int] = ()
) -> tuple[list[Seg], list[str]]:
    """Return the entry segments of a section and the numbers dropped because they break the sequence.

    Headings with a readable number are kept if their numbers increase (a
    longest increasing subsequence); a heading whose number is damaged is kept
    if exactly one number fits between its neighbours. `skipped` holds the
    first word ids of furniture lines, which are never headings.
    """
    skip = set(skipped)
    lines = [
        line
        for line in doc.lines
        if section.first <= line.first <= section.last and line.first not in skip
    ]
    candidates = [
        (line, found)
        for line in lines
        if (found := heading_candidate(line, doc, config))
    ]
    keys = {
        i: key
        for i, (_, found) in enumerate(candidates)
        if (key := number_key(found[0], config))
    }
    readable = sorted(keys)
    keep = {readable[j] for j in increasing([keys[i] for i in readable])}
    dropped = [candidates[i][1][0] for i in readable if i not in keep]
    # Damaged numbers: infer from the kept neighbours
    accepted: list[
        tuple[Line, tuple[int, int, str], str, str, int | None, list[str]]
    ] = []
    for i, (line, (number, confidence, link_id, evidence)) in enumerate(candidates):
        if i in keep:
            accepted.append((line, keys[i], number, confidence, link_id, evidence))
        elif i not in keys and accepted:
            following = next(
                (keys[j] for j in range(i + 1, len(candidates)) if j in keep), None
            )
            if inferred := infer_key(accepted[-1][1], following):
                note = (
                    f"number {number!r} unreadable, inferred from the sequence"
                    if number
                    else "no number, inferred from the sequence"
                )
                accepted.append(
                    (
                        line,
                        inferred,
                        number_text(inferred, config),
                        "uncertain",
                        link_id,
                        [*evidence, note],
                    )
                )
            else:
                dropped.append(number or "?")
    result = []
    for k, (line, _key, number, confidence, link_id, evidence) in enumerate(accepted):
        last = accepted[k + 1][0].first - 1 if k + 1 < len(accepted) else section.last
        result.append(
            Seg(
                "entry",
                number,
                line.first,
                last,
                "heading",
                confidence,
                "; ".join(evidence),
                link_id,
            )
        )
    return result, dropped
