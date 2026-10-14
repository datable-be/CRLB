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

See also [NER.md](NER.md) for named entity recognition on top of this text database.

## OCR quality test

A test of the quality of the existing OCR text layer on hand-corrected specimen pages, how to interpret the results, and whether re-running the OCR is advisable.

### Summary

- Overall character error rate (CER) is **5.4%**, but **59% of all errors are superfluous spaces** (e.g. `M useum`, `p r o v e n a n c e`).
- Without those spaces, quality is fairly even across volumes: roughly **1–2.5% CER**.
- The OCR batch (2013 vs 2014) makes no visible difference; the typography of each volume does.
- The superfluous spaces are encoded in ABBYY's text layer itself; they are not an artefact of text extraction.
- Advice: do not re-run the OCR yet. First repair the existing OCR (spaces, `I` → `1`), then compare a few engines on the corrected specimen pages.

### Method

#### Specimens

Two catalogue pages and two index pages per volume, drawn at random (seed 42) from pages with at least 50 words, with `scripts/OCR/sample_specimens.py` (`make sample_specimens`):

| Volume | Catalogue                        | Index                    |
| ------ | -------------------------------- | ------------------------ |
| 02     | `02_1_links` p. 313, 380         | `02_index` p. 18, 28     |
| 19_2   | `19_2_links` p. 77, 195          | `19_2_index` p. 10, 20   |
| 26_2_I | `26_2_I_1_querylink` p. 393, 425 | `26_2_I_Index` p. 28, 43 |

Catalogue pages are taken from the bookmark whose title contains "catalog" up to the next bookmark at the same or a higher level; index files are sampled in full. Each specimen gets `page.png`, `ocr.txt` and `gt.txt` (a copy of the OCR text, corrected by hand against the page image). All output stays local in `doc/CRLB_pdfs/specimens` (gitignored).

#### Analysis

`scripts/OCR/analyse_specimens.py` (`make analyse_specimens`) compares `gt.txt` with `ocr.txt` for every corrected specimen:

- Both texts are normalised: soft hyphens at line ends are joined, whitespace and line breaks are collapsed; case and punctuation are kept.
- **CER**: character edit distance / ground-truth characters, split into substitutions, insertions and deletions.
- **CER loose**: the same without case and punctuation.
- **WER**: word edit distance / ground-truth words.
- Errors are pooled before computing rates per group (file, OCR year, section).
- The most common confusions (adjacent edits merged) are written to `confusions.csv`.

### Results

#### Per specimen

| Specimen           | Year | Section   | GT chars | Char errors | Subst. | Ins. | Del. | CER   | CER loose | WER   |
| ------------------ | ---- | --------- | -------- | ----------- | ------ | ---- | ---- | ----- | --------- | ----- |
| 02_1_links p. 313  | 2013 | catalogue | 2739     | 61          | 38     | 19   | 4    | 2.2%  | 1.3%      | 10.5% |
| 02_1_links p. 380  | 2013 | catalogue | 2669     | 59          | 40     | 11   | 8    | 2.2%  | 1.6%      | 8.2%  |
| 19_2_links p. 77   | 2013 | catalogue | 3410     | 188         | 45     | 100  | 43   | 5.5%  | 3.7%      | 33.9% |
| 19_2_links p. 195  | 2013 | catalogue | 3635     | 244         | 63     | 158  | 23   | 6.7%  | 5.5%      | 42.3% |
| 26_2_I_1 p. 393    | 2014 | catalogue | 4407     | 440         | 34     | 389  | 17   | 10.0% | 9.3%      | 91.6% |
| 26_2_I_1 p. 425    | 2014 | catalogue | 4238     | 228         | 36     | 176  | 16   | 5.4%  | 4.8%      | 42.6% |
| 02_index p. 18     | 2013 | index     | 1478     | 19          | 11     | 2    | 6    | 1.3%  | 0.8%      | 7.5%  |
| 02_index p. 28     | 2013 | index     | 2333     | 33          | 18     | 2    | 13   | 1.4%  | 0.7%      | 6.8%  |
| 19_2_index p. 10   | 2013 | index     | 3375     | 333         | 32     | 294  | 7    | 9.9%  | 10.5%     | 97.2% |
| 19_2_index p. 20   | 2013 | index     | 2636     | 223         | 15     | 195  | 13   | 8.5%  | 8.9%      | 75.7% |
| 26_2_I_Index p. 28 | 2014 | index     | 3240     | 86          | 69     | 14   | 3    | 2.7%  | 2.8%      | 18.7% |
| 26_2_I_Index p. 43 | 2014 | index     | 3193     | 95          | 74     | 14   | 7    | 3.0%  | 3.2%      | 21.3% |

