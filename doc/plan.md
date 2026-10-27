# Plan

## Step 1: text database

### Goal

Turn every CRLB PDF into a SQLite database of raw text. The text is stored per page and per word, with coordinates, so that later steps (OCR correction, entry segmentation, extraction, validation against the PDF) can build on it without going back to the PDFs for text.

This step stores the text exactly as it is in the PDF. It does not correct, normalise or segment anything.

### Source material

The material is in `data/` (outside git), unpacked from the Rubenshuis download:

- `data/CRLB_borndigital/`: born-digital PDFs (InDesign exports, 2015–2025). The text layer is the real text and is assumed to be correct.
- `data/CRLB_digitized/`: scanned volumes. Three kinds of files:
    - PDFs with an invisible OCR text layer made by ABBYY FineReader 11 (2013–2014). See [OCR.md](OCR.md) for their structure and quality.
    - `Boekdeel_*.docx`: page-by-page text conversions of the scanned volumes, from SharePoint, exported through Google Drive. Their OCR origin is unknown.
    - `Origineel*/`: the original scans (300 dpi colour JPEG/TIFF) for VI, XIII (3), XV, XXII (1), XXVI (1) and XXVI (2.1–2.3).
- `doc/CRLB_pdfs/`: the ABBYY PDFs of XXVI (2.1) and XXVI (2.2) (`CRLB_26_2_*`), which are not in the download.

The folder a file is in does not reliably say what it is:

- `CRLB_borndigital/CRLB_13/CRLB_13_3*.pdf` is ABBYY OCR (December 2014), not born-digital. It matches the 408 scans in `CRLB_digitized/CRLB_13/Origineel_III`.
- `CRLB_digitized/CRLB_14/` contains part XIX (`CRLB_19_1_*`, `CRLB_19_2_*`).
- `CRLB_borndigital/CRLB_22_2/` also contains 22_3 and 22_4.

**Step 1 covers the PDFs only.** Both born-digital and OCR PDFs go through the same procedure; only `text_source` differs. The Word files and the scans of volumes without a PDF are a separate step (see "Volumes without a PDF").

### Naming and identification

Filenames follow `CRLB_<part>_<n>_<m>`:

- `<part>` is the CRLB part as an Arabic number (`02` = II, `26` = XXVI).
- The levels below are used inconsistently. They can be a sub-part (`19_3` = XIX (3), `05_2` = V (2)), a physical volume of one book (`05_1_I` / `05_1_II`, whose InDesign titles are "Vol-one" and "Vol-two"), or both (`26_2_I_1` = XXVI (2.1), volume 1).
- For XXVI (2) the mapping is confirmed by page counts: `26_2_I_1` (454 pages) and `26_2_I_2` (275) match the scans `Origineel_XXVI_2_I_I` (454) and `_I_II` (276); `26_2_II_1` (452) and `26_2_II_2` (244) match `_II_I` (452) and `_II_II` (244).
- For `02_1`/`02_2`, `18_1`, `21_1`/`21_2` and `23_1`/`23_2`/`23_3` it is not yet clear whether the number is a sub-part or a physical volume. The colophons will settle it.

A book can therefore be spread over several files. The unit of storage is **the PDF file**. The CRLB part and the physical volume are attributes of the file, recorded in a manifest.

### File selection

The download contains duplicates. One file is selected per physical volume:

| Present                                | Selected             | Reason                                                                       |
| :------------------------------------- | :------------------- | :--------------------------------------------------------------------------- |
| `X.pdf` and `X_links RKD Research.pdf` | the `_links` version | same PDF (same creation date and page count) with RKDimages links added      |
| `X.pdf` and `X_unlocked.pdf`           | `X.pdf`              | the unlocked file is an iLovePDF copy; the original opens without a password |
| `CRLB_27_2_PROEF.pdf`                  | it, flagged as proof | the only version of XXVII (2)                                                |

Index files:

- The ABBYY index files (`*_index-*.pdf` in `CRLB_digitized`, `CRLB_13_3_Index.pdf`, `CRLB_26_2_I_Index`) are separate scans and are included as `section = 'index'`.
- The born-digital index files (`*_index.pdf`, made with PDF-XChange in June 2026) are **excerpts** of their main PDF: the page labels of `CRLB_11_2_index.pdf` run from 291 to 389, the end of `CRLB_11_2_II.pdf`. They are included as `section = 'index'` with `excerpt_of` set to the main file, so it is known that their pages also occur there. They are convenient as a ready-made index for NER.

This gives about 65 PDFs: 22 born-digital parts or sub-parts (47 files including indexes) and 12 ABBYY parts or sub-parts (about 25 files).

### Manifest

`data_manifest/documents.csv` (in git, contains no copyrighted content) describes each selected file:

| Column        | Example                                                            | Note                                                             |
| :------------ | :----------------------------------------------------------------- | :--------------------------------------------------------------- |
| `path`        | `data/CRLB_borndigital/CRLB_05/CRLB_05_1_I_links RKD research.pdf` | relative to the project root                                     |
| `part`        | `V (1)`                                                            | CRLB part as printed: `II`, `XIX (3)`, `XXVI (2.1)`              |
| `volume`      | `1`                                                                | physical volume within the part; empty if the part is one volume |
| `section`     | `main`                                                             | `main` or `index`                                                |
| `text_source` | `born_digital`                                                     | `born_digital` or `ocr`                                          |
| `excerpt_of`  |                                                                    | for born-digital index excerpts: `path` of the main file         |
| `note`        |                                                                    | free text, e.g. `proof`, `part designation unverified`           |

The build fails if a manifest row has no file, if a `path` occurs twice, or if `excerpt_of` does not refer to another row.

A second manifest, `data_manifest/parts.csv`, describes the CRLB parts themselves, for citations ("CRLB XIX (4), No. 22") and for Rubens Online:

| Column    | Example                               | Note                                |
| :-------- | :------------------------------------ | :---------------------------------- |
| `part`    | `XIX (4)`                             | as in `documents.csv`               |
| `title`   | `Portraits after Existing Prototypes` | title of the part as printed        |
| `year`    | `2016`                                | year of publication                 |
| `authors` |                                       | as on the title page, `;`-separated |

Every `part` in `documents.csv` must occur in `parts.csv`; the build fails otherwise. Title, year and authors are filled in from the title pages and colophons, which also settles the open sub-part/volume questions.

`text_source` is set from the PDF metadata, not from the folder: `Producer` "ABBYY FineReader 11", or "3-Heights" with `Creator` "Paperless" (the repaired files 09 and 19_1), or an empty producer (03) means `ocr`; an InDesign `Creator` means `born_digital`. The build re-checks this and warns on a mismatch.

The manifest is written once by hand (with a helper script that lists candidates and metadata, printing no text) and checked by the user.

### Output

Two SQLite files, both in `data/` and therefore outside git:

