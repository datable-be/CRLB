# OCR and PDF structure of the CRLB PDFs

This document records an analysis of the 18 PDFs in `doc/CRLB_pdfs`: how they are built, what OCR text layer they contain, what links they carry, and how the OCR text can be extracted with coordinates for a future validation tool.

Tools used: `pdfinfo`, `pdffonts`, `pdfimages` (poppler), `pypdf` and PyMuPDF.

## Summary

- **Every PDF has an OCR text layer** produced by ABBYY FineReader 11 (invisible text over the scanned page image). No new OCR is needed.
- The files fall into three groups by **link model**: per-figure RKDimages links, a single RKD search query link, or no RKD links.
- Page images come in three variants: pure black and white, greyscale MRC, or colour MRC.
- Word-level text with bounding boxes can be extracted reliably with PyMuPDF; boxes align with the scanned text.

## Groups by link model

### Group A: per-figure links (`*_links`)

Each illustration is linked to its own RKD image record. These files also contain Highlight + Popup annotations (and FreeText annotations) in numbers close to the link count, which suggests the links were added by hand: highlight the figure, then link it.

| File       | URI links | URL pattern                                               | TOC links (Contents page) | Bookmarks   |
| ---------- | --------- | --------------------------------------------------------- | ------------------------- | ----------- |
| 02_1       | 415       | `explore.rkd.nl/explore/images/N` (+9 `rkd.nl/explore/…`) | 21 (p. 5)                 | 22, depth 3 |
| 03         | 584       | `rkd.nl/images/N`                                         | 5 (p. 5)                  | none        |
| 09         | 208       | `rkd.nl/images/N` (+3 `explore.rkd.nl`)                   | 17 (p. 5–6)               | 24          |
| 18_1_links | 340       | `rkd.nl/explore/images/N`                                 | 4 (p. 5)                  | 13          |
| 19_1       | 170       | `rkd.nl/images/N` (+2 `explore/`)                         | 7 (p. 5)                  | 16          |
| 19_2_links | 534       | `rkd.nl/explore/images/N`                                 | 4 (p. 5)                  | 11          |
| 21_1       | 287       | `rkd.nl/explore/images/N`                                 | 5 (p. 5)                  | 8           |

Notes:

- **Three URL patterns** are in use: `explore.rkd.nl/explore/images/N`, `rkd.nl/explore/images/N` and `rkd.nl/images/N`. Code parsing these links must handle all three.
- **Broken links:** `03` contains `ftp://ftP.P.R` (OCR text auto-linked by mistake); `21_1` contains a link whose URI is the bare number `263903`.
- `09` and `19_1` (`_RKDresearch_repaired_DAMS`) were rewritten by 3-Heights PDF Analysis & Repair. They are PDF 1.4 and much larger (76 MB and 59 MB, against ~20 MB for the others).
- `03` has no Producer metadata, is PDF 1.3 and has no bookmarks; its only TOC navigation is the links on p. 5.
- `02_2_links` has "links" in its name but contains only 1 URI link and 3 GoTo links. In practice it belongs to group C.

### Group B: query link (`*_querylink`)

Files: `26_2_I_1`, `26_2_II_1`.

- 3 identical URI links per file to an RKD search page: `https://research.rkd.nl/nl/zoeken?q=citationpart:"corpus rubenianum ludwig burchard pt. 26-2, I"&…` (filtered on RKDimages).
- No clickable TOC links on the Contents page; navigation is through bookmarks only (8 entries, depth 2).

### Group C: no RKD links

Files: all `*_index` files (`02`, `18_1`, `19_1`, `19_2`, `26_2_I`), plus `02_2`, `21_2`, `26_2_I_2` and `26_2_II_2`.

- Most have bookmarks (6–10 entries); the older index files (`02`, `18_1`, `19_1`, `19_2`) have none.

### Empty link annotations

Almost every file contains Link annotations without an action (no `/A` and no `/Dest`), up to 99 in `26_2_II_1`. These are ABBYY leftovers and should be filtered out when processing links.

## Page images

| Type                                                                                            | Files                                            |
| ----------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| Pure black and white (1-bit JBIG2, ~330 dpi)                                                    | 02_1, 21_1, index files 02, 18_1, 19_1, 19_2     |
| Greyscale MRC (JPEG2000 background at 150 dpi + JBIG2 mask at 300 dpi), some pages bitonal only | 02_2, 03, 09, 18_1_links, 19_1, 19_2_links, 21_2 |
| Colour MRC (RGB JPEG2000 background + foreground + JBIG2 mask)                                  | all `26_2_*` files                               |

## OCR text layer