#### Per group

| Group              | Specimens | CER  | CER loose | WER   |
| ------------------ | --------- | ---- | --------- | ----- |
| **All**            | 12        | 5.4% | 4.9%      | 42.4% |
| 02_1_links         | 2         | 2.2% | 1.5%      | 9.4%  |
| 02_index           | 2         | 1.4% | 0.8%      | 7.1%  |
| 19_2_index         | 2         | 9.2% | 9.8%      | 87.2% |
| 19_2_links         | 2         | 6.1% | 4.6%      | 38.2% |
| 26_2_I_1_querylink | 2         | 7.7% | 7.1%      | 67.2% |
| 26_2_I_Index       | 2         | 2.8% | 3.0%      | 20.0% |
| OCR year 2013      | 8         | 5.2% | 4.5%      | 38.0% |
| OCR year 2014      | 4         | 5.6% | 5.4%      | 49.3% |
| Catalogue          | 6         | 5.8% | 4.8%      | 42.5% |
| Index              | 6         | 4.9% | 5.0%      | 42.3% |

With only two pages per file, per-file figures are indicative.

#### Most common confusions

| Ground truth → OCR                                          | Count   | Interpretation                                         |
| ----------------------------------------------------------- | ------- | ------------------------------------------------------ |
| `` → ` `                                                    | 1192    | Superfluous space                                      |
| `I` → `1`                                                   | 128     | Capital I / Roman numeral read as digit                |
| `- ` → ``                                                   | 57      | Transcription convention, not an OCR error (see below) |
| `o` → `0`                                                   | 19      | Classic confusion                                      |
| `s` → `S`                                                   | 17      | Old typography (ligature)                              |
| `s` → `f`                                                   | 15      | Long s / ligature                                      |
| `ct` → `d`                                                  | 7       | `ct` ligature                                          |
| `l` → `i`                                                   | 5       | Classic confusion                                      |
| `rn` → `m`                                                  | 3       | Classic confusion                                      |
| `PROVENANCE` → `p r o v e n a n c e `                       | 3       | Letter-spaced small caps heading                       |
| `EXHIBITED`, `LITERATURE`, `COPY` → letter-spaced lowercase | several | Same                                                   |

### Interpretation

#### 1. Superfluous spaces dominate

- 1,192 of 2,009 character errors (59%) are inserted spaces.
- They are concentrated on the four worst pages: `26_2_I_1` p. 393, both `19_2_index` pages and the `19_2_links` pages. The other files have very few.
- **They come from ABBYY, not from text extraction.** The spaces are actual characters in the PDF text layer: on `26_2_I_1` p. 393 there are 1,100 space characters for 727 real words. Of three extractors compared (PyMuPDF, pdftotext, pypdf), PyMuPDF adds the fewest spaces:

| Specimen           | GT words | PyMuPDF | pdftotext | pypdf | Space chars in text layer |
| ------------------ | -------- | ------- | --------- | ----- | ------------------------- |
| 02_1_links p. 313  | 467      | 485     | 531       | 505   | 475                       |
| 02_1_links p. 380  | 463      | 474     | 502       | 494   | 469                       |
| 19_2_links p. 77   | 560      | 659     | 745       | 790   | 621                       |
| 19_2_links p. 195  | 597      | 750     | 986       | 962   | 714                       |
| 26_2_I_1 p. 393    | 727      | 1123    | 2491      | 2108  | 1100                      |
| 26_2_I_1 p. 425    | 720      | 896     | 1593      | 1298  | 872                       |
| 02_index p. 18     | 226      | 229     | 230       | 232   | 215                       |
| 02_index p. 28     | 382      | 381     | 386       | 386   | 361                       |
| 19_2_index p. 10   | 493      | 781     | 1925      | 1474  | 751                       |
| 19_2_index p. 20   | 423      | 616     | 1198      | 924   | 580                       |
| 26_2_I_Index p. 28 | 454      | 468     | 477       | 462   | 441                       |
| 26_2_I_Index p. 43 | 432      | 445     | 442       | 505   | 421                       |