| File               | Content                                                                          | Shareable                               |
| :----------------- | :------------------------------------------------------------------------------- | :-------------------------------------- |
| `data/crlb.sqlite` | documents, pages, words, links, bookmarks, full-text index                       | the text may be, the PDFs are not in it |
| `data/pdfs.sqlite` | the PDF files as raw bytes, in the [sqlar](https://sqlite.org/sqlar.html) format | no (copyright)                          |

`crlb.sqlite` refers to a PDF by its path and SHA-256 hash. When a later step needs the PDF itself (to render a page or highlight a word), it attaches `pdfs.sqlite` and checks the hash, so the coordinates are guaranteed to belong to that exact file.

### Schema of `pdfs.sqlite`

The standard sqlar table, so the archive can be inspected and unpacked with `sqlite3 -A`:

```sql
CREATE TABLE sqlar (
    name  TEXT PRIMARY KEY,  -- path, as in the manifest
    mode  INT,               -- file mode, 0o100644
    mtime INT,               -- file modification time, Unix seconds
    sz    INT,               -- original size in bytes
    data  BLOB               -- the file; stored uncompressed (length = sz)
);
```

PDFs barely compress, so they are stored uncompressed. sqlar treats `length(data) = sz` as uncompressed.

Size: the selected PDFs total roughly 6–7 GB. The largest file (`CRLB_11_1_II.pdf`, 823 MB) is below SQLite's default maximum value size of 1,000,000,000 bytes. To avoid holding such files in memory twice, the bytes are written with incremental blob I/O (`INSERT ... zeroblob(sz)`, then `Connection.blobopen` and chunked writes), and the hash is computed in the same pass.

### Schema of `crlb.sqlite`

```sql
PRAGMA foreign_keys = ON;

-- One row per build, for provenance.
CREATE TABLE extraction_runs (
    id            INTEGER PRIMARY KEY,
    started_at    TEXT NOT NULL,      -- ISO 8601, UTC
    tool          TEXT NOT NULL,      -- 'pymupdf'
    tool_version  TEXT NOT NULL,      -- pymupdf.__version__ / MuPDF version
    options       TEXT NOT NULL       -- JSON: extraction flags and settings
);

-- One row per CRLB part, from data_manifest/parts.csv.
CREATE TABLE parts (
    part           TEXT PRIMARY KEY,       -- 'XIX (4)', 'XXVI (2.1)'
    title          TEXT,
    year           INTEGER,
    authors        TEXT                    -- ';'-separated, as on the title page
);

-- One row per PDF file.
CREATE TABLE documents (
    id             INTEGER PRIMARY KEY,
    run_id         INTEGER NOT NULL REFERENCES extraction_runs(id),
    path           TEXT NOT NULL UNIQUE,   -- = sqlar.name in pdfs.sqlite
    sha256         TEXT NOT NULL,          -- hex digest of the PDF bytes
    size           INTEGER NOT NULL,       -- bytes
    part           TEXT NOT NULL REFERENCES parts(part),  -- from the manifest
    volume         TEXT,                   -- from the manifest
    section        TEXT NOT NULL CHECK (section IN ('main', 'index')),
    text_source    TEXT NOT NULL CHECK (text_source IN ('ocr', 'born_digital')),
    excerpt_of     INTEGER REFERENCES documents(id),
    note           TEXT,                   -- from the manifest
    pdf_version    TEXT,                   -- e.g. 'PDF-1.4'
    title          TEXT,                   -- PDF metadata, verbatim
    producer       TEXT,
    creator        TEXT,
    creation_date  TEXT,                   -- PDF date string, verbatim
    mod_date       TEXT,
    page_count     INTEGER NOT NULL
);

-- One row per page.
CREATE TABLE pages (
    id           INTEGER PRIMARY KEY,
    document_id  INTEGER NOT NULL REFERENCES documents(id),
    page_index   INTEGER NOT NULL,    -- 0-based index in the PDF
    page_label   TEXT,                -- printed page number from /PageLabels, if any
    rotation     INTEGER NOT NULL,    -- /Rotate
    width        REAL NOT NULL,       -- CropBox width (page.rect), points
    height       REAL NOT NULL,       -- CropBox height (page.rect), points
    mediabox     TEXT NOT NULL,       -- JSON [x0, y0, x1, y1]; differs from the CropBox in some files
    text         TEXT NOT NULL,       -- raw page text, see "Extraction"
    UNIQUE (document_id, page_index)
);

-- One row per word, as returned by page.get_text("words").
CREATE TABLE words (
    id        INTEGER PRIMARY KEY,   -- stable id; later corrections refer to it
    page_id   INTEGER NOT NULL REFERENCES pages(id),
    block_no  INTEGER NOT NULL,
    line_no   INTEGER NOT NULL,
    word_no   INTEGER NOT NULL,
    x0        REAL NOT NULL,         -- page coordinates, points, origin top left of page.rect
    y0        REAL NOT NULL,
    x1        REAL NOT NULL,
    y1        REAL NOT NULL,
    text      TEXT NOT NULL,
    font      TEXT NOT NULL,         -- font name of the word's dominant span, e.g. 'PalatinoLTStd-Bold'
    size      REAL NOT NULL,         -- font size of that span, points
    flags     INTEGER NOT NULL,      -- PyMuPDF span flags: 1 superscript, 2 italic, 16 bold, ...
    styles    INTEGER NOT NULL       -- number of distinct (font, size, flags) spans in the word; > 1 = mixed
);
CREATE INDEX words_page ON words(page_id);

-- One row per link annotation, as returned by page.get_links().
CREATE TABLE links (
    id           INTEGER PRIMARY KEY,
    page_id      INTEGER NOT NULL REFERENCES pages(id),
    kind         TEXT NOT NULL,      -- 'uri', 'goto', 'named', 'launch', 'none', ...
    uri          TEXT,               -- for 'uri', verbatim (broken URIs included)
    target_page  INTEGER,            -- for 'goto', 0-based
    x0           REAL NOT NULL,
    y0           REAL NOT NULL,
    x1           REAL NOT NULL,
    y1           REAL NOT NULL
);
CREATE INDEX links_page ON links(page_id);

-- Bookmarks (outline), as returned by doc.get_toc(simple=True).
CREATE TABLE toc (
    id           INTEGER PRIMARY KEY,
    document_id  INTEGER NOT NULL REFERENCES documents(id),
    position     INTEGER NOT NULL,   -- order in the outline, 0-based
    level        INTEGER NOT NULL,   -- 1 = top level
    title        TEXT NOT NULL,
    page_index   INTEGER             -- 0-based; NULL if the bookmark has no target
);

-- Full-text search on the page text.
CREATE VIRTUAL TABLE pages_fts USING fts5(
    text,
    content = 'pages',
    content_rowid = 'id',
    tokenize = 'unicode61 remove_diacritics 2'
);
```

Notes on the schema:

- Part and file are separate on purpose: `SELECT ... WHERE part = 'XXVI (2.1)'` gives all files of that part.
- Searches over the whole corpus exclude excerpts (`WHERE excerpt_of IS NULL`) to avoid counting index pages twice.
- `pages.text` and `words` both come from the same PyMuPDF extraction of the same page. `words` is the basis for coordinates and corrections; `pages.text` is the convenient form for reading and searching.
- Later layers (OCR corrections, entries, extracted fields) go into **new tables** that refer to `words.id`, `pages.id` or `documents.id`. The tables of this step are never updated after the build.
- The `links` table matters beyond this step: in the `_links` files each RKDimages link marks a catalogue entry and carries its RKD permalink.
- The `toc` table is needed to find the catalogue and index sections (see `catalogue_pages` in `scripts/OCR/sample_specimens.py`). Several born-digital PDFs have no bookmarks; for those the sections must be found another way in a later step.

### Extraction

For each document, in manifest order:

1. Stream the file into `pdfs.sqlite` (incremental blob I/O), computing SHA-256 and size on the way.
2. Open the PDF with PyMuPDF from the same path and verify that its hash is unchanged since step 1, so the text comes from exactly the stored file.
3. Insert the `documents` row with manifest fields and PDF metadata.
4. Insert the `toc` rows from `doc.get_toc(simple=True)` (PyMuPDF page numbers are 1-based, -1 for none; store 0-based, NULL for none).
5. For each page:
    - insert the `pages` row: `page.get_label()` (NULL if empty), `page.rotation`, `page.rect`, `page.mediabox`, and the text from `page.get_text("text", sort=False)`;
    - insert `words` from `page.get_text("words", sort=False)`, with the typography of each word (see below);
    - insert `links` from `page.get_links()`.
6. Commit once per document.

After all documents: resolve `excerpt_of` paths to document ids, fill the FTS index (`INSERT INTO pages_fts(pages_fts) VALUES ('rebuild')`) and run `ANALYZE`.

Extraction settings, also recorded in `extraction_runs.options`:

- `sort=False`: keep the order of the content stream. ABBYY and InDesign write the text in their own reading order; sorting by position can mix columns.
- Default text flags, **without** `TEXT_DEHYPHENATE`: soft hyphens (`\xad`) and line-end hyphens stay as they are.
- No normalisation (no NFC, no whitespace collapsing). That belongs to later steps.

Typography per word. `get_text("words")` gives no font information, so it is added from `page.get_text("dict", sort=False)` with the same flags. The `block_no` and `line_no` of a word refer to the same block and line in the `dict` output; within that line, the word gets the font, size and flags of the span that covers most of its characters (by bounding-box overlap), and `styles` counts how many different spans it overlaps. Typography is the main signal for segmentation (step 3): bold headings, notes in a smaller size, superscript note markers, italic locations and titles, and small caps, which ABBYY records as a capital in a larger size followed by letters in a smaller size (`P rov en a n ce`: 10.5 pt and 8.4 pt).

Expected size of `crlb.sqlite`: on the order of 20,000 pages and several million words, so probably 1–2 GB, mostly `words`. The exact number will be clear after the first build.

### Code

New directory `scripts/database/`:

- `schema.sql`: the two schemas above.
- `list_pdfs.py`: lists candidate PDFs under the given directories with page count, metadata, link and bookmark counts and the proposed `text_source`, as a starting point for the manifest. Prints no PDF text.
- `build_database.py`: command line `build_database.py <manifest> <out_dir>`.
    - Creates `<out_dir>/crlb.sqlite` and `<out_dir>/pdfs.sqlite`.
    - Refuses to run if either file exists (same behaviour as `sample_specimens.py`).
    - Prints only counts per document (pages, words, links per kind, bookmarks) and warnings. It never prints PDF text.
    - Functions (each with type annotations and a one-line docstring), roughly: `read_manifest`, `create_databases`, `store_pdf`, `insert_document`, `insert_toc`, `insert_page`, `build`, `main`.
- `pdf_store.py`: `open_pdf(conn, document_id) -> pymupdf.Document`, which reads the bytes from the attached `pdfs.sqlite`, checks the SHA-256 against `documents.sha256` and raises if they differ. This is the entry point for later validation work.

Project configuration:

- `pyproject.toml`: add `scripts/database` to pytest `pythonpath`, ruff `src` and ty `extra-paths`.
- `Makefile`: targets `list_pdfs` and `build_database: uv run scripts/database/build_database.py data_manifest/documents.csv data`; add them to `help`.
- No new dependencies: `sqlite3` and `hashlib` are in the standard library; FTS5 is included in Python's bundled SQLite.

### Tests

`tests/database/test_build_database.py`, using small PDFs generated in the test with PyMuPDF (text, a URI link, a GoTo link, bookmarks, page labels, metadata):

- each PDF ends up in `sqlar` with the original bytes, and `documents.sha256` matches;
- a path with spaces (as in `X_links RKD Research.pdf`) works;
- page, word, link and bookmark counts match what was generated;
- word coordinates match those of `page.get_text("words")` on the original;
- font, size and flags are right for bold, italic and superscript words, and a word with two styles gets `styles = 2`;
- soft hyphens survive unchanged in `pages.text` and `words.text`;
- `excerpt_of` is resolved to the right document id;
- the build fails for a `part` missing from `parts.csv`, and `parts` is filled from it;
- an FTS query finds a word on the right page;
- `open_pdf` returns the document, and raises after the stored bytes are altered;
- the build fails for a manifest row without a file, a duplicate path and a dangling `excerpt_of`;
- the build refuses to overwrite existing output.

Ruff, ruff format and ty must be clean.

### Verification on the real corpus

Run locally (`make build_database`); the output is counts only.

- Every manifest row is present, with `page_count` equal to the number of `pages` rows.
- `uri` link counts match the `list_pdfs.py` overview (e.g. 735 for `CRLB_12_I_links`, 3 identical query links for the `26_2_*_1` files, 0 for files without links).
- No `text_source` warnings.
- Spot check: for a few specimen pages from the OCR quality test, `pages.text` equals the `ocr.txt` from `sample_specimens.py` (same extraction), compared by a script that reports only equal/different.
- Spot check of coordinates: render one born-digital and one OCR page from `pdfs.sqlite` with the word boxes drawn on it and look at them locally.

### Out of scope for this step

- OCR correction (space repair, `I`/`1` and the other confusions): step 2.
- Splitting the text into sections, catalogue entries and fields: step 3.
- Extracting structured data from the fields.
- NER.
- Re-OCR of the scans.
- The validation interface.

## Step 2: OCR correction

### Goal

Improve the text of the OCR documents (`text_source = 'ocr'`) as far as possible **without an LLM**, measure the result, and only consider LLM-assisted correction if the measured quality is not sufficient.

The OCR quality test ([OCR.md](OCR.md)) showed that superfluous spaces are the main error: 1192 of 2009 errors on the specimens, with letter-spaced small-caps headings (`p r o v e n a n c e`) as a special case. Without the inserted spaces, CER drops from 1.4–9.2% to about 1.1–2.5% per file.

### Approach

The order is fixed:

1. **Step 2a, space repair:** deterministic, only removes characters. Always done.
2. **Measurement:** raw OCR against corrected OCR, against a quality threshold set beforehand.
3. **Step 2b, character substitutions** (`I`/`1`, `s`/`f`, ...): deterministic, only if the measurement shows it is worth it.
4. **Step 2c, LLM-assisted correction:** only if 2a and 2b together do not reach the threshold.

### Principles

- **Invariant of step 2a:** only whitespace and soft hyphens (`\xad`) are removed. With whitespace and soft hyphens stripped, the text of a page is identical before and after. The script checks this for every page and stops on a violation. "M useum" can become "Museum", never "Muse on".
- **The raw layer is never changed.** Corrections are a separate layer that refers to `words.id`, so the coordinates stay available and every change can be traced and undone.
- **Every change has a rule and a reason**, stored with it.
- **When in doubt, do not change; flag.** A missed correction is cheaper than a wrong one, because a wrong one is invisible afterwards.
- **No tuning on the test pages** (see "Measurement").

### Lexicon

The lexicon decides whether a joined form is a real word. It is built from the corpus itself, so it contains the vocabulary of the CRLB: names ("Rooses", "Ovid"), places, Latin and Dutch titles, abbreviations ("repr.", "Met.").

Sources:

- **Born-digital documents** (`text_source = 'born_digital'`, `excerpt_of IS NULL`): the main source. Their text is correct.
- **The OCR document itself**: a word that occurs unsplit often enough in the same document (for example at least 5 times) is accepted as a joined form. This covers names that occur only in the old volumes. OCR tokens are only used to _accept_ a joined form, never to decide that a piece is a word, because a piece that is split the same way many times ("useum") would otherwise end up in the lexicon.

Building:

- Tokens are taken from `words.text`, NFC-normalised, with leading and trailing punctuation stripped and case folded (`casefold()`). The original case is kept in the output.
- A word that ends a line with a soft hyphen is joined to the first word of the next line before counting. A word ending a line with a hard hyphen is not counted (it may be a compound: "Rubens-" + "House").
- Tokens containing digits are not counted.
- Besides word counts, **bigram counts** (two consecutive words on one line) are stored, to compare "a part" with "apart".

Tables in `crlb.sqlite`:

```sql
CREATE TABLE lexicon (
    form          TEXT PRIMARY KEY,   -- casefolded, NFC
    born_digital  INTEGER NOT NULL,   -- count in born-digital documents
    ocr           INTEGER NOT NULL    -- count in OCR documents (for statistics only)
);

CREATE TABLE bigrams (
    first         TEXT NOT NULL,
    second        TEXT NOT NULL,
    born_digital  INTEGER NOT NULL,
    PRIMARY KEY (first, second)
);
```

The lexicon is rebuilt from scratch together with the correction; its options are recorded in the correction run.

### Rules of step 2a

The rules work per line, on the words of `words` in their stored order (`block_no`, `line_no`, `word_no`). A join always covers consecutive words. Tokens containing digits are never joined, because numbers (catalogue numbers, dimensions, dates) are data that must not change unnoticed.

**R1, letter-spaced runs.** A run of 3 or more single-letter tokens on one line (`p r o v e n a n c e`) is joined if the result is in the born-digital lexicon (case-insensitive). If it is not, the run is flagged. Case is not changed: the OCR has lowercase where the print has small caps; restoring that is not a space correction.

**R2, lexicon join.** For each window of 2 to 4 consecutive tokens on a line (longest window first, left to right), the tokens are joined if:

- the joined form (without surrounding punctuation) is in the lexicon: born-digital count ≥ 1, or count in the same OCR document ≥ 5; and
- at least one of the pieces is **not** a word: not in the born-digital lexicon, with single letters other than `a`, `A` and `I` counting as non-words ("M useum", "Mu seum", "Museu m").

If all pieces are words ("a part", "in to", "may be"), the tokens are only joined if the joined form is clearly more frequent in the born-digital text than the bigram (for example 20 times as frequent, both counts from the born-digital lexicon). Otherwise the case is flagged.

**R3, soft hyphen at line end.** A word that ends a line with `\xad` is joined to the first word of the next line in the same block. The soft hyphen is removed. Hard hyphens are never removed.

**Gap between word boxes (to be investigated first).** A superfluous ABBYY space may be narrower than a real space on the same line. Before the rules are finalised, the gaps are measured on the development pages (see "Measurement"): the distribution of gaps at superfluous spaces against real spaces, relative to the font size (word box height). If the distributions separate well, a small gap becomes an extra condition for R2, or allows R2 when all pieces are words. If not, the gap is not used.

The thresholds (minimum count in the same document, frequency ratio, maximum window, gap) are options of the script, recorded in the run, and tuned on the development pages only.

### Schema of the correction layer

```sql
-- One row per correction run.
CREATE TABLE correction_runs (
    id           INTEGER PRIMARY KEY,
    started_at   TEXT NOT NULL,     -- ISO 8601, UTC
    step         TEXT NOT NULL,     -- '2a', later '2b', '2c'
    based_on     INTEGER REFERENCES correction_runs(id),  -- NULL = raw layer
    version      TEXT NOT NULL,     -- git commit of the scripts
    options      TEXT NOT NULL      -- JSON: thresholds, lexicon options
);

-- The corrected text as a sequence of tokens. Every raw word of a corrected
-- document belongs to exactly one token per run; unchanged words get a token
-- with rule NULL, so the corrected page can be rebuilt from this table alone.
CREATE TABLE corrected_words (
    id             INTEGER PRIMARY KEY,
    run_id         INTEGER NOT NULL REFERENCES correction_runs(id),
    page_id        INTEGER NOT NULL REFERENCES pages(id),
    first_word_id  INTEGER NOT NULL REFERENCES words(id),
    last_word_id   INTEGER NOT NULL REFERENCES words(id),  -- = first_word_id if not joined
    text           TEXT NOT NULL,
    x0             REAL NOT NULL,   -- union of the boxes of the raw words
    y0             REAL NOT NULL,
    x1             REAL NOT NULL,
    y1             REAL NOT NULL,
    rule           TEXT,            -- 'R1', 'R2', 'R3' or NULL (unchanged)
    reason         TEXT             -- e.g. 'pieces: M|useum; lexicon bd=412'
);
CREATE INDEX corrected_words_run_page ON corrected_words(run_id, page_id);

-- Cases a rule considered but did not change.
CREATE TABLE correction_flags (
    id             INTEGER PRIMARY KEY,
    run_id         INTEGER NOT NULL REFERENCES correction_runs(id),
    page_id        INTEGER NOT NULL REFERENCES pages(id),
    first_word_id  INTEGER NOT NULL REFERENCES words(id),
    last_word_id   INTEGER NOT NULL REFERENCES words(id),
    rule           TEXT NOT NULL,
    candidate      TEXT NOT NULL,   -- the joined form that was not applied
    reason         TEXT NOT NULL    -- e.g. 'all pieces are words; ratio 3.1 < 20'
);

-- The run that later steps and exports use, per step. Steps 2, 3 and 4 can
-- each be run several times; older runs stay in the database for comparison.
CREATE TABLE active_runs (
    step     TEXT PRIMARY KEY,      -- '2' (correction), '3' (segmentation), '4:<field>' (extraction)
    run_id   INTEGER NOT NULL,      -- id in the run table of that step
    set_at   TEXT NOT NULL,         -- ISO 8601, UTC
    note     TEXT                   -- why this run was made active
);
```

`active_runs` is introduced here because step 2 is the first step with several runs; it is used the same way by steps 3 and 4. A run becomes active only by an explicit command, after its measurement, never automatically. For step 2 the active run is the last run of the chain (`based_on`), e.g. the 2b run built on the 2a run.

A join is a contiguous range of word ids, because words are stored in reading order and a join never crosses a block. The corrected page text is rebuilt from `corrected_words`: tokens joined by a space within a line, a newline between lines, an empty line between blocks. For a fair comparison, the raw page text is rebuilt from `words` in the same way.

### Measurement

**Ground truth.** The 12 hand-corrected specimen pages (6 files × 2 pages) are split once into a development set and a test set: per file one page each, chosen at random with a fixed seed and recorded in a file in git. Rules and thresholds are tuned on the 6 development pages only. The test pages are used once per version of the rules, for the final figures. If the test set turns out to be too small to decide, more pages are corrected by hand for it (not taken from the development set).

**Metrics on the specimens** (with `analyse_specimens.py`, extended to compare a corrected text with the ground truth):

- CER, CER loose and WER, raw and corrected;
- CER with all whitespace removed: must be equal for raw and corrected (check of the invariant, apart from soft hyphens);
- join precision: correct joins / all joins;
- join recall: superfluous spaces removed / all superfluous spaces in the ground truth;
- **errors introduced**: wrong joins. This is the most important number;
- per rule (R1, R2, R3) and per file.

**Metrics on the whole corpus** (no ground truth):

- number of joins and flags per rule and per document;
- the invariant holds for every page;
- a random sample of joins (for example 200, with a fixed seed) and of flags is written to a CSV file with the pieces, the joined form and the page, for manual review by the user. The reviewed sample gives a precision estimate for the whole corpus. The script only prints counts; the CSV stays local.
- Later, optionally: the indexes as ground truth. An index entry says that a name occurs on a page; the share of index terms that can be found on the referenced page, before and after correction, measures the improvement on exactly the terms that matter for NER. This needs index parsing, which is work in itself, so it is not part of the POC.

**Threshold.** Before the test figures are looked at, the user sets what is "sufficient", for example:

- CER on the test pages at most N%;
- at most K wrong joins per 1000 joins in the reviewed sample;
- (later) at least M% of index terms found.

If the threshold is met, step 2 ends with 2a. Otherwise step 2b is considered first, then 2c.

### Step 2b: character substitutions (conditional)

Most of the remaining errors are substitutions: `I`→`1` (128 on the specimens), `o`→`0`, `s`→`f` and `s`→`S` (long s, case), `ct`→`d`, `rn`→`m`. A second deterministic pass can generate candidates from a substitution table derived from `confusions.csv` and accept a candidate only if the result is in the born-digital lexicon and the original is not.

This is a different risk class from space repair: the characters themselves change, and `1`/`I` and `0`/`o` also occur in catalogue numbers, Roman numerals and dimensions. Tokens consisting mainly of digits or Roman numerals are therefore excluded. Step 2b is a separate run (`based_on` the 2a run), with its own measurement, and is only planned in detail if the 2a measurement asks for it.

### Step 2c: LLM-assisted correction (only if needed)

Only if 2a and 2b do not reach the threshold. Even then the LLM is constrained:

- it chooses between candidates the script generates, or judges a flagged case (join or not), instead of rewriting text freely;
- its output is checked against the same invariants (2a: only whitespace removed; 2b: only substitutions from the table);
- model choice follows the project preference: local first, then an EU provider;
- the model is listed in `README.md` under AI usage.

### Code

New directory `scripts/correction/`:

- `build_lexicon.py`: fills `lexicon` and `bigrams` in `crlb.sqlite`.
- `correct_spaces.py`: runs step 2a on all OCR documents (or a selection), writes `correction_runs`, `corrected_words` and `correction_flags`. Checks the invariant per page. Prints only counts.
- `measure_gaps.py`: the gap investigation on the development pages; prints the distributions as counts and quantiles only.
- `sample_joins.py`: writes the review sample to CSV.
- `analyse_specimens.py` (existing, in `scripts/OCR/`): extended with an option to compare corrected text, and with join precision and recall.

Project configuration as in step 1 (`pyproject.toml` paths, Makefile targets, `help`).

### Tests

`tests/correction/`, on small handmade token sequences and a small lexicon:

- R1 joins `p r o v e n a n c e` and flags an unknown run;
- R2 joins `M useum`, `Mu seum` and `Museu m`, keeps `a part` (flagged) unless the ratio condition holds, and never joins tokens with digits;
- R3 joins across lines on a soft hyphen and never on a hard hyphen;
- punctuation and case are kept (`M useum,` → `Museum,`);
- the invariant check catches a deliberately wrong correction;
- every raw word belongs to exactly one corrected token, and the rebuilt page text is right;
- lexicon building: soft-hyphen joining, hard-hyphen skipping, no digit tokens, OCR tokens never count as pieces.

## Step 3: segmentation

### Goal

Divide the text of each document into its structural parts and record them in the database: the sections of a volume, the catalogue entries and their copies, and the fields within an entry. This is the basis for the extraction of provenance, exhibition history, literature and descriptive texts (step 4), because what a piece of text means is decided mainly by where it is in that structure.

Segmentation does not change or interpret text; it only marks ranges of words. Like step 2a, it is deterministic: rules and patterns, configured per volume, no LLM.

### Structure of a volume

From the bookmarks, the running heads and two catalogue pages each of XIX (4) (born-digital, 2016) and II (ABBYY OCR, 1970s), the structure is a tree:

```
document
├── page furniture        running heads, page numbers, marginal marks
├── section               front matter, introduction/essays, catalogue, appendices,
│                         abbreviations/bibliography, exhibitions, illustrations, indexes
│   └── entry             catalogue number + title, e.g. "No. 22. Augustus: Painting (Fig. 79)"
│   │   ├── field         heading, material/dimensions, location, date, provenance,
│   │   │   │             exhibited, copies, literature, description, notes
│   │   │   ├── item      one provenance stage, one literature reference, one exhibition
│   │   │   ├── paragraph a paragraph of the description
│   │   │   └── note      one note, label = note number
│   │   └── copy          "(1) Painting (Fig. 80), whereabouts unknown; …" inside "copies"
│   │       └── field     material/dimensions, location, provenance ("prov.:"), literature ("lit.:")
│   │           └── item  as above
│   └── item              in the abbreviations/bibliography and exhibitions sections:
│                         one abbreviation with its full citation
```

Splitting a field into items is part of segmentation (it only marks ranges, by rules). Step 4 interprets items; it does not cut text up itself.

An entry has the same skeleton in both volumes, 40 years apart:

| Part                              | XIX (4), born-digital                                                                             | II, ABBYY OCR                                                                                      |
| :-------------------------------- | :------------------------------------------------------------------------------------------------ | :------------------------------------------------------------------------------------------------- |
| heading                           | `No. 22. Augustus: Painting (Fig. 79)`, bold 11.2 pt, title bold italic                           | `10a. THE SACRIFICE OF THE OLD COVENANT: BOZZETTO`, number bold 14 pt, title capitals 7 pt         |
| material, dimensions, inscription | first block after the heading                                                                     | first block after the heading                                                                      |
| location, inventory number        | italic                                                                                            | italic                                                                                             |
| date                              | own block (`c. 1598–1600`)                                                                        | not always present                                                                                 |
| labelled fields                   | small caps, extracted as lowercase + colon: `provenance:`, `exhibited:`, `copies:`, `literature:` | small caps, extracted as `P rov en a n ce:` (capital 10.5 pt, rest 8.4 pt), `Copy:`, `Literature:` |
| copies                            | `(1)`, `(2)`, … inside `copies:`, each with `prov.:` and `lit.:`                                  | same                                                                                               |
| description                       | untitled text after the labelled fields                                                           | same                                                                                               |
| notes                             | end of the entry, 7.5 pt, `1.⇥…`, superscript markers in the text                                 | end of the entry, 7.5 pt, `19 See …`, markers as plain digits or `*`                               |
| RKD link                          | on the heading and on each copy                                                                   | on the heading and on each copy                                                                    |

The variation between volumes is in the label wording and case, the heading format, the note markers, the layout (two columns in XIX (4), one in II) and the page furniture. This is what the per-volume configuration describes.

### Schema

```sql
-- One row per segmentation run.
CREATE TABLE segmentation_runs (
    id                 INTEGER PRIMARY KEY,
    started_at         TEXT NOT NULL,     -- ISO 8601, UTC
    correction_run_id  INTEGER REFERENCES correction_runs(id),  -- text used for matching; NULL = raw
    version            TEXT NOT NULL,     -- git commit of the scripts
    options            TEXT NOT NULL      -- JSON: the volume configurations used
);

-- One row per structural part. A segment is a contiguous range of words in
-- reading order, possibly across pages, with a parent in the tree.
CREATE TABLE segments (
    id             INTEGER PRIMARY KEY,
    run_id         INTEGER NOT NULL REFERENCES segmentation_runs(id),
    document_id    INTEGER NOT NULL REFERENCES documents(id),
    parent_id      INTEGER REFERENCES segments(id),
    kind           TEXT NOT NULL,   -- 'furniture', 'section', 'entry', 'copy', 'field',
                                    -- 'item', 'paragraph', 'note'
    label          TEXT,            -- section name, entry number ('22', '10a', '1-1'),
                                    -- copy number ('(3)'), field name ('provenance', 'notes', ...),
                                    -- note number ('19'), item/paragraph position
    first_word_id  INTEGER NOT NULL REFERENCES words(id),
    last_word_id   INTEGER NOT NULL REFERENCES words(id),
    rule           TEXT NOT NULL,   -- which rule created it
    confidence     TEXT NOT NULL CHECK (confidence IN ('certain', 'probable', 'uncertain')),
    reason         TEXT,            -- e.g. 'bold 11.2 pt line matching heading pattern; RKD link'
    link_id        INTEGER REFERENCES links(id)  -- RKD link anchoring this entry or copy, if any
);
CREATE INDEX segments_run_document ON segments(run_id, document_id);
CREATE INDEX segments_parent ON segments(parent_id);

-- Printed page numbers, derived from the page furniture.
CREATE TABLE printed_pages (
    run_id        INTEGER NOT NULL REFERENCES segmentation_runs(id),
    page_id       INTEGER NOT NULL REFERENCES pages(id),
    printed       TEXT,             -- printed page number, NULL for unnumbered pages
    rule          TEXT NOT NULL,    -- 'furniture' (read from the page) or 'interpolated'
    PRIMARY KEY (run_id, page_id)
);

-- Note markers in the text, linked to their note.
CREATE TABLE note_refs (
    id               INTEGER PRIMARY KEY,
    run_id           INTEGER NOT NULL REFERENCES segmentation_runs(id),
    word_id          INTEGER NOT NULL REFERENCES words(id),     -- the marker ('2', '*'), or the word carrying it
    note_segment_id  INTEGER NOT NULL REFERENCES segments(id),  -- kind = 'note'
    rule             TEXT NOT NULL,   -- 'superscript', 'digit after word', ...
    confidence       TEXT NOT NULL CHECK (confidence IN ('certain', 'probable', 'uncertain'))
);
CREATE INDEX note_refs_note ON note_refs(note_segment_id);
```

Notes:

- Segments refer to raw `words` ids, so segmentation does not depend on the OCR correction (step 2). The corrected tokens of step 2 map onto the same word ranges, so a field can be read in raw or corrected form. Matching labels and patterns may use the corrected text; `correction_run_id` records which.
- **Boundary conflicts with corrections.** A corrected token can cover several raw words. If a segment boundary falls inside such a token, the corrected text of the segment is undefined. Such a boundary is a conflict: the segment keeps its boundary, the corrected text of both segments uses the raw words for that token, and the case is listed in the run's checks for review. A conflict usually means either a wrong join (step 2) or a wrong boundary (step 3).
- Segments of the same `kind` under the same parent do not overlap. Because ranges are contiguous, an entry that continues on the next page also spans the running head and page number in between; those words are covered by a `furniture` segment, and anything that reads the text of a segment skips words inside furniture segments.
- `printed_pages` is needed because the PDFs have no page labels while citations and the indexes use printed page numbers (II: PDF page 298 is printed page 291; XIX (4): PDF page 89 is printed page 90). Page numbers that cannot be read (blank pages, plates) are interpolated from their neighbours.
- `confidence` makes it possible to review the uncertain cases first.

### Rules

The rules run in this order, each on the result of the previous one:

1. **Page furniture.** Words whose position and style repeat over many pages of a document: running heads at the top (XIX (4): `CATALOGUE No. 22`, 6.8 pt), page numbers at the bottom (XIX (4): 7 pt; II: bold 14 pt), marginal marks (XIX (4): a 5 pt number at the left edge). Detected per document by position band and style, configurable per volume. The page numbers fill `printed_pages`; the running heads are kept as evidence for rule 3 and the checks.
2. **Sections.** From the bookmarks (`toc`) where present. Otherwise from the running heads (`CATALOGUE …`) and from section headings (large or bold lines matching names such as Introduction, Catalogue, Appendix, Abbreviations, Index), with the printed table of contents as a check.
3. **Entries** within the catalogue section. An entry starts at a heading line that matches the volume's heading pattern (catalogue number, title, type, figure references) and has the heading style. Supporting evidence, each raising the confidence: an RKD link on the heading line, a running head with the same number on the same or next page, a number that follows the previous one in the numbering scheme (`1`, `1a`, `2`, …; `1-1` for fragments). OCR errors in the number (`10«` for `10a`) are tolerated through the style and the numbering sequence, and recorded in `reason`. An entry ends where the next entry or section starts.
4. **Fields** within an entry:
    - `heading`: the heading line(s).
    - `material`, `location`, `date`: the blocks between the heading and the first label, in that order; `location` recognised by italics, `date` by a date pattern.
    - labelled fields: a block that starts with a label from the volume's label list (`provenance`, `exhibited`, `copies`/`copy`, `literature`, `drawings`, `prints`, …), recognised by text (fuzzy, case-insensitive, spaces ignored) and, in OCR volumes, by the small-caps size pattern. The field runs until the next label or the description.
    - `description`: the untitled body text after the last labelled field.
    - `notes`: the trailing run of note-size lines starting with a note number, up to the next entry.
5. **Copies** within a `copies` field: each starts at `(n)` at the start of a line or block, supported by an RKD link at that position; within a copy, sub-fields after `prov.:`, `lit.:` and similar abbreviations.
6. **Cross-references** such as `provenance: see No. 21.` are recorded as a field with label `provenance` and a `reason` noting the reference. Resolving them is step 4.
7. **Paragraphs and notes.**
    - `paragraph`: the `description` field is split at paragraph starts: a new block with a first-line indent (II: the indented lines at x=52 against 42) or a vertical gap (XIX (4): one block per paragraph).
    - `note`: the `notes` field is split at note numbers at the start of a line (`1.⇥`, `19 `), checked against the expected sequence; the note number is the `label`.
8. **Note markers** (`note_refs`): in born-digital volumes, superscript words (flag 1) in the description and fields; in OCR volumes, a digit or `*` directly attached to the end of a word or after punctuation (`Julienne.1`), accepted only if a note with that number exists in the same entry and the numbers occur in increasing order. Each marker is linked to its note.
9. **Items.** Fields that are lists are split into `item` segments:
    - `provenance` and `prov.:`: at `;` outside brackets and quotation marks (the stages of the provenance chain);
    - `literature`, `lit.:`, `exhibited`, `exh.:`: at `;` outside brackets (one reference each);
    - in the abbreviations/bibliography and exhibitions sections: one item per abbreviation with its full citation, recognised by the hanging-indent layout and the abbreviation pattern (author, short title, year; or place, year).
      The separator and the item pattern are part of the volume configuration, because the conventions changed over time (the 2015 bibliography rules apply from V (1), 2014).

Patterns, label lists, style thresholds and furniture bands are kept in one configuration file per volume (`data_manifest/segmentation/<part>.toml`, in git), with shared defaults. Configurations are developed on a few pages and then checked on the whole volume.

### Checks and measurement

Built-in checks per document, reported as counts:

- entry numbers are consecutive in the numbering scheme, without gaps or duplicates;
- every entry has a heading and at least material/dimensions or location;
- in `_links` documents: every RKD link lies in the heading of an entry or at the start of a copy, and every entry has a link (exceptions listed);
- running heads agree with the entry segments on their pages;
- printed page numbers increase by one per page, apart from interpolated pages;
- no words outside a section (except furniture);
- notes are numbered consecutively per entry, every note has at least one marker, and every marker resolves to a note;
- every literature and exhibition item matches an abbreviation item of the same part (unmatched items listed);
- the number of boundary conflicts with the active correction run.

Reference data:

- **The Rubenshuis registration lists** (an Excel list per volume with record numbers such as `19`, `19a`, `19C11`, one row per entry and copy) give the expected entries and copies per volume. Comparing them with the segments measures completeness without manual work. To be requested from the Rubenshuis.
- A small hand-checked set: for each POC volume, a few entries whose segment boundaries and fields are checked by the user against the PDF. A review script writes the segments of a sample of entries to a local file (HTML with the page images and boxes, or CSV), never to the console.

### Order of work

1. POC volumes: XIX (4) (born-digital, `_links`) and II part 1 (`02_1_links`, ABBYY): furniture, sections, entries, copies, fields.
2. Check against the registration lists, if available.
3. Other volumes, one at a time, each with its own configuration. Older ABBYY volumes and born-digital volumes without links or bookmarks will need more rules.

### Code

New directory `scripts/segmentation/`:

- `segment.py`: runs the rules for the given documents with their configuration, writes `segmentation_runs`, `segments`, `printed_pages` and `note_refs`. Prints only counts and check results.
- `set_active_run.py`: sets the active run of a step in `active_runs` (shared with steps 2 and 4).
- `review_segments.py`: writes a review file for a sample of entries (local, not printed).
- `data_manifest/segmentation/`: the per-volume configuration files.

Project configuration as in step 1.

### Tests

`tests/segmentation/`, on small generated PDFs that imitate both layouts (two columns with paragraph blocks; one column with a block per line), built through the step 1 extraction:

- furniture is detected and printed page numbers are read and interpolated;
- entries are found by heading style and pattern, including a damaged number (`10«.`) between `10.` and `11.`;
- labelled fields are found in both forms (`provenance:` and `P rov en a n ce:` with two sizes);
- copies are split at `(n)` and their `prov.:`/`lit.:` sub-fields are found;
- notes at the end of an entry are a separate field, split into single notes with their numbers;
- the description is split into paragraphs in both layouts;
- superscript markers and attached digits (`Julienne.1`) are linked to the right note; a digit that is part of a number (`1617`) is not;
- provenance is split into stages at `;`, but not at a `;` inside brackets or quotation marks;
- abbreviation-list entries become items, and a literature item is matched to its abbreviation;
- a segment boundary inside a joined token is reported as a conflict;
- an entry continuing on the next page, past the furniture, stays one segment;
- the checks report a gap in the numbering and an RKD link outside any entry.

### Points to check first

- The `(7)` in a different font (BellMT 10 pt) at the position of an RKD link in XIX (4): possibly text added by the tool that added the links. If so, it must be treated as furniture, not as part of the copy.
- Whether ABBYY's font sizes are consistent enough across a whole volume for the style rules, or need a tolerance per volume.

## Step 4: extraction

### Goal

Turn the segments of step 3 into structured records that follow the **Rubens Online data model** (RO Datamodel v0.1, [browsable version](https://hvanstappen.github.io/RubensOnline), [spreadsheet](https://docs.google.com/spreadsheets/d/1t_Tt4jtfaT1j-gEBEcGngK_qcSTe3TC07R4XQUFudys)), in particular the data that was not (fully) entered by hand: provenance, exhibition history, literature and the descriptive texts, together with the core data of each work that these hang on.

Step 4 records **what the text says**, verbatim and in the structure of the RO model. Linking values to authorities (RKD Artists, TGN, AAT, Iconclass, Wikidata) and reconciling with the existing RKD/Axiell data is step 5; the `*_id` columns for authorities stay empty in step 4.

### Principles

The same as in steps 2 and 3:

1. **Rules first, LLM where rules fall short.** Step 3 has already cut fields into items (one provenance stage, one literature reference). Most fields can then be interpreted by rules; the LLM is used per item, on short inputs, for what rules cannot do reliably.
2. **No invented text.** The LLM returns only _spans_ (verbatim substrings of the item) and _choices from a closed list_ (e.g. a transfer method). The code checks that every span occurs in the item text and every choice is in the list; a violation rejects the answer. Normalisation (dates to ISO, dimensions to numbers, list labels to URIs) is always done by rules on the verbatim values.
3. **Fixed output format.** The LLM output is constrained to a JSON schema during generation (structured output / grammar-constrained decoding), so it is always well-formed.
4. **Traceable.** Every row records its source segment or item (and so its words and coordinates), the run, the method (`rules` or `llm`), and a review status.
5. **Local first.** See "Models".

### Mapping from the CRLB entry to the RO model

| CRLB (step 3 segment)                                                                           | RO model                                                                                                                                                                                                                                                                                                               | Method                                                  |
| :---------------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------ |
| entry, copy, print                                                                              | `Object`; a copy or print is its own Object with an artistic relation (`copy after`, `copied in print by`) to the primary work                                                                                                                                                                                         | rules                                                   |
| entry number, part                                                                              | `object_identifier` of type `CRLB nummer` (`XIX (4), No. 22`, copies `XIX (4), No. 22, Copy 3`)                                                                                                                                                                                                                        | rules                                                   |
| RKD link                                                                                        | `object_identifier` of type `RKD ID`                                                                                                                                                                                                                                                                                   | rules                                                   |
| heading: title                                                                                  | `title_value`, `title_type` = title                                                                                                                                                                                                                                                                                    | rules                                                   |
| heading: type (`Painting`, `BOZZETTO`, `Drawing`)                                               | `object_name_label` from the _Object names_ list                                                                                                                                                                                                                                                                       | rules (mapping table per volume), LLM if unmapped       |
| heading/copy: attribution (`Workshop of Rubens`, `attributed to`, `by an anonymous artist`)     | `production_attribution_status` (_Attribution status_ list), `production_actor_label`                                                                                                                                                                                                                                  | rules + LLM                                             |
| `material` (`Oil on panel; c. 68.5 × 52.5 cm. Inscribed …`)                                     | `material_note` (verbatim), `material_support_label` (_Material_support_ list), `material_label`; dimensions: `dimension_value`, `dimension_unit_label`, `dimension_type_label` (height first, then width, per the style guide); inscriptions: `inscription_type_label`, `inscription_content`, `inscription_position` | rules for material and dimensions; LLM for inscriptions |
| `location` (`Stuttgart, Staatsgalerie. Inv. no. 2258`; `Whereabouts unknown; presumably lost.`) | current collection: `collection_is_current` = true, holder name, `collection_place_label`, `collection_identifier`; lost or destroyed: `destruction_cause`, `destruction_date_*`                                                                                                                                       | rules + LLM                                             |
| `date` (`c. 1598–1600`)                                                                         | `production_date_label` (verbatim), `production_date_start`/`_end`                                                                                                                                                                                                                                                     | rules                                                   |
| `provenance` items                                                                              | per stage either a **collection** stay (holder, place, `collection_entry_date`, `collection_entry_method` from _Transfer method_, removal date) or an **auction** (`auction_label`, organiser, place, dates, `auction_lot_number`, `auction_consignor`, `auction_buyer`, `auction_price_amount`, currency)             | LLM per item, rules for dates, lists and chain order    |
| `exhibited` items                                                                               | `exhibition_id` (via the volume's exhibitions list → `Exhibition` record: title, venue, place, dates), `exhibition_cat_number`, `exhibition_note`                                                                                                                                                                      | rules                                                   |
| `literature` items                                                                              | `source_id` (via the volume's abbreviations list → `TextResource` record: author, title, date) or `source_reference` (full citation if not resolved), `source_page_reference`, `source_note` (`as Jan van Eyck`, `repr.`)                                                                                              | rules, LLM for leftovers                                |
| description paragraphs and notes                                                                | `TextResource` of source type `CRLB-entry`, with paragraphs and notes; figure references removed and `Ibid.` resolved for display (see "Analyses entries")                                                                                                                                                             | rules                                                   |
| cross-references (`see No. 21`)                                                                 | resolved to the referenced Object's data, recorded as a reference, not copied                                                                                                                                                                                                                                          | rules                                                   |

The provenance chain needs care in the mapping, because the CRLB writes it as one chronological list in which collection stays and sales alternate, while RO separates collections (with entry and removal) from auctions:

- "his sale" or "sale" makes the stage an auction; the consignor is the previous holder when the text says "his/her sale".
- The removal date of a collection stay is taken from the date of the next stage when the text gives none (recorded as derived, not as stated).
- `?` before a stage, or "possibly"/"probably", marks it uncertain (style guide: `?` only for an uncertain part of the provenance). RO records uncertainty in notes; the flag is kept in a column so it is not lost.
- "(as Rubens)" or "(as 'Rubbens')" is the attribution under which the work was sold or listed; it goes into `auction_note` or `collection_entry_note`.

### Schema

All step 4 tables start with `ro_`. Column names follow the RO model where a column corresponds to an RO property; the extra columns (`*_text`, source, run, status) are for traceability and validation and are not exported to RO as such.

```sql
-- One row per extraction run (per field and method).
CREATE TABLE ro_runs (
    id                   INTEGER PRIMARY KEY,
    started_at           TEXT NOT NULL,
    field                TEXT NOT NULL,     -- 'object', 'provenance', 'exhibition', 'literature', 'text'
    method               TEXT NOT NULL CHECK (method IN ('rules', 'llm')),
    model                TEXT,              -- name, version, quantisation; NULL for rules
    runtime              TEXT,              -- e.g. 'ollama 0.x', 'llama.cpp server bNNNN'; NULL for rules
    prompt_sha           TEXT,              -- hash of prompt + JSON schema (both in git)
    correction_run_id    INTEGER REFERENCES correction_runs(id),
    segmentation_run_id  INTEGER NOT NULL REFERENCES segmentation_runs(id),
    version              TEXT NOT NULL,     -- git commit
    options              TEXT NOT NULL      -- JSON: thresholds, temperature, seed, ...
);

-- Every extracted row carries these columns (shown once here, written out in schema.sql):
--   segment_id   INTEGER NOT NULL REFERENCES segments(id)  -- the field or item it comes from
--   run_id       INTEGER NOT NULL REFERENCES ro_runs(id)
--   status       TEXT NOT NULL DEFAULT 'unreviewed'
--                CHECK (status IN ('unreviewed', 'accepted', 'corrected', 'rejected'))
--   review_note  TEXT

-- Object: one per entry, copy and print.
CREATE TABLE ro_objects (
    id                          INTEGER PRIMARY KEY,
    segment_id ..., run_id ..., status ..., review_note ...,   -- the entry or copy segment
    part                        TEXT NOT NULL REFERENCES parts(part),
    crlb_number                 TEXT NOT NULL,   -- '22', '10a', '22 (3)'
    title_value                 TEXT,
    title_type_label            TEXT,            -- 'title'
    object_name_label           TEXT,            -- from Object names, e.g. 'painting (visual work)'
    object_name_text            TEXT,            -- verbatim: 'Painting', 'BOZZETTO'
    production_date_label       TEXT,            -- verbatim: 'c. 1598–1600'
    production_date_start       TEXT,            -- YYYY[-MM[-DD]]
    production_date_end         TEXT,
    material_note               TEXT,            -- verbatim: 'Oil on panel'
    material_support_label      TEXT,            -- from Material_support
    destruction_cause           TEXT,            -- from Destruction cause
    destruction_date_start      TEXT,
    destruction_date_end        TEXT,
    destruction_text            TEXT             -- verbatim: 'destroyed in 1945', 'presumably lost'
);

CREATE TABLE ro_object_identifiers (
    id, object_id INTEGER NOT NULL REFERENCES ro_objects(id),
    segment_id ..., run_id ..., status ..., review_note ...,
    object_identifier             TEXT NOT NULL,   -- 'XIX (4), No. 22', '311963'
    object_identifier_type_label  TEXT NOT NULL,   -- 'CRLB nummer', 'RKD ID'
    link_id                       INTEGER REFERENCES links(id)
);

CREATE TABLE ro_attributions (
    id, object_id ..., segment_id ..., run_id ..., status ..., review_note ...,
    production_attribution_status  TEXT NOT NULL,  -- from Attribution status
    production_actor_label         TEXT,           -- 'Rubens', 'Workshop of Rubens', 'anonymous'
    attribution_text               TEXT NOT NULL,  -- verbatim
    is_current                     INTEGER NOT NULL
);

CREATE TABLE ro_dimensions (
    id, object_id ..., segment_id ..., run_id ..., status ..., review_note ...,
    dimension_value       REAL NOT NULL,
    dimension_unit_label  TEXT NOT NULL,     -- 'cm', 'mm'
    dimension_type_label  TEXT NOT NULL,     -- 'height', 'width', 'diameter', ...
    dimension_note        TEXT,              -- 'c.', 'approximately', 'sight size'
    dimensions_text       TEXT NOT NULL      -- verbatim: 'c. 68.5 × 52.5 cm'
);

CREATE TABLE ro_inscriptions (
    id, object_id ..., segment_id ..., run_id ..., status ..., review_note ...,
    inscription_type_label  TEXT,            -- from Inscription Type
    inscription_content     TEXT,            -- verbatim
    inscription_position    TEXT,            -- verbatim: 'horizontally below'
    inscription_note        TEXT             -- verbatim: 'in gold on grey'
);

-- Provenance and current location: collection stays.
CREATE TABLE ro_collection_stays (
    id, object_id ..., segment_id ..., run_id ..., status ..., review_note ...,
    position                     INTEGER NOT NULL,  -- order in the chain; current location last
    holder_text                  TEXT NOT NULL,     -- verbatim: 'Duarte Pinto Coehlo', 'Staatsgalerie'
    collection_type_label        TEXT,              -- from Collection Type (museum, private collection, art dealer, church, ...)
    collection_place_label       TEXT,              -- verbatim place name
    collection_identifier        TEXT,              -- inventory number
    collection_entry_date        TEXT,              -- YYYY[-MM[-DD]]
    collection_entry_date_text   TEXT,              -- verbatim
    collection_entry_method      TEXT,              -- from Transfer method
    collection_entry_note        TEXT,
    collection_removal_date      TEXT,
    collection_removal_derived   INTEGER NOT NULL DEFAULT 0,  -- 1 = taken from the next stage
    collection_removal_method    TEXT,
    collection_removal_note      TEXT,
    collection_is_current        INTEGER NOT NULL,
    uncertain                    INTEGER NOT NULL DEFAULT 0   -- '?', 'possibly', 'probably'
);

-- Provenance: auctions (one row per object per sale).
CREATE TABLE ro_auctions (
    id, object_id ..., segment_id ..., run_id ..., status ..., review_note ...,
    position                  INTEGER NOT NULL,  -- order in the chain, shared with ro_collection_stays
    auction_label             TEXT,              -- e.g. 'his sale'
    auction_organizer_label   TEXT,              -- verbatim: 'Christie’s'
    auction_place_label       TEXT,              -- verbatim: 'London'
    auction_date_start        TEXT,
    auction_date_end          TEXT,
    auction_date_text         TEXT,              -- verbatim: '20–21 July 2011', '15ff. June 1874'
    auction_lot_number        TEXT,
    auction_consignor         TEXT,              -- free text, as in RO
    auction_buyer             TEXT,              -- free text, as in RO
    auction_price_amount      TEXT,              -- string, as in RO (pounds/shillings/pence)
    auction_price_currency    TEXT,              -- from Currencies
    auction_note              TEXT,              -- e.g. '(as Rubens)'
    uncertain                 INTEGER NOT NULL DEFAULT 0
);

-- Exhibitions and literature: the records from the volume's lists (step 3 items) ...
CREATE TABLE ro_exhibitions (
    id INTEGER PRIMARY KEY,
    segment_id ..., run_id ..., status ..., review_note ...,   -- the abbreviation-list item
    part                   TEXT NOT NULL REFERENCES parts(part),
    abbreviation           TEXT NOT NULL,     -- 'Liverpool – London, 1998–99'
    exhibition_title       TEXT,
    exhibition_venue       TEXT,
    exhibition_place_label TEXT,
    exhibition_date_start  TEXT,
    exhibition_date_end    TEXT,
    full_citation          TEXT NOT NULL      -- verbatim
);

CREATE TABLE ro_text_resources (
    id INTEGER PRIMARY KEY,
    segment_id ..., run_id ..., status ..., review_note ...,
    part                   TEXT NOT NULL REFERENCES parts(part),  -- part whose list it comes from, or of the CRLB entry
    abbreviation           TEXT,              -- 'Jaffé, Catalogo, 1989'; NULL for CRLB entries
    source_type_label      TEXT NOT NULL,     -- from Source Types: book, article, exhibition catalogue, CRLB-entry, ...
    source_title           TEXT,
    source_author          TEXT,
    source_date            TEXT,
    full_citation          TEXT,              -- verbatim
    object_id              INTEGER REFERENCES ro_objects(id)  -- for source type 'CRLB-entry'
);

-- ... and their use in an entry (step 3 items of 'exhibited' and 'literature').
CREATE TABLE ro_object_exhibitions (
    id, object_id ..., segment_id ..., run_id ..., status ..., review_note ...,
    exhibition_id          INTEGER REFERENCES ro_exhibitions(id),  -- NULL = not resolved
    exhibition_cat_number  TEXT,
    exhibition_note        TEXT,
    reference_text         TEXT NOT NULL     -- verbatim item
);

CREATE TABLE ro_object_sources (
    id, object_id ..., segment_id ..., run_id ..., status ..., review_note ...,
    source_id              INTEGER REFERENCES ro_text_resources(id),  -- NULL = not resolved
    source_reference       TEXT,             -- full citation if not resolved
    source_page_reference  TEXT,             -- 'pp. 297–303', 'no. 109a', 'fig. 4'
    source_note            TEXT,             -- '(as Jan van Eyck)', 'repr.'
    reference_text         TEXT NOT NULL     -- verbatim item
);

-- Artistic relations: copy after, copied in print by, study for, ...; and cross-references.
CREATE TABLE ro_related_objects (
    id, object_id ..., segment_id ..., run_id ..., status ..., review_note ...,
    related_object_id                        INTEGER REFERENCES ro_objects(id),
    related_object_artistic_relation_type    TEXT,   -- from Artistic relation types
    related_object_artistic_description      TEXT,   -- when there is no related record
    relation_text                            TEXT NOT NULL  -- verbatim, e.g. 'see No. 21'
);

-- Descriptive text of the CRLB entry (TextResource of type 'CRLB-entry').
CREATE TABLE ro_text_paragraphs (
    id INTEGER PRIMARY KEY,
    text_resource_id  INTEGER NOT NULL REFERENCES ro_text_resources(id),
    segment_id ..., run_id ..., status ..., review_note ...,   -- the paragraph segment
    position          INTEGER NOT NULL,
    text              TEXT NOT NULL,     -- corrected text, note markers kept
    text_display      TEXT NOT NULL      -- figure references removed, for Rubens Online
);

CREATE TABLE ro_text_notes (
    id INTEGER PRIMARY KEY,
    text_resource_id  INTEGER NOT NULL REFERENCES ro_text_resources(id),
    segment_id ..., run_id ..., status ..., review_note ...,   -- the note segment
    number            TEXT NOT NULL,
    text              TEXT NOT NULL,
    text_display      TEXT NOT NULL,     -- 'Ibid.' and 'op. cit.' resolved, figure references removed
    paragraph_id      INTEGER REFERENCES ro_text_paragraphs(id)  -- paragraph containing the first marker
);

-- LLM calls, for auditing and reuse: what was asked, what came back, what was accepted.
CREATE TABLE ro_llm_calls (
    id            INTEGER PRIMARY KEY,
    run_id        INTEGER NOT NULL REFERENCES ro_runs(id),
    segment_id    INTEGER NOT NULL REFERENCES segments(id),
    input_text    TEXT NOT NULL,
    output_json   TEXT,
    valid         INTEGER NOT NULL,   -- passed schema, span and list checks
    error         TEXT,               -- why it was rejected
    duration_ms   INTEGER NOT NULL,
    tokens_in     INTEGER,
    tokens_out    INTEGER
);
```

Notes:

- `ro_collection_stays` and `ro_auctions` share `position`, so the provenance chain can be read back in the order of the text.
- Collections, agents and places are not separate records yet: holders, consignors and places are verbatim text. Making them RO `Collection`, `Agent` and `Place` records with URIs is reconciliation (step 5); the same holder appears under different spellings across volumes.
- The RO `Auction` class is one record per sale event shared by all objects in it; step 4 keeps one row per object per sale, and step 5 merges rows that describe the same sale (same organiser, place and date).
- The `ro_llm_calls` table makes every LLM decision auditable and allows rerunning the checks or comparing models without calling the model again.
- An export script turns the active runs into RO records (JSON per object, following the RO property names), for NocoDB/MongoDB or the Rubens Online datahub. Only rows with `status` other than `rejected` are exported; whether `unreviewed` rows are exported is a decision for the client.

### Rules per field

- **Object core** (heading, material, date, location): patterns per volume, based on the style guide's fixed order (`Painting (Fig. x), attributed to …, Antwerp, St Paul’s Church; canvas, 158 x 106 cm.`). Dimensions: `H × W unit` with `x`, `×` or `:` (older volumes: `16 : 21.5 cm`), decimal point or comma; `c.`/`approximately` into `dimension_note`. Support and object name through mapping tables (`panel` → `paneel (hout)`, `canvas` → `doek`, `Painting` → `schilderij`, `BOZZETTO` → `olieverfschets`), kept in git and extended per volume.
- **Literature and exhibitions:** split already done in step 3. Each item is matched to the abbreviation list of the same part: the longest abbreviation that the item starts with (fuzzy on OCR text, exact on born-digital), the rest parsed into page reference, number, figures and note. Unmatched items are listed; the LLM is only used to split the leftovers.
- **Abbreviation lists:** each list item is split into abbreviation and full citation by layout (hanging indent) and pattern; the full citation is parsed into author, title, place, date by patterns from the 2015 bibliography rules, with the LLM for leftovers in older volumes.
- **Provenance:** per item: rules recognise the frequent fixed forms (`sale, London (Christie’s), 20–21 July 2011, lot 550`; `his sale`; `with the dealer X, Brussels, 1971`); everything else goes to the LLM. Dates in any form (`15ff. June 1874`, `in 1796 ?`, `(1612 - 23 October 1652)`) are parsed by rules into start/end.
- **Descriptive text:** paragraphs and notes from step 3; `text_display` by rules: remove `(Fig. 58)`, `(No. 15; Fig. 58)` and similar, resolve `Ibid.` to the previous note's citation and `op. cit.`/`loc. cit.` to the last citation of that author.

### LLM tasks

Each task is one prompt with a JSON schema, both in git (`scripts/extraction/prompts/<task>.md` and `.json`), with a few examples taken from the development set. Input is one item plus minimal context (the field name, the previous stage for provenance).

| Task                | Input                                        | Output                                                                                                                                                                           |
| :------------------ | :------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `provenance_stage`  | one provenance item                          | kind (collection/auction), spans for holder, place, dates, organiser, lot, price, consignor, buyer, note; choices for transfer method, collection type, currency; uncertain flag |
| `inscription`       | the inscription part of the material field   | spans for type word, position, content, note; choice for inscription type                                                                                                        |
| `location`          | the location field                           | spans for holder, place, inventory number; choice for collection type; lost/destroyed with cause                                                                                 |
| `attribution`       | heading or copy attribution                  | span for actor; choice for attribution status                                                                                                                                    |
| `citation_leftover` | an unmatched literature or abbreviation item | spans for author, title, date, pages                                                                                                                                             |

The checks on every answer: valid against the schema; every span is a substring of the input (after whitespace normalisation); every choice in the list; dates only as spans (parsed by rules afterwards). Rejected answers are stored in `ro_llm_calls` with the reason and the item is flagged for review. Temperature 0 and a fixed seed, so a rerun gives the same answer.

### Models

The hardware available for development has no GPU, 15 GB RAM and 8 CPU cores. That is enough for a quantised model of about 7–8 billion parameters at a few tokens per second: fine for the POC (tens of entries), too slow for the whole corpus (tens of thousands of items).

Escalation path, each step only if the measurement of the previous one is insufficient:

1. **POC, local:** two open models of about 8B parameters, compared on the same development items: a Qwen model (strong at structured output) and a Mistral model (EU, the project's preference). Exact versions are chosen when the work starts.
2. **Full run, open model on EU infrastructure:** an open model of about 24–32B parameters on a rented GPU server in the EU, or the Mistral API (EU).
3. **Frontier model** (Claude, OpenAI, Gemini), only for the fields where 1 and 2 do not reach the threshold.

Runtime: Ollama or the llama.cpp server (a llamafile is llama.cpp packaged as one file; the results are the same), called from Python over HTTP, with the JSON schema passed for constrained decoding. The runtime is behind a small interface so a cloud API can be swapped in for step 2 or 3 of the escalation without changing the tasks.

Every model and runtime used is added to `README.md` under AI usage.

### Measurement

**Reference data.** The Rubenshuis has registered several volumes by hand in Adlib/Axiell, managed by the RKD (2023–2025, including XIX (4) and XII, see the presentation). Those records give, for the same works, the provenance, exhibitions and literature as entered by people. An export for the POC volumes is to be requested. Where no reference exists, a small hand-checked set is made by the user from the review file.

**Development and test split** per volume, as in step 2: rules and prompts are tuned on development entries only; test entries are used once per version.

**Metrics** per field and per method:

- precision and recall of extracted values against the reference (exact and normalised match), per RO property;
- for provenance: correct number and order of stages, correct kind (collection/auction);
- for literature and exhibitions: share of items resolved to an abbreviation;
- for the LLM: share of rejected answers (schema, span, list), duration per item, and the projected time for the whole corpus;
- for review: share of rows accepted unchanged.

**Threshold.** As in step 2, the user sets beforehand what is sufficient per field. Fields below the threshold move up the escalation path; fields above it stay local.

### Order of work

1. XIX (4), a few entries: object core, literature and exhibitions (rules only) and the abbreviation list.
2. XIX (4): provenance with rules plus the local LLM; comparison of the two local models.
3. The same for II part 1 (`02_1_links`), with the OCR correction of step 2.
4. Descriptive text and notes (rules).
5. Measurement against the reference data; decision on escalation per field.

### Code

New directory `scripts/extraction/`:

- `extract_objects.py`, `extract_lists.py` (abbreviation and exhibition lists), `extract_references.py` (literature, exhibitions), `extract_provenance.py`, `extract_texts.py`: each writes one `ro_runs` row and its tables, and prints only counts.
- `llm.py`: the runtime interface (local server or API), schema-constrained calls, the span and list checks, logging to `ro_llm_calls`.
- `prompts/`: one prompt and one JSON schema per task.
- `vocabularies/`: the RO value lists used (Object names, Material_support, Attribution status, Transfer method, Collection Type, Currencies, Inscription Type, Source Types, Artistic relation types) as CSV with label and URI, and the CRLB-to-RO mapping tables.
- `review_extraction.py`: writes a local review file per entry (the PDF region next to the extracted rows), never to the console.
- `export_ro.py`: writes RO JSON records from the active runs.

New dependencies, to be confirmed when the code is written: an HTTP client for the model runtime, and a schema library (for example Pydantic) to define the JSON schemas once and validate answers.

### Tests

`tests/extraction/`, on hand-made items, with the LLM replaced by a stub that returns fixed answers:

- dimensions in the different notations (`68.5 × 52.5 cm`, `16 : 21.5 cm`, `c. 64 × 51 cm`, `66,5 × 51 cm`) give the right values, unit, type and note;
- literature items are matched to the right abbreviation, including the longest match when one abbreviation is a prefix of another, and page references are split off;
- the fixed provenance forms (`sale, London (Christie’s), 20–21 July 2011, lot 550`, `his sale`) are parsed by rules, with the consignor taken from the previous stage for `his sale`;
- dates (`15ff. June 1874`, `20–21 July 2011`, `in 1796 ?`, `c. 1598–1600`) give the right start and end;
- an LLM answer with a span that is not in the input, or a choice outside the list, is rejected and logged;
- the provenance chain keeps its order across collection stays and auctions, and a derived removal date is marked as derived;
- `Ibid.` in a note is resolved to the previous note's citation, and figure references are removed from `text_display`;
- the export produces RO property names and leaves out rejected rows.

### Points to check first

- Whether the RO model will get its own records for collections, agents and auctions with Rubens Online URIs, or link to RKD records; this decides what step 5 has to produce.
- How the RKD/Axiell export of the registered volumes is structured, so the comparison can be automated.
- Whether `unreviewed` rows may be exported.

## Volumes without a PDF

Eleven volumes exist only as Word files: I, VII, VIII, X, XIII (1), XV, XVI, XXII (1), XXIV, XXVI (1) and XXVI (2.3). Four of them also have original scans (XV, XXII (1), XXVI (1), XXVI (2.3); VI and XIII (3) have scans as well but already have a PDF). There is no decision yet; the options are:

1. Import the Word text into the same tables, one `pages` row per Word section, without `words` coordinates and with `text_source = 'docx'`. Fast, but nothing to validate against and an unknown OCR quality.
2. OCR the scans where they exist (this gives text with coordinates, comparable to the PDFs), and use the Word files only for the volumes without scans.
3. Leave them out of the POC.

Before choosing, measure the quality of the Word text on a few pages that also exist as ABBYY PDF (for example `Boekdeel_II_I.docx` against `CRLB_02_1_links`, both 416 pages), with the same method as the OCR quality test.

## Open questions

- Sub-part or physical volume for `02_1`/`02_2`, `18_1`, `21_1`/`21_2` and `23_1`/`23_2`/`23_3`: to be read from the colophons and checked with the Rubenshuis.
- Whether XIII (2) `CRLB_13_2_1` and `CRLB_13_2_2` (both 392 pages, created a minute apart) are two volumes or two versions of one.
- Where the Word files come from (which OCR, made by whom), and whether there are two versions on purpose (`Boekdeel_X.docx` and `Boekdeel_X(1).docx`).
- Whether a PDF of XXVI (2.3) exists.
- Whether the final edition of XXVII (2) is available instead of the proof.