- Producer: ABBYY FineReader 11 for all files (except `03`, which has no metadata, and the two repaired files, which were rewritten by 3-Heights).
- Fonts are TrueType, **not embedded**, with Unicode mappings. This is normal for an invisible OCR layer.
- Pages without any text:

| File         | Pages without text / total |
| ------------ | -------------------------- |
| 02_1         | 7 / 416                    |
| 02_2         | 17 / 277                   |
| 02_index     | 0 / 40                     |
| 03           | 10 / 402                   |
| 09           | 24 / 546                   |
| 18_1_index   | 0 / 22                     |
| 18_1_links   | 9 / 375                    |
| 19_1_index   | 0 / 18                     |
| 19_1         | 16 / 337                   |
| 19_2_index   | 0 / 32                     |
| 19_2_links   | 14 / 400                   |
| 21_1         | 4 / 370                    |
| 21_2         | 5 / 424                    |
| 26_2_I_1     | 9 / 454                    |
| 26_2_I_2     | 49 / 275                   |
| 26_2_I_Index | 2 / 50                     |
| 26_2_II_1    | 6 / 452                    |
| 26_2_II_2    | 55 / 244                   |

`26_2_I_2` and `26_2_II_2` have about 50 pages each without text. These are probably plate pages, but this has not been checked visually. If they contain captions, those were missed by ABBYY and only those pages would need new OCR.

## Extracting text with coordinates

PyMuPDF's `page.get_text("words")` returns each word with its bounding box (`x0, y0, x1, y1`, in PDF points, origin top-left) plus block, line and word numbers, so reading order can be reconstructed.

A test on `02_1` p. 10 (black and white) and `26_2_I_1` p. 41 (colour) drew the extracted boxes over the rendered page: they align closely with the scanned text in both.

```python
import pymupdf

doc = pymupdf.open("CRLB_02_1_links-cxVmajEMUVTrFvcJZBinvpab.pdf")
page = doc[9]  # page 10
for x0, y0, x1, y1, text, block_no, line_no, word_no in page.get_text("words"):
    ...
```

Sample output (coordinates rounded):

| File     | Page | Page size (pt) | Words | First words: `[x0, y0, x1, y1] text (block, line, word)`                                                                        |
| -------- | ---- | -------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------- |
| 02_1     | 10   | 432 × 720      | 325   | `[70.3, 94.9, 80.9, 102.4] 26. (0,0,0)`, `[85.5, 94.9, 92.9, 102.4] B. (0,0,1)`, `[96.0, 94.9, 118.0, 102.4] Croce, (0,0,2)`    |
| 26_2_I_1 | 41   | 484.1 × 721.2  | 653   | `[336.7, 29.8, 338.9, 36.3] I (0,0,0)`, `[339.9, 29.8, 397.5, 36.3] NTRODUCTION (0,0,1)`, `[23.0, 52.4, 33.9, 62.0] he (1,0,0)` |

### Proposed storage: SQLite

A single file, no server, with built-in full-text search (FTS5). Estimated size: ~5,000 pages and 2–3 million words, a few hundred MB.

```
documents(id, filename, volume)
pages(id, document_id, page_no, width, height)        -- in PDF points
words(id, page_id, block_no, line_no, word_no, text, x0, y0, x1, y1)
lines_fts  (FTS5: line text + page_id/line reference)  -- for search
```

- `words` holds the coordinates needed for highlighting.
- `lines_fts` holds whole lines for phrase search. A hit yields a page and line; `words` yields the boxes to highlight.
- Corrections from a validation tool go in a separate table, so the original OCR is never overwritten.
- Storing coordinates also as fractions of the page size (0–1) lets a web viewer (e.g. PDF.js with an overlay) draw boxes at any zoom level without conversion.

### Points to watch

- **Page frame:** `02_1` reports 436×722 pt in `pdfinfo` (MediaBox) but PyMuPDF uses 432×720 (CropBox). Pick one convention and store it, or highlights in the viewer will be slightly off.
- **Small caps are split:** "INTRODUCTION" is extracted as `I` + `NTRODUCTION`; search should be tolerant of this.
- **Soft hyphens:** ABBYY uses soft hyphens at line breaks (`National\xad` / `museum`). Store them as they are and normalise them in the search text.
- **No OCR confidence:** ABBYY does not store recognition confidence in the PDF, so a validation tool cannot prioritise doubtful words from this data alone.
- **OCR quality is fixed:** the text is what ABBYY recognised in 2013–2015, errors included. Re-OCR with a modern engine is only worth it if the error rate turns out to be high.
- **Coordinates are tied to these exact PDFs:** if a file is re-processed (as happened with the repaired versions of `09` and `19_1`), coordinates may shift and extraction must be redone.

See also [NER_plan.md](NER_plan.md) for named entity recognition on top of this text database.