- **Letter-spaced headings** are the clearest case: in 26_2, `PROVENANCE` becomes `p r o v e n a n c e`, and likewise `EXHIBITED`, `LITERATURE` and `COPY`. ABBYY reads each letter as a separate word and also lowercases the small caps.

#### 2. Without the spaces, quality is fairly even

Rough estimate (character errors minus insertions, which are mostly spaces):

| File                         | CER  | CER without inserted spaces (approx.) |
| ---------------------------- | ---- | ------------------------------------- |
| 02_1 (catalogue, 2013)       | 2.2% | ~1.7%                                 |
| 02_index (2013)              | 1.4% | ~1.3%                                 |
| 19_2_links (catalogue, 2013) | 6.1% | ~2.5%                                 |
| 19_2_index (2013)            | 9.2% | ~1.1%                                 |
| 26_2_I_1 (catalogue, 2014)   | 7.7% | ~1.2%                                 |
| 26_2_I_Index (2014)          | 2.8% | ~2.4%                                 |

The OCR batch (2013 vs 2014) makes no visible difference. What matters is the typography of each volume: letter spacing, small caps, ligatures.

#### 3. WER is misleading here

Overall WER is 42% against a CER of 5.4%. One superfluous space turns one correct word into two wrong ones, so WER heavily exaggerates the problem.

#### 4. Other systematic errors

- **`I` → `1` (128×):** most likely Roman numerals or capital I in references. Systematic, so fixable with context rules.
- **`- ` → ``(57×, plus 5× `-` →``):** not an OCR error. The OCR has a soft hyphen at the line break, which the analysis removes; `gt.txt` has a normal hyphen there, which stays. Agreeing on one convention, or having the analysis also join hyphens at line ends, removes these errors.
- **Old typography (2013 volumes):** `s` → `S`, `s` → `f`, `ct` → `d`, `st` → `U` are ligature and long-s problems. Small in number.
- **Classic confusions:** `o` → `0`, `l` → `i`, `rn` → `m`.

#### Consequences for the planned work

- **Search:** superfluous spaces break phrase search; "Museum" will not find `M useum`.
- **Coordinates and highlighting:** not affected, apart from one word being split over two boxes.
- **NER** (see [NER.md](NER.md)): the catalogue headings (_Provenance_, _Literature_, …) used to split entries are exactly the ones that come out letter-spaced. Rule-based segmentation must handle that, or the spacing must be repaired first.
- **Repairing the spacing** looks promising because it is so systematic: join runs of single letters (`p r o v e n a n c e`), and join two fragments when together they form a known word (`M useum`). Such a repair can be measured against the corrected specimens.

### Should the OCR be re-run?

Not yet. First try repairing the existing OCR, and let a small comparison on the corrected specimen pages decide whether new OCR is worth it.

#### Why not re-run straight away

- **Character recognition is already fairly good.** Without superfluous spaces the error rate is roughly 1–2.5%. A modern engine might get below 1%, but the gain is modest.
- **The spaces are systematic** (letter spacing, small caps), so a repair step may remove much of the problem cheaply, and its effect can be measured exactly.
- **The input for new OCR is limited.** Re-OCR would use the images inside the PDFs. In `02_1` those are already reduced to black and white (1-bit JBIG2); in the MRC files the background is only 150 dpi. Any engine does worse on that than on the original scans.

#### Options

Requirements: **word coordinates** (validation tool, highlighting) and preferably **local processing**.

