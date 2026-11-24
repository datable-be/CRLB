"""The parts of a catalogue entry: fields, copies, notes and items (rules 4-7 and 9 of the plan).

An entry is divided, from top to bottom, into:

- heading: the heading line (and, where configured, the bold lines after it);
- material, location, date: the groups of lines before the first label, a
  group being lines without a vertical gap; a location starts in italics, a
  date matches the date pattern;
- labelled fields (provenance, exhibited, copies, literature, ...): from a
  line that starts with a label to the next label or the description;
- description: the body text after the labelled fields;
- notes: note-size lines after the description, starting at note number 1.

Within a copies field, each copy starts at "(n)"; within a copy, sub-fields
start at "prov.", "lit." or "exh.". List fields are split into items at ";"
outside brackets and quotation marks. Labels, copies and items are found on the
raw words, with spaces ignored, so that OCR splits ("P rov en a n ce:") do not
matter; punctuation is reliable in both volumes.
"""

import re

from crlb.segmentation.config import Config, Fields
from crlb.segmentation.model import Document, Line, Seg, Word

OPENING = "([“‘«"
CLOSING = ")]”’»"
SEE = re.compile(r"^\W*see\b", re.IGNORECASE)
OCR_ONE = {"i", "l", "I"}
# A copy marker the OCR damaged beyond the marker pattern: "(ix)" for "(11)"
DAMAGED_MARKER = re.compile(r"^\([0-9ilIxX|!oO]{1,3}\)[,;:.]?$")
MAX_MATERIAL_LINES = 5


def label_length(
    texts: list[str],
    aliases: list[str],
    separator: re.Pattern[str],
    ignore_spaces: bool = True,
) -> int:
    """Return how many of the texts a label at their start takes up, or 0 if none of the aliases is there.

    The texts are casefolded and joined, without spaces if ignore_spaces
    ("P r o v e n a n c e :"), else with single spaces ("Provenance :"); the
    label must be followed by a separator. A text that holds both the end of
    the label and what follows it ("'.Drawing") stays outside the label.
    """
    joiner = "" if ignore_spaces else " "
    joined = ""
    ends = []
    for text in texts[:20]:
        joined += (joiner if joined else "") + text.casefold()
        ends.append(len(joined))
    for alias in sorted(aliases, key=len, reverse=True):
        label = alias.casefold().replace(" ", "") if ignore_spaces else alias.casefold()
        if not joined.startswith(label):
            continue
        match = re.compile(f" ?(?:{separator.pattern})+").match(joined, len(label))
        if match:
            return max(1, sum(1 for end in ends if end <= match.end()))
    return 0


def find_label(line: Line, fields: Fields) -> tuple[str, int, bool] | None:
    """Return the field name, the number of raw label words and whether the corrected text was used, if a line starts with a label.

    Labels are matched on the corrected text of step 2 ("Provenance:"). Where
    step 2 left a letter-spaced label unjoined ("P r o v e n a n c e :"), the
    raw words are matched with spaces ignored; such fallbacks are counted in
    the checks, as they show joins step 2 missed.
    """
    for name, aliases in fields.labels.items():
        if n := label_length(
            [text for text, _ in line.tokens],
            aliases,
            fields.separator,
            ignore_spaces=False,
        ):
            last = line.tokens[n - 1][1]
            return name, sum(1 for w in line.words if w.id <= last), True
    for name, aliases in fields.labels.items():
        if n := label_length([w.text for w in line.words], aliases, fields.separator):
            return name, n, False
    return None


def groups(lines: list[Line]) -> list[list[Line]]:
    """Split lines into groups at a vertical gap of more than half a line height, or a page change."""
    result: list[list[Line]] = []
    for line in lines:
        if result:
            previous = result[-1][-1]
            height = previous.bottom - previous.top
            if (
                line.page_index == previous.page_index
                and line.top - previous.bottom <= 0.5 * height
            ):
                result[-1].append(line)
                continue
        result.append([line])
    return result


# The gap (fraction of the page height) above a description in an OCR volume;
# the lines of a field are at most 0.010 apart
DESCRIPTION_GAP = 0.015
# A label the OCR spaced out and garbled, so that find_label misses it ('L i t b r a t u r e :')
SPACED_LABEL = re.compile(r"^(?:\S\s){4,}\S*\s*:")


def ends_sentence(line: Line) -> bool:
    """Return whether a line ends with a full stop (possibly before a closing bracket or quote)."""
    return line.text.rstrip(CLOSING + " ").endswith(".")


