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

-- One row per PDF file.
CREATE TABLE documents (
    id             INTEGER PRIMARY KEY,
    run_id         INTEGER NOT NULL REFERENCES extraction_runs(id),
    path           TEXT NOT NULL UNIQUE,   -- = sqlar.name in pdfs.sqlite
    sha256         TEXT NOT NULL,          -- hex digest of the PDF bytes
    size           INTEGER NOT NULL,       -- bytes
    part           TEXT NOT NULL,          -- from the manifest
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
    text      TEXT NOT NULL
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
    - insert `words` from `page.get_text("words", sort=False)`;
    - insert `links` from `page.get_links()`.
6. Commit once per document.

After all documents: resolve `excerpt_of` paths to document ids, fill the FTS index (`INSERT INTO pages_fts(pages_fts) VALUES ('rebuild')`) and run `ANALYZE`.

Extraction settings, also recorded in `extraction_runs.options`:

- `sort=False`: keep the order of the content stream. ABBYY and InDesign write the text in their own reading order; sorting by position can mix columns.
- Default text flags, **without** `TEXT_DEHYPHENATE`: soft hyphens (`\xad`) and line-end hyphens stay as they are.
- No normalisation (no NFC, no whitespace collapsing). That belongs to later steps.

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
- soft hyphens survive unchanged in `pages.text` and `words.text`;
- `excerpt_of` is resolved to the right document id;
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
- Splitting the text into catalogue entries and extracting fields.
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
```

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