| Option                                     | Strengths                                                                                              | Weaknesses                                                                                                                                             |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **ABBYY (current version)**                | Strong on printed text and layout; exports word coordinates (XML/ALTO)                                 | Commercial; probably no large gain over FR11 on these images                                                                                           |
| **Tesseract 5**                            | Free, local, hOCR/ALTO with word boxes                                                                 | Weaker on small caps, letter spacing and mixed layouts; needs preprocessing                                                                            |
| **Transkribus**                            | Good layout analysis, printed-text models, trainable on own corrected pages, PAGE XML with coordinates | Cloud service (data leaves the machine), paid credits; main strength is handwriting                                                                    |
| **Kraken / eScriptorium**                  | Open source, trainable, local, with coordinates                                                        | More setup work                                                                                                                                        |
| **Vision-language models** (LLM-based OCR) | Read very well in context; would correctly produce "Provenance"                                        | Coordinates weak or missing; risk of silently "improving" text, which is dangerous for scholarly validation; cloud unless an open model is run locally |

### Repairing the existing OCR

Repairs are done with a **deterministic script, not an LLM**, to avoid introducing hallucinations, which would be worse than plain OCR errors.

#### Space repair only removes spaces

Superfluous spaces are the biggest problem (59% of errors). Repairing them only **removes spaces between existing tokens**: no letter is ever changed, added or dropped. This is checked in code after every run: with all whitespace stripped, the text before and after must be identical. A wrong join (`of the` → `ofthe`) is still possible, but it is measurable and traceable, and never an invented word.

#### Rules for joining tokens

In increasing order of risk:

1. **Letter-spaced runs:** three or more single-letter tokens in a row (`p r o v e n a n c e`) are joined into one word. Legitimate single letters (`a`, `I`, initials like `J. B.`) almost never occur in runs of three or more.
2. **Gaps between words:** per line, the gap between two fragments of the same word (`M` | `useum`) is usually smaller than a real gap between words. Joining below a per-line threshold uses the image geometry (the word coordinates) instead of guessing at language.
3. **Lexicon check:** join two fragments if together they form a known word and separately they do not (or one of them is a single capital). The lexicon is built **from the corpus itself**: words such as "Museum", "Kunsthistorisches" and proper names appear correctly elsewhere in the ~5,000 pages. This covers all languages in the text without separate dictionaries.

Rules 2 and 3 can confirm each other: joining only when both agree is the most conservative option.

#### Other errors: flag rather than fix

- **`I` → `1`:** fix automatically only where unambiguous, such as a `1` inside a word made of letters. In ambiguous contexts (`1` vs Roman `I` in a reference), **flag** the case for the validation tool instead of guessing.
- **Ligatures** (`BieSt`, `ct` → `d`): too few to justify rules; flag at most.
- **Hyphen difference:** not an OCR repair but a transcription convention, handled in the analysis script.

#### Safeguards

- **Never overwrite the original OCR.** The repaired version is a separate layer, linked to the original word IDs. A joined word gets the combined box of its parts.
- **Log every change** (rule, tokens) for later review in the validation tool.
- **Measure both sides against the ground truth:** errors fixed and errors introduced. A rule only stays if it clearly improves the result.
- **Avoid tuning on the same pages:** with only 12 pages, adjust the rules on half and check them on the other half, or correct a few extra pages as a test set.

#### Possible role for an LLM

At most as a **judge between options generated by the script** ("join these two tokens: yes or no?"), with its output checked against the same invariant so it cannot add text. This is probably unnecessary: the corpus lexicon plus coordinates should cover most cases.

### Next steps

1. **Ask RKD whether the original scans still exist** (TIFF, greyscale or colour, ≥300 dpi). This is the biggest factor for any new OCR.
2. **Repair the existing OCR** as described above: join superfluous spaces, fix unambiguous `I` → `1` and flag the rest, agree on the hyphen convention. Add a "CER without spaces" metric to the analysis and measure again.
3. **Compare engines on the same 12 pages,** for example Tesseract (free, local) plus a current ABBYY version or a Transkribus trial, against the ground truth. Measure CER, CER without spaces, and whether word coordinates are available.
4. **Only re-run OCR for all ~5,000 pages** if an engine clearly beats the repaired version. Even then the PDFs and their hand-made RKD links can stay as they are: the new text with coordinates goes into the database, not into the PDF.