def is_description_start(line: Line, previous: Line, fields: Fields) -> bool:
    """Return whether a line starts the description of an entry."""
    if fields.description_min_size is not None:
        # The OCR's sizes are unreliable (a literature line at 12 pt, a whole page
        # of description at 7.5 pt), so on the same page the gap above the line
        # decides; at a page break, the size and the end of the line before
        if not line.text[:1].isalpha() or SPACED_LABEL.match(line.text):
            return False
        if line.page_index == previous.page_index:
            return line.top - previous.bottom >= DESCRIPTION_GAP
        return line.size >= fields.description_min_size and ends_sentence(previous)
    if fields.description_new_block:
        return (
            line.block_no != previous.block_no
            and ends_sentence(previous)
            and line.text[:1].isupper()
        )
    return False


def heading_end(lines: list[Line], config: Config) -> int:
    """Return the index of the first line after the heading."""
    end = 1
    if config.fields.heading_bold_lines:
        while end < len(lines):
            first = lines[end].words[0]
            if not (
                first.flags & 16
                and config.heading_min_size <= first.size <= config.heading_max_size
            ):
                break
            end += 1
    return end


def ends_mark_sentence(line: Line) -> bool:
    """Return whether a line ends with a full stop after a word ('Vervoert.', 'GEVBELS.'), not after an initial or alone ('RAES F.', 'IAN .')."""
    words = line.text.rstrip(CLOSING + " ").split()
    if not words:
        return False
    core = re.sub(r"\W", "", words[-1])
    # The OCR may read the full stop after the weaver's name as a comma ('GEVBELS,')
    return (words[-1].endswith(".") and len(core) > 1) or (
        words[-1].endswith(",") and len(core) > 2 and core.isupper()
    )


def continues_marks(previous: Line, line: Line) -> bool:
    """Return whether a line continues the tapestry marks of the previous one.

    It does when the previous line does not end a sentence, or when the line
    starts with a name in capitals ('RAES F.', 'GEVBELS') or in lower case
    ('of Jacob Fobert'); a line starting with a capitalised word ('Madrid,
    Convent ...') after a sentence end starts the location.
    """
    first = re.sub(r"\W", "", line.words[0].text)
    return (
        not ends_mark_sentence(previous)
        or (len(first) > 1 and first.isupper())
        or first[:1].islower()
    )


def material_groups(lines: list[Line], fields: Fields) -> list[list[Line]]:
    """Return the groups of lines before the labels, with a material that runs on (tapestry marks) kept whole."""
    grouped = groups(lines)
    if not grouped or fields.material_continues is None:
        return grouped
    if not fields.material_continues.search(" ".join(l.text for l in grouped[0])):
        return grouped
    n = 1
    while n < min(len(lines), MAX_MATERIAL_LINES) and continues_marks(
        lines[n - 1], lines[n]
    ):
        n += 1
    return [lines[:n], *groups(lines[n:])]


def before_labels(
    lines: list[Line], fields: Fields, start: int, stop: int
) -> tuple[list[tuple[str, list[Line]]], int]:
    """Return the (name, lines) groups between the heading and the first label, and where they stop.

    The first group is the material; a group starting in italics is the
    location, one matching the date pattern the date. If there is no label, the
    first group that is none of these starts the description.
    """
    result = []
    end = start
    for k, group in enumerate(material_groups(lines[start:stop], fields)):
        if k == 0:
            name = "material"
        elif group[0].italic:
            name = "location"
        elif fields.date.match(group[0].text):
            name = "date"
        else:
            break
        result.append((name, group))
        end += len(group)
    return result, end


def split_items(words: list[Word], start: int) -> list[tuple[int, int]]:
    """Return (first id, last id) of the items of a list: split after ';' outside brackets and quotes."""
    items = []
    depth = 0
    first = None
    for word in words[start:]:
        if first is None:
            first = word.id
        for char in word.text:
            if char in OPENING:
                depth += 1
            elif char in CLOSING:
                depth = max(depth - 1, 0)
            elif char == '"':
                depth = depth - 1 if depth else depth + 1
        if depth == 0 and word.text.rstrip(CLOSING).endswith(";"):
            items.append((first, word.id))
            first = None
    if first is not None:
        items.append((first, words[-1].id))
    return items


def item_segs(words: list[Word], start: int, rule: str) -> list[Seg]:
    """Return item segments for the words of a list field, after its label words."""
    return [
        Seg(
            "item",
            str(k + 1),
            first,
            last,
            rule,
            "probable",
            "split at ';' outside brackets and quotes",
        )
        for k, (first, last) in enumerate(split_items(words, start))
    ]


