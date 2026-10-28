"""Verbatim dates of the CRLB text to an ISO start and end (YYYY, YYYY-MM or YYYY-MM-DD).

Handles the forms of the provenance, the date field and the citations:
`c. 1598–1600`, `1925-26`, `26 May 1777`, `20–21 July 2011`, `15ff. June 1874`,
`December 1856`, `between 17 March 1613 and 2 May 1616`, `(1612 - 23 October 1652)`,
`until 1931`. The start is the start of the first date in the text, the end the
end of the last one; `ff.` and `et seqq.` leave the end open.
"""

import re
from dataclasses import dataclass

MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sept", "sep"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for name in names
}
MONTH = r"(?:" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\b\.?"
DASH = r"\s*[–—-]\s*"

DATE = re.compile(
    # Day(s), month and year: '26 May 1777', '20–21 July 2011', '15ff. June 1874'
    rf"(?P<d1>\b\d{{1,2}})(?P<ff>\s*ff\.)?(?:{DASH}(?P<d2>\d{{1,2}}))?\s+(?P<m1>{MONTH})\s+(?P<y1>\d{{4}})\b"
    # Month and year: 'December 1856'
    rf"|(?P<m2>{MONTH})\s+(?P<y2>\d{{4}})\b"
    # Year or range of years: '1613–1616', '1925-26'; not '1612 - 23 October 1652'
    rf"|(?P<y3>\b\d{{4}})(?:{DASH}(?P<y4>\d{{2,4}})\b(?!\s+{MONTH}))?",
    re.IGNORECASE,
)
OPEN_END = re.compile(r"\bff\.|\bet seqq?\.|\bfollowing days\b", re.IGNORECASE)
UNTIL = re.compile(r"^\s*\(?\s*until\b", re.IGNORECASE)


@dataclass(frozen=True)
class DateRange:
    """A parsed date: ISO start and end; either may be None."""

    start: str | None
    end: str | None


def plausible(year: int) -> bool:
    """Return whether a four-digit number can be a year in the CRLB."""
    return 1400 <= year <= 2099


def complete_year(start: int, end: str) -> int:
    """Return the end year of a range written short: (1925, '26') -> 1926."""
    if len(end) == 4:
        return int(end)
    century = start - start % 10 ** len(end)
    year = century + int(end)
    return year if year >= start else year + 10 ** len(end)


def parse_date(text: str) -> DateRange | None:
    """Return the start and end of the dates in a text, or None if it has none."""
    points: list[tuple[str, str | None]] = []
    for match in DATE.finditer(text):
        if match["y1"]:
            year = int(match["y1"])
            month = MONTHS[match["m1"].lower().rstrip(".")]
            first = f"{year:04d}-{month:02d}-{int(match['d1']):02d}"
            if match["ff"]:
                last = None
            elif match["d2"]:
                last = f"{year:04d}-{month:02d}-{int(match['d2']):02d}"
            else:
                last = first
        elif match["y2"]:
            year = int(match["y2"])
            first = last = f"{year:04d}-{MONTHS[match['m2'].lower().rstrip('.')]:02d}"
        else:
            year = int(match["y3"])
            first = f"{year:04d}"
            last = f"{complete_year(year, match['y4']):04d}" if match["y4"] else first
        if plausible(year):
            points.append((first, last))
    if not points:
        return None
    start, end = points[0][0], points[-1][1]
    if OPEN_END.search(text):
        end = None
    if UNTIL.search(text):
        start = None
    return DateRange(start, end)
