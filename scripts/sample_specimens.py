"""Draw a reproducible random sample of catalogue and index pages for OCR quality testing.

All page images and OCR text are written to the output directory only; the console
shows nothing but counts and page numbers.
"""

import argparse
import csv
import random
import re
from pathlib import Path

import pymupdf

# Files to sample from, with the kind of section to sample in each
SPECIMEN_FILES = {
    "CRLB_02_1_links-cxVmajEMUVTrFvcJZBinvpab.pdf": "catalogue",
    "CRLB_19_2_links-VoPOPfmJNRiHYXlZnw1MecVP.pdf": "catalogue",
    "CRLB_26_2_I_1_querylink-j2ZTGXhbVOWdKmsVUit4WHHJ.pdf": "catalogue",
    "CRLB_02_index-LOGXbYlPJJhRnlbBPpbWbprN.pdf": "index",
    "CRLB_19_2_index-G1LuPVPWUGbVamTjQm6KtT8s.pdf": "index",
    "CRLB_26_2_I_Index-DIjNSVaf9NjUUZeNEYoN9IjY.pdf": "index",
}
CATALOGUE_TITLE = re.compile(r"catalog", re.IGNORECASE)
MANIFEST_FIELDS = ["specimen_id", "file", "ocr_year", "section", "page", "words"]


def catalogue_pages(toc: list[list], page_count: int) -> list[int]:
    """Return the 1-based pages covered by bookmarks whose title mentions the catalogue."""
    pages: set[int] = set()
    for i, (level, title, start) in enumerate(toc):
        if not CATALOGUE_TITLE.search(title) or start < 1:
            continue
        end = next(
            (p - 1 for lvl, _, p in toc[i + 1 :] if lvl <= level and p >= start),
            page_count,
        )
        pages.update(range(start, max(end, start) + 1))
    return sorted(pages)


def short_name(filename: str) -> str:
    """Return a compact file label, e.g. '02_1_links' for 'CRLB_02_1_links-xyz.pdf'."""
    return Path(filename).stem.split("-")[0].removeprefix("CRLB_")


def sample_document(
    pdf_path: Path,
    section: str,
    out_dir: Path,
    pages: int,
    seed: int,
    dpi: int,
    min_words: int,
) -> list[dict]:
    """Sample pages from one PDF, write image and text files, and return manifest rows."""
    doc = pymupdf.open(pdf_path)
    if section == "index":
        section_pages = list(range(1, doc.page_count + 1))
    else:
        section_pages = catalogue_pages(doc.get_toc(simple=True), doc.page_count)

    word_counts = {p: len(doc[p - 1].get_text("words")) for p in section_pages}
    candidates = [p for p in section_pages if word_counts[p] >= min_words]
    # Seed per file so adding or removing files does not change the other samples
    rng = random.Random(f"{seed}-{pdf_path.name}")
    chosen = sorted(rng.sample(candidates, min(pages, len(candidates))))
    print(
        f"{short_name(pdf_path.name)}: {section} pages {len(section_pages)}, "
        f"with >= {min_words} words {len(candidates)}, sampled {chosen}"
    )

    ocr_year = (doc.metadata or {}).get("creationDate", "")[2:6]
    rows = []
    for page_no in chosen:
        specimen_id = f"{short_name(pdf_path.name)}_p{page_no:04d}"
        specimen_dir = out_dir / specimen_id
        specimen_dir.mkdir(parents=True)
        page = doc[page_no - 1]
        page.get_pixmap(dpi=dpi).save(specimen_dir / "page.png")
        text = page.get_text("text")
        (specimen_dir / "ocr.txt").write_text(text, encoding="utf-8")
        (specimen_dir / "gt.txt").write_text(text, encoding="utf-8")
        rows.append(
            {
                "specimen_id": specimen_id,
                "file": pdf_path.name,
                "ocr_year": ocr_year,
                "section": section,
                "page": page_no,
                "words": word_counts[page_no],
            }
        )
    return rows


def main() -> None:
    """Parse arguments and write the specimen sample to the output directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf_dir", type=Path, help="directory containing the CRLB PDFs")
    parser.add_argument("out_dir", type=Path, help="new directory for the specimens")
    parser.add_argument("--pages", type=int, default=2, help="pages to sample per file")
    parser.add_argument("--seed", type=int, default=42, help="random seed")
    parser.add_argument(
        "--dpi", type=int, default=200, help="resolution of the page images"
    )
    parser.add_argument(
        "--min-words", type=int, default=50, help="skip pages with fewer words"
    )
    args = parser.parse_args()

    # Refuse to reuse a directory so corrected gt.txt files are never overwritten
    if args.out_dir.exists():
        parser.error(f"{args.out_dir} already exists; choose a new output directory")
    args.out_dir.mkdir(parents=True)

    rows = []
    for filename, section in SPECIMEN_FILES.items():
        rows += sample_document(
            args.pdf_dir / filename,
            section,
            args.out_dir,
            args.pages,
            args.seed,
            args.dpi,
            args.min_words,
        )

    with (args.out_dir / "manifest.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} specimens written to {args.out_dir}")


if __name__ == "__main__":
    main()