def copy_marker(
    words: list[Word], i: int, pattern: re.Pattern[str]
) -> tuple[str, int] | None:
    """Return the number of a copy marker starting at word i ('(2)' or '( i )') and its word count, or None."""
    for n in (1, 3):
        if i + n <= len(words):
            text = "".join(w.text for w in words[i : i + n])
            if match := pattern.match(text):
                number = match["number"]
                return ("1" if number in OCR_ONE else number), n
    return None


def copy_starts(
    words: list[Word], line_starts: set[int], pattern: re.Pattern[str]
) -> list[tuple[int, str]]:
    """Return (word position, number) of the copy markers, in sequence from (1).

    A marker counts at the start of a line or after punctuation (OCR may turn
    ";" into "!"), and only with the next number or the one after it, so a
    marker damaged beyond recognition does not stop the sequence.
    """
    result = []
    expected = 1
    for i, word in enumerate(words):
        previous = words[i - 1].text.rstrip(CLOSING) if i else ""
        at_start = (
            word.id in line_starts
            or i == 0
            or (previous and not previous[-1].isalnum())
        )
        if not at_start:
            continue
        found = copy_marker(words, i, pattern)
        if found and int(found[0]) in (expected, expected + 1):
            result.append((i, found[0]))
            expected = int(found[0]) + 1
        elif (
            found is None
            and DAMAGED_MARKER.match(word.text)
            and next_marker(words, i + 1, line_starts, pattern, expected + 1)
        ):
            result.append((i, str(expected)))
            expected += 1
    return result


def next_marker(
    words: list[Word],
    start: int,
    line_starts: set[int],
    pattern: re.Pattern[str],
    number: int,
) -> bool:
    """Return whether the marker of a copy number comes later, at a start of a line or after punctuation."""
    for i in range(start, len(words)):
        previous = words[i - 1].text.rstrip(CLOSING)
        if not (
            words[i].id in line_starts or (previous and not previous[-1].isalnum())
        ):
            continue
        found = copy_marker(words, i, pattern)
        if found and int(found[0]) == number:
            return True
    return False


def copy_parts(words: list[Word], config: Config) -> list[Seg]:
    """Return the sub-fields of one copy: its object description, then 'prov.', 'lit.' and 'exh.' fields."""
    fields = config.fields
    starts = [(0, "object")]
    for i, word in enumerate(words[1:], 1):
        text = word.text.casefold()
        token = text.rstrip(":")
        for name, aliases in fields.copy_labels.items():
            # An alias with a colon only counts with it ('print:', not 'print' in the text)
            if any(
                text == a.casefold() if a.endswith(":") else token == a.casefold()
                for a in aliases
            ):
                starts.append((i, name))
        if starts[-1][1] == "print":
            break  # a print after the copy keeps its own 'lit.:' inside it
    result = []
    for k, (i, name) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(words)
        part = words[i:end]
        if not part:
            continue
        seg = Seg(
            "field",
            name,
            part[0].id,
            part[-1].id,
            "copy label" if k else "copy start",
            "probable",
        )
        if name in fields.item_fields:
            seg.children = item_segs(part, 1, "items in copy")
        result.append(seg)
    return result


def copies(
    field_words: list[Word],
    line_starts: set[int],
    start: int,
    doc: Document,
    config: Config,
) -> list[Seg]:
    """Return the copy segments of a copies field, after its label words.

    A field without "(n)" markers ("Copy: Drawing ...") is one copy, (1).
    """
    words = field_words[start:]
    if not words:
        return []
    starts = copy_starts(words, line_starts, config.fields.copy_marker)
    rule = "copy marker"
    if not starts:
        starts, rule = [(0, "1")], "single copy"
    result = []
    for k, (i, number) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(words)
        part = words[i:end]
        # The link of a copy lies on its marker or on the first words after it
        links = doc.links_on(part[0].id, part[min(5, len(part) - 1)].id)
        link_id = min(links) if links else None
        seg = Seg(
            "copy",
            f"({number})",
            part[0].id,
            part[-1].id,
            rule,
            "certain" if link_id else "probable",
            "RKD link" if link_id else None,
            link_id,
        )
        seg.children = copy_parts(part, config)
        result.append(seg)
    return result


def notes(lines: list[Line], fields: Fields) -> list[Seg]:
    """Return one segment per note: a note starts at the next expected number at the start of a line."""
    starts = []
    expected = 1
    for k, line in enumerate(lines):
        match = fields.note_number.match(line.words[0].text)
        # The first note may have a higher number when the OCR damaged the ones before it
        if match and (
            int(match["number"]) == expected
            or (not starts and int(match["number"]) <= fields.first_note_max)
        ):
            starts.append((k, match["number"]))
            expected = int(match["number"]) + 1
    result = []
    for j, (k, number) in enumerate(starts):
        end = starts[j + 1][0] if j + 1 < len(starts) else len(lines)
        result.append(
            Seg(
                "note",
                number,
                lines[k].first,
                lines[end - 1].last,
                "note number",
                "probable",
            )
        )
    return result


def first_note(lines: list[Line], start: int, fields: Fields) -> int | None:
    """Return the index of the line where the notes start: note size and a first note number."""
    return next(
        (
            j
            for j in range(start, len(lines))
            if lines[j].size <= fields.notes_max_size
            and (m := fields.note_number.match(lines[j].words[0].text))
            and 1 <= int(m["number"]) <= fields.first_note_max
        ),
        None,
    )


def group_fields(group: Seg, lines: list[Line], config: Config) -> list[Seg]:
    """Return the fields of an introduction to a group of entries: its heading, its text and its notes."""
    if not lines:
        return []
    end = 1
    while (
        end < len(lines)
        and lines[end].words[0].flags & 16
        and lines[end].size >= config.group_min_size
    ):
        end += 1
    notes_at = first_note(lines, end, config.fields)
    parts = [
        (0, "heading", "group heading lines"),
        (end, "description", "after heading"),
    ]
    if notes_at is not None:
        parts.append((notes_at, "notes", "note size and number"))
    result = []
    for k, (j, name, rule) in enumerate(parts):
        stop = parts[k + 1][0] if k + 1 < len(parts) else len(lines)
        field_lines = lines[j:stop]
        if not field_lines:
            continue
        last = lines[stop].first - 1 if stop < len(lines) else group.last
        seg = Seg("field", name, field_lines[0].first, last, rule, "probable")
        if name == "notes":
            seg.children = notes(field_lines, config.fields)
        result.append(seg)
    return result


def entry_fields(
    entry: Seg, lines: list[Line], doc: Document, config: Config
) -> list[Seg]:
    """Return the fields of one entry, given its lines without furniture."""
    fields = config.fields
    if not lines:
        return []
    starts: list[
        tuple[int, str, str, str | None, int]
    ] = []  # line index, name, rule, reason, label words
    body = heading_end(lines, config)
    starts.append((0, "heading", "heading lines", None, 0))
    labels = [
        (k, found)
        for k in range(body, len(lines))
        if (found := find_label(lines[k], fields))
    ]
    # The description follows the last labelled field (or the groups before the labels)
    pre_stop = labels[0][0] if labels else len(lines)
    pre, after_pre = before_labels(lines, fields, body, pre_stop)
    k = body
    for name, group in pre:
        starts.append((k, name, "before labels", None, 0))
        k += len(group)
    if labels:
        description = next(
            (
                j
                for j in range(labels[-1][0] + 1, len(lines))
                if is_description_start(lines[j], lines[j - 1], fields)
            ),
            None,
        )
    else:
        # Without labels the description is the first group that is not material, location or date
        description = after_pre if after_pre < len(lines) else None
    for j, (name, n_label, corrected) in labels:
        if description is None or j < description:
            remarks = []
            if not corrected:
                remarks.append("label matched on the raw words (not joined by step 2)")
            if SEE.match(" ".join(w.text for w in lines[j].words[n_label:])):
                remarks.append("cross-reference")
            starts.append((j, name, "label", "; ".join(remarks) or None, n_label))
    notes_start = None
    if description is not None:
        starts.append((description, "description", "after labelled fields", None, 0))
        notes_start = first_note(lines, description + 1, fields)
        if notes_start is not None:
            starts.append((notes_start, "notes", "note size and number", None, 0))
    starts.sort()
    result = []
    for s, (j, name, rule, reason, n_label) in enumerate(starts):
        end_line = starts[s + 1][0] if s + 1 < len(starts) else len(lines)
        field_lines = lines[j:end_line]
        if not field_lines:
            continue
        last = lines[end_line].first - 1 if end_line < len(lines) else entry.last
        if last < field_lines[0].first:
            # a heading stored out of reading order ends at its own last word
            last = field_lines[-1].last
        seg = Seg("field", name, field_lines[0].first, last, rule, "probable", reason)
        words = [w for line in field_lines for w in line.words]
        if name in fields.numbered_fields:
            seg.children = copies(
                words, {line.first for line in field_lines}, n_label, doc, config
            )
        elif (
            name in fields.item_fields
            and rule == "label"
            and "cross-reference" not in (reason or "")
        ):
            seg.children = item_segs(words, n_label, "items")
        elif name == "notes":
            seg.children = notes(field_lines, fields)
        result.append(seg)
    return result
