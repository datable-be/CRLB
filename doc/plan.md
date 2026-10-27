# Plan

## Implementation

How the steps below are built as software. The end result of the project is data, not software; the software is there to produce that data reproducibly and to document how it was produced.

### Environment and reproducibility

- **uv** manages Python and all Python dependencies. `uv.lock` pins every package version and hash; a `.python-version` file (`uv python pin 3.14`) pins the interpreter at the minor version; patch releases (bug and security fixes) are picked up automatically. All commands run as `uv run --locked …`, so an outdated lock file stops the run instead of being updated silently.
- **No container.** PyMuPDF ships with MuPDF built in and uv's Python builds include SQLite with FTS5, so there are no system libraries to install. A Dockerfile can be added on top of uv later if a deployment asks for it; it is not needed to reproduce the data.
- **What uv does not pin** is recorded separately, because it affects results more than any Python package:
    - the model runtime (Ollama or llama.cpp server) and its version;
    - each model by name, quantisation and file digest; models downloaded from Hugging Face (for example GLiNER) by repository and commit hash;
    - external tools such as Pandoc, with their version.
      They are listed in `README.md` (with the AI tools, under AI usage) and stored with every run that uses them (`model`, `runtime` and `options` of the run tables).
- **The data records its own provenance.** Every run stores the git commit of the code, its options and the runs it builds on; every LLM answer is stored (`llm_calls`). Results are reproduced from these records, not by calling a model again: LLM output is not guaranteed to be identical across hardware and runtime versions, even at temperature 0.

### Code structure

One Python package with a command-line interface, instead of separate scripts per step:

```
src/crlb/
├── cli.py              the `crlb` command (argparse), one subcommand per action
├── db.py               connections to crlb.sqlite and pdfs.sqlite, schema versions
├── runs.py             run rows, active runs, git commit and options of a run
├── text.py             the effective text of a word range (see below)
├── llm.py              the model interface: local runtime or API, schema-constrained calls, span and list checks, `llm_calls`
├── review.py           reviews, status updates and effective values
├── schema/             one SQL file per step, applied in order
├── ocr/                the OCR quality test (specimen sampling and analysis)
├── database/           step 1
├── correction/         step 2
├── segmentation/       step 3
├── extraction/         step 4 (with prompts/ and vocabularies/)
└── enrichment/         step 5 (with entry_rules/)
tests/                  one folder per subpackage, as now
```

- **CLI:** `crlb <command>`, declared in `pyproject.toml` under `[project.scripts]`. Examples: `crlb list-pdfs`, `crlb build`, `crlb correct`, `crlb segment`, `crlb extract provenance`, `crlb normalise`, `crlb export markdown`, `crlb set-active <step> <run>`, `crlb ocr sample`. `crlb --help` lists them all. Only the standard library (`argparse`) is used for the CLI.
- **Makefile** targets call the CLI (`uv run --locked crlb build data_manifest/documents.csv data`), so the usual `make <target>` workflow stays, and `make help` lists the targets.
- **Shared code** lives once in the core modules: opening the database and the PDFs (`db.py`, with `open_pdf` checking the hash), run bookkeeping (`runs.py`), the effective text (`text.py`), the LLM interface (`llm.py`, used by steps 2c, 4 and 5) and reviews (`review.py`).
- **Tests** import `crlb` as an installed package; the per-folder `pythonpath`, ruff `src` and ty `extra-paths` settings are no longer needed. The OCR quality test lives in `crlb.ocr` (`crlb ocr sample`, `crlb ocr analyse`); `scripts/archive` holds earlier scripts, kept as they are and excluded from ruff and ty.
- **Conventions** for every command: type annotations and a one-line docstring on every function; ruff, ruff format and ty clean; the console only shows counts, checks and warnings, never CRLB text; anything with CRLB text (review files, samples, exports) is written to `data/`.

### Database schema and versions

The database grows step by step: each step adds its tables. The schema is kept as one SQL file per step in `src/crlb/schema/` (`01_text.sql`, `02_correction.sql`, `03_segmentation.sql`, `04_extraction.sql`, `05_enrichment.sql`, `06_review.sql`, and later changes as further numbered files). A table `schema_version` records which files have been applied; `crlb` applies missing files in order when it opens the database. This way a later step never requires rebuilding the database from scratch. `pdfs.sqlite` has only the sqlar table.

### Effective text

Every step after step 1 reads text through one function, `crlb.text`, so that "the text of a segment" means the same everywhere. The effective text of a range of word ids is:

1. the tokens of the active correction run (step 2) for those words; for every document there is one, because the soft-hyphen rule R3 also runs on born-digital documents;
2. with words inside `furniture` segments of the active segmentation run left out;
3. with corrections from `reviews` applied;
4. with a token that crosses the start or end of the range (a boundary conflict, step 3) replaced by the raw words inside the range.

It returns the text together with the word ids of each token, so every result can be traced back to coordinates.

### Shared tables

Two tables are used by all steps:

```sql
-- The run that later steps and exports use, per step. Every step can be run
-- several times; older runs stay in the database for comparison.
CREATE TABLE active_runs (
    step     TEXT PRIMARY KEY,      -- '2' (correction), '3' (segmentation), '4:<field>' (extraction),
                                    -- '5b' (normalisation), '5c' (enrichment), '5d' (named entities),
                                    -- '5e' (RKD comparison), '5f' (RKD link products)
    run_id   INTEGER NOT NULL,      -- id in the run table of that step
    set_at   TEXT NOT NULL,         -- ISO 8601, UTC
    note     TEXT                   -- why this run was made active
);

-- Every call to a language model, in any step: what was asked, what came back,
-- whether it was accepted. Allows auditing and comparing models without new calls.
CREATE TABLE llm_calls (
    id            INTEGER PRIMARY KEY,
    run_table     TEXT NOT NULL,      -- 'correction_runs', 'ro_runs', 'enrichment_runs'
    run_id        INTEGER NOT NULL,
    task          TEXT NOT NULL,      -- e.g. 'provenance_stage', 'judge_candidates', 'ner'
    first_word_id INTEGER REFERENCES words(id),   -- the input range, where the input is text
    last_word_id  INTEGER REFERENCES words(id),
    input_text    TEXT NOT NULL,
    output_json   TEXT,
    valid         INTEGER NOT NULL,   -- passed schema, span and list checks
    error         TEXT,               -- why it was rejected
    duration_ms   INTEGER NOT NULL,
    tokens_in     INTEGER,
    tokens_out    INTEGER
);
```

A run becomes active only by an explicit command (`crlb set-active`), after its measurement, never automatically. For step 2 the active run is the last run of a chain (`based_on`), for example the 2b run built on the 2a run. Reviews and corrections are described in "Review and corrections (all steps)".
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
| `data/crlb.sqlite` | documents, pages, words, links, bookmarks, full-text index; the tables of the later steps | no (CRLB text)                          |
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
CREATE TABLE build_runs (
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
    run_id         INTEGER NOT NULL REFERENCES build_runs(id),
    path           TEXT NOT NULL UNIQUE,   -- = sqlar.name in pdfs.sqlite
    sha256         TEXT NOT NULL,          -- hex digest of the PDF bytes
    size           INTEGER NOT NULL,       -- bytes
    part           TEXT NOT NULL REFERENCES parts(part),  -- from the manifest
    volume         TEXT,                   -- from the manifest
    section        TEXT NOT NULL CHECK (section IN ('main', 'index')),
    text_source    TEXT NOT NULL CHECK (text_source IN ('ocr', 'born_digital')),
    excerpt_of     INTEGER REFERENCES documents(id),
    derived_from   INTEGER REFERENCES documents(id),  -- PDF copies made by the project (step 5f)
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

- `page_label` is mostly empty: of the current PDFs only `CRLB_11_2_*` have page labels. Printed page numbers are therefore derived from the page furniture in step 3 (`printed_pages`).
- Part and file are separate on purpose: `SELECT ... WHERE part = 'XXVI (2.1)'` gives all files of that part.
- Searches over the whole corpus exclude excerpts (`WHERE excerpt_of IS NULL`) to avoid counting index pages twice.
- `pages.text` and `words` both come from the same PyMuPDF extraction of the same page. `words` is the basis for coordinates and corrections; `pages.text` is the convenient form for reading and searching.
- Later layers (OCR corrections, entries, extracted fields) go into **new tables** that refer to `words.id`, `pages.id` or `documents.id`. The tables of this step are never updated after the build.
- The `links` table matters beyond this step: in the `_links` files each RKDimages link marks a catalogue entry and carries its RKD permalink.
- The `toc` table is needed to find the catalogue and index sections (see `catalogue_pages` in the specimen sampling, `crlb.ocr`). Several born-digital PDFs have no bookmarks; for those the sections must be found another way in a later step.

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

Extraction settings, also recorded in `build_runs.options`:

- `sort=False`: keep the order of the content stream. ABBYY and InDesign write the text in their own reading order; sorting by position can mix columns.
- Default text flags, **without** `TEXT_DEHYPHENATE`: soft hyphens (`\xad`) and line-end hyphens stay as they are.
- No normalisation (no NFC, no whitespace collapsing). That belongs to later steps.

Typography per word. `get_text("words")` gives no font information, so it is added from `page.get_text("dict", sort=False)` with the same flags. The `block_no` and `line_no` of a word refer to the same block and line in the `dict` output; within that line, the word gets the font, size and flags of the span that covers most of its characters (by bounding-box overlap), and `styles` counts how many different spans it overlaps. Typography is the main signal for segmentation (step 3): bold headings, notes in a smaller size, superscript note markers, italic locations and titles, and small caps, which ABBYY records as a capital in a larger size followed by letters in a smaller size (`P rov en a n ce`: 10.5 pt and 8.4 pt).

Expected size of `crlb.sqlite`: on the order of 20,000 pages and several million words, so probably 1–2 GB, mostly `words`. The exact number will be clear after the first build.

### Code

Subpackage `crlb.database` (see "Implementation"):

- `src/crlb/schema/01_text.sql`: the schema of `crlb.sqlite` above; the sqlar table of `pdfs.sqlite`.
- `crlb list-pdfs <dir>…`: lists candidate PDFs with page count, metadata, link and bookmark counts and the proposed `text_source`, as a starting point for the manifest. Prints no PDF text.
- `crlb build <manifest> <out_dir>`:
    - creates `<out_dir>/crlb.sqlite` and `<out_dir>/pdfs.sqlite`;
    - refuses to run if either file exists (same behaviour as the specimen sampling);
    - prints only counts per document (pages, words, links per kind, bookmarks) and warnings, never PDF text;
    - functions roughly: `read_manifest`, `create_databases`, `store_pdf`, `insert_document`, `insert_toc`, `insert_page`, `build`.
- `crlb.db.open_pdf(conn, document_id) -> pymupdf.Document`: reads the bytes from the attached `pdfs.sqlite`, checks the SHA-256 against `documents.sha256` and raises if they differ. This is the entry point for later validation work.

Makefile targets `list_pdfs` and `build_database` call these commands. No new dependencies: `sqlite3` and `hashlib` are in the standard library; FTS5 is included in the SQLite of uv's Python builds.

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
- `uri` link counts match the `crlb list-pdfs` overview (e.g. 735 for `CRLB_12_I_links`, 3 identical query links for the `26_2_*_1` files, 0 for files without links).
- No `text_source` warnings.
- Spot check: for a few specimen pages from the OCR quality test, `pages.text` equals the `ocr.txt` of the specimen sampling (same extraction), compared by a script that reports only equal/different.
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

Born-digital documents get a correction run as well, with only rule R3 (soft hyphen at line end): their text is correct, but words broken at line ends (`biogra­phy`) must be joined like in the OCR text. So every document has a corrected layer, and later steps read all text the same way (see "Effective text" under "Implementation").

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

**R3, soft hyphen at line end.** A word that ends a line with `\xad` is joined to the first word of the next line in the same block. The soft hyphen is removed. Hard hyphens are never removed. R3 is the only rule that also runs on born-digital documents.

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
    reason         TEXT,            -- e.g. 'pieces: M|useum; lexicon bd=412'
    status         TEXT NOT NULL DEFAULT 'unreviewed'
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

**Metrics on the specimens** (with `crlb ocr analyse`, extended to compare a corrected text with the ground truth):

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

A candidate for comparison is the OCR-correction model tried earlier on CRLB text (`scripts/archive/OCR_correct.py`, see "Earlier work"), used as a judge rather than as a free rewriter.

### Code

Subpackage `crlb.correction`, schema `02_correction.sql`:

- `crlb lexicon`: fills `lexicon` and `bigrams`.
- `crlb correct`: runs step 2a on all OCR documents (or a selection) and R3 on the born-digital documents, writes `correction_runs`, `corrected_words` and `correction_flags`. Checks the invariant per page. Prints only counts.
- `crlb correct measure-gaps`: the gap investigation on the development pages; prints the distributions as counts and quantiles only.
- `crlb correct sample`: writes the review sample to CSV in `data/`.
- `crlb ocr analyse` (the existing specimen analysis, moved into `crlb.ocr`): extended with an option to compare corrected text, and with join precision and recall.

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
    link_id        INTEGER REFERENCES links(id),  -- RKD link anchoring this entry or copy, if any
    status         TEXT NOT NULL DEFAULT 'unreviewed'
);
CREATE INDEX segments_run_document ON segments(run_id, document_id);
CREATE INDEX segments_parent ON segments(parent_id);

-- Printed page numbers, derived from the page furniture.
CREATE TABLE printed_pages (
    run_id        INTEGER NOT NULL REFERENCES segmentation_runs(id),
    page_id       INTEGER NOT NULL REFERENCES pages(id),
    printed       TEXT,             -- printed page number, NULL for unnumbered pages
    rule          TEXT NOT NULL,    -- 'furniture' (read from the page) or 'interpolated'
    status        TEXT NOT NULL DEFAULT 'unreviewed',
    PRIMARY KEY (run_id, page_id)
);

-- Note markers in the text, linked to their note.
CREATE TABLE note_refs (
    id               INTEGER PRIMARY KEY,
    run_id           INTEGER NOT NULL REFERENCES segmentation_runs(id),
    word_id          INTEGER NOT NULL REFERENCES words(id),     -- the marker ('2', '*'), or the word carrying it
    note_segment_id  INTEGER NOT NULL REFERENCES segments(id),  -- kind = 'note'
    rule             TEXT NOT NULL,   -- 'superscript', 'digit after word', ...
    confidence       TEXT NOT NULL CHECK (confidence IN ('certain', 'probable', 'uncertain')),
    status           TEXT NOT NULL DEFAULT 'unreviewed'
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
10. **Index entries.** In the index documents and index sections: one `item` per index entry (heading term with its page references), with sub-entries as child items, recognised by indentation and the page-reference pattern (`123`, `123–125`, `n. 12`, `Fig. 58`, `No. 22`); entries continuing in the next column or on the next page stay one item. Step 5 parses them into terms with page references. Each index is segmented once: where a born-digital index excerpt exists (`excerpt_of`), the excerpt is used and the index pages of the main PDF are marked as a `section` labelled `index (see excerpt)` without items, so no index term is counted twice.

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
- The reference records of step 4: they also confirm the segments of their entries (boundaries of entry, copies, fields, items), so they are the hand-checked set for step 3 as well. A review command writes the segments of a sample of entries to a local file (HTML with the page images and boxes, or CSV) for checking them, never to the console.

### Order of work

1. POC volumes: XIX (4) (born-digital, `_links`) and II part 1 (`02_1_links`, ABBYY): furniture, sections, entries, copies, fields.
2. Check against the registration lists, if available.
3. Other volumes, one at a time, each with its own configuration. Older ABBYY volumes and born-digital volumes without links or bookmarks will need more rules.

### Code

Subpackage `crlb.segmentation`, schema `03_segmentation.sql`:

- `crlb segment`: runs the rules for the given documents with their configuration, writes `segmentation_runs`, `segments`, `printed_pages` and `note_refs`. Prints only counts and check results.
- `crlb segment review`: writes a review file for a sample of entries to `data/` (not printed).
- `data_manifest/segmentation/`: the per-volume configuration files (in git).

`crlb set-active` (core, see "Implementation") sets the active run of this and every other step.

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

Step 4 records **what the text says**, verbatim and in the structure of the RO model. Normalising values to the RKD lists and entry instructions, linking them to authorities (RKD Artists, TGN, AAT, Iconclass, Wikidata) and reconciling with the existing RKD/Axiell data is step 5. The step 4 tables have no authority columns; the URIs of the RO `*_id` properties are added in step 5 (`cluster_uris`) and combined at export.

### Target: Rubens Online records or RKDimages fields

It is not yet decided whether Rubens Online will have its own records for collections, agents, auctions and exhibitions, or will link to the RKD. The existing manual registration is done in RKDimages (Adlib/Axiell), following the [RKD manual](<project/Handleiding_RKDdatabases (15).pdf>) (_Handleiding RKDdatabases_), and the RO model carries an RKD mapping per property. Step 4 is therefore designed so that both targets can be served from the same rows: the verbatim values and the structure are the same, only the authority step (5) and the export differ.

What the RKD manual adds for step 4 and 5 (RKDimages, screens 1, 6, 7 and 8):

- **Provenance** is two chronological field groups: collections (_Herkomst 1_: collection name from a validation list, inventory number, how acquired, begin and end date in ISO format, a date remark such as `seen`, `reported`, `date of auction`, a special status such as lost or destroyed with its year) and auctions (_Herkomst 2_: a link to a record in the RKD auction file by barcode, lot number, vendor, buyer, amount and currency). This matches the RO split into collection stays and auctions, and so the `ro_collection_stays` / `ro_auctions` design below.
- **Conventions** that the normalisation (rules) follows: dates as `YYYY`, `YYYY-MM` or `YYYY-MM-DD`; no end date for the current or last known location; amounts without thousands separators, pounds/shillings/pence as `3.4.2` with currency `Lsd`; unknown owners as _Private collection_, unknown dealers as _Art dealer_, no provenance as _Whereabouts unknown_; one exhibition occurrence per venue for travelling exhibitions; `as by …`, `listed as '…'` in the remark of a literature or auction reference.
- **Literature** is cited by RKD citation abbreviations (`Jaffé 1989`, `Corpus Rubenianum Ludwig Burchard` with `pt. 18-2 (1986), p. 123-130, no. 6, copy 12`), which differ from the CRLB abbreviations (`Jaffé, Catalogo, 1989`). Mapping one to the other is part of step 5.
- **Attribution** is a status (current/rejected) with a qualification (`atelier van`, `naar`, `toegeschreven aan`, …) and an RKDartists name; copies link only to their prototype.
- **Privacy:** protected private owners may not be shown publicly in RKDimages (_Private collection_ with the name in a non-public field). The CRLB names private owners in the provenance. The export must respect this (see "Points to check first").

### Principles

The same as in steps 2 and 3:

1. **Rules first, LLM where rules fall short.** Step 3 has already cut fields into items (one provenance stage, one literature reference). Most fields can then be interpreted by rules; the LLM is used per item, on short inputs, for what rules cannot do reliably.
2. **No invented text.** The LLM returns only _spans_ (verbatim substrings of the item) and _choices from a closed list_ (e.g. a transfer method). The code checks that every span occurs in the item text and every choice is in the list; a violation rejects the answer. Parsing the verbatim values into the RO structure (dates to ISO start and end, dimensions to numbers, list choices to their RO label) is always done by rules.
3. **Fixed output format.** The LLM output is constrained to a JSON schema during generation (structured output / grammar-constrained decoding), so it is always well-formed.
4. **Traceable.** Every row records its source segment or item and its word range (and so its coordinates), the run, the method (`rules` or `llm`), and a review status.
5. **Local first.** See "Models".

**Division of work with step 5.** A value goes through four stages, each kept separately:

| Stage | Example | Where |
| :--- | :--- | :--- |
| verbatim | `c. 1598–1600`, `Duarte Pinto Coehlo`, `£3 4s 2d` | step 4, `*_text` columns |
| parsed into the RO structure | start `1598`, end `1600`; holder `Duarte Pinto Coehlo`; amount `£3 4s 2d` | step 4 |
| in the RKD form, with control-list terms | date remark; `Pinto Coelho, Duarte`; `3.4.2` + `Lsd` | step 5b, `normalised_values` |
| with LOD URIs | RKDartists, TGN, AAT URIs | step 5c, `cluster_uris` |

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
    field                TEXT NOT NULL,     -- 'lists', 'object', 'provenance', 'exhibition', 'literature', 'text'
    method               TEXT NOT NULL CHECK (method IN ('rules', 'llm', 'reference')),
    model                TEXT,              -- name, version, quantisation; NULL for rules
    runtime              TEXT,              -- e.g. 'ollama 0.x', 'llama.cpp server bNNNN'; NULL for rules
    prompt_sha           TEXT,              -- hash of prompt + JSON schema (both in git)
    correction_run_id    INTEGER REFERENCES correction_runs(id),
    segmentation_run_id  INTEGER NOT NULL REFERENCES segmentation_runs(id),
    version              TEXT NOT NULL,     -- git commit
    options              TEXT NOT NULL      -- JSON: thresholds, temperature, seed, ...
);

-- Every extracted row carries these columns (shown once here, written out in 04_extraction.sql):
--   segment_id     INTEGER NOT NULL REFERENCES segments(id)  -- the field or item it comes from
--   first_word_id  INTEGER NOT NULL REFERENCES words(id)     -- the same source as a word range,
--   last_word_id   INTEGER NOT NULL REFERENCES words(id)     -- stable across segmentation runs
--   run_id         INTEGER NOT NULL REFERENCES ro_runs(id)
--   status         TEXT NOT NULL DEFAULT 'unreviewed'
--                  CHECK (status IN ('unreviewed', 'accepted', 'corrected', 'rejected'))
--   note           TEXT                                      -- remark made when the row was created

-- Object: one per entry, copy and print.
CREATE TABLE ro_objects (
    id                          INTEGER PRIMARY KEY,
    segment_id ..., first_word_id ..., last_word_id ..., run_id ..., status ..., note ...,   -- the entry or copy segment
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
    segment_id ..., first_word_id ..., last_word_id ..., run_id ..., status ..., note ...,
    object_identifier             TEXT NOT NULL,   -- 'XIX (4), No. 22', '311963'
    object_identifier_type_label  TEXT NOT NULL,   -- 'CRLB nummer', 'RKD ID'
    link_id                       INTEGER REFERENCES links(id)
);

CREATE TABLE ro_attributions (
    id, object_id ..., segment_id ..., first_word_id ..., last_word_id ..., run_id ..., status ..., note ...,
    production_attribution_status  TEXT NOT NULL,  -- from Attribution status
    production_actor_label         TEXT,           -- 'Rubens', 'Workshop of Rubens', 'anonymous'
    attribution_text               TEXT NOT NULL,  -- verbatim
    is_current                     INTEGER NOT NULL
);

CREATE TABLE ro_dimensions (
    id, object_id ..., segment_id ..., first_word_id ..., last_word_id ..., run_id ..., status ..., note ...,
    dimension_value       REAL NOT NULL,
    dimension_unit_label  TEXT NOT NULL,     -- 'cm', 'mm'
    dimension_type_label  TEXT NOT NULL,     -- 'height', 'width', 'diameter', ...
    dimension_note        TEXT,              -- 'c.', 'approximately', 'sight size'
    dimensions_text       TEXT NOT NULL      -- verbatim: 'c. 68.5 × 52.5 cm'
);

CREATE TABLE ro_inscriptions (
    id, object_id ..., segment_id ..., first_word_id ..., last_word_id ..., run_id ..., status ..., note ...,
    inscription_type_label  TEXT,            -- from Inscription Type
    inscription_content     TEXT,            -- verbatim
    inscription_position    TEXT,            -- verbatim: 'horizontally below'
    inscription_note        TEXT             -- verbatim: 'in gold on grey'
);

-- Provenance and current location: collection stays.
CREATE TABLE ro_collection_stays (
    id, object_id ..., segment_id ..., first_word_id ..., last_word_id ..., run_id ..., status ..., note ...,
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
    collection_date_note         TEXT,              -- RKD 'Remark date': 'seen', 'reported', 'date of auction', ...
    collection_is_current        INTEGER NOT NULL,
    uncertain                    INTEGER NOT NULL DEFAULT 0   -- '?', 'possibly', 'probably'
);

-- Provenance: auctions (one row per object per sale).
CREATE TABLE ro_auctions (
    id, object_id ..., segment_id ..., first_word_id ..., last_word_id ..., run_id ..., status ..., note ...,
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
    segment_id ..., first_word_id ..., last_word_id ..., run_id ..., status ..., note ...,   -- the abbreviation-list item
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
    segment_id ..., first_word_id ..., last_word_id ..., run_id ..., status ..., note ...,
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
    id, object_id ..., segment_id ..., first_word_id ..., last_word_id ..., run_id ..., status ..., note ...,
    exhibition_id          INTEGER REFERENCES ro_exhibitions(id),  -- NULL = not resolved
    exhibition_cat_number  TEXT,
    exhibition_note        TEXT,
    reference_text         TEXT NOT NULL     -- verbatim item
);

CREATE TABLE ro_object_sources (
    id, object_id ..., segment_id ..., first_word_id ..., last_word_id ..., run_id ..., status ..., note ...,
    source_id              INTEGER REFERENCES ro_text_resources(id),  -- NULL = not resolved
    source_reference       TEXT,             -- full citation if not resolved
    source_page_reference  TEXT,             -- 'pp. 297–303', 'no. 109a', 'fig. 4'
    source_note            TEXT,             -- '(as Jan van Eyck)', 'repr.'
    reference_text         TEXT NOT NULL     -- verbatim item
);

-- Artistic relations: copy after, copied in print by, study for, ...; and cross-references.
CREATE TABLE ro_related_objects (
    id, object_id ..., segment_id ..., first_word_id ..., last_word_id ..., run_id ..., status ..., note ...,
    related_object_id                        INTEGER REFERENCES ro_objects(id),
    related_object_artistic_relation_type    TEXT,   -- from Artistic relation types
    related_object_artistic_description      TEXT,   -- when there is no related record
    relation_text                            TEXT NOT NULL  -- verbatim, e.g. 'see No. 21'
);

-- Descriptive text of the CRLB entry (TextResource of type 'CRLB-entry').
CREATE TABLE ro_text_paragraphs (
    id INTEGER PRIMARY KEY,
    text_resource_id  INTEGER NOT NULL REFERENCES ro_text_resources(id),
    segment_id ..., first_word_id ..., last_word_id ..., run_id ..., status ..., note ...,   -- the paragraph segment
    position          INTEGER NOT NULL,
    text              TEXT NOT NULL,     -- corrected text, note markers kept
    text_display      TEXT NOT NULL      -- figure references removed, for Rubens Online
);

CREATE TABLE ro_text_notes (
    id INTEGER PRIMARY KEY,
    text_resource_id  INTEGER NOT NULL REFERENCES ro_text_resources(id),
    segment_id ..., first_word_id ..., last_word_id ..., run_id ..., status ..., note ...,   -- the note segment
    number            TEXT NOT NULL,
    text              TEXT NOT NULL,
    text_display      TEXT NOT NULL,     -- 'Ibid.' and 'op. cit.' resolved, figure references removed
    paragraph_id      INTEGER REFERENCES ro_text_paragraphs(id)  -- paragraph containing the first marker
);

```

Notes:

- `ro_collection_stays` and `ro_auctions` share `position`, so the provenance chain can be read back in the order of the text.
- Collections, agents and places are not separate records yet: holders, consignors and places are verbatim text. Making them RO `Collection`, `Agent` and `Place` records with URIs is reconciliation (step 5); the same holder appears under different spellings across volumes.
- The RO `Auction` class is one record per sale event shared by all objects in it; step 4 keeps one row per object per sale, and step 5 merges rows that describe the same sale (same organiser, place and date).
- The word range (`first_word_id`, `last_word_id`) is stored next to `segment_id` because segment ids change with every segmentation run while words never change. Reference records, review carry-over and comparisons between runs use the word range.
- `note` is a remark made when the row is created (by the extraction or the annotator); later decisions are in `reviews`.
- Every LLM call is stored in `llm_calls` (see "Implementation"), which makes every LLM decision auditable and allows rerunning the checks or comparing models without calling the model again.
- An export script turns the active runs into RO records (JSON per object, following the RO property names), in the format agreed with the client. Only rows with `status` other than `rejected` are exported; whether `unreviewed` rows are exported is a decision for the client.

### Rules per field

- **Object core** (heading, material, date, location): patterns per volume, based on the style guide's fixed order (`Painting (Fig. x), attributed to …, Antwerp, St Paul’s Church; canvas, 158 x 106 cm.`). Dimensions: `H × W unit` with `x`, `×` or `:` (older volumes: `16 : 21.5 cm`), decimal point or comma; `c.`/`approximately` into `dimension_note`. Support and object name through mapping tables (`panel` → `paneel (hout)`, `canvas` → `doek`, `Painting` → `schilderij`, `BOZZETTO` → `olieverfschets`), kept in git and extended per volume.
- **Literature and exhibitions:** split already done in step 3. Each item is matched to the abbreviation list of the same part: the longest abbreviation that the item starts with (fuzzy on OCR text, exact on born-digital), the rest parsed into page reference, number, figures and note. Unmatched items are listed; the LLM is only used to split the leftovers.
- **Abbreviation lists:** each list item is split into abbreviation and full citation by layout (hanging indent) and pattern; the full citation is parsed into author, title, place, date by patterns from the 2015 bibliography rules, with the LLM for leftovers in older volumes.
- **Provenance:** per item: rules recognise the frequent fixed forms (`sale, London (Christie’s), 20–21 July 2011, lot 550`; `his sale`; `with the dealer X, Brussels, 1971`); everything else goes to the LLM. Dates in any form (`15ff. June 1874`, `in 1796 ?`, `(1612 - 23 October 1652)`) are parsed by rules into start/end.
- **Descriptive text:** paragraphs and notes from step 3; `text_display` by rules: remove `(Fig. 58)`, `(No. 15; Fig. 58)` and similar, resolve `Ibid.` to the previous note's citation and `op. cit.`/`loc. cit.` to the last citation of that author.

### LLM tasks

Each task is one prompt with a JSON schema, both in git (`src/crlb/extraction/prompts/<task>.md` and `.json`), with a few examples taken from the development set. Input is one item plus minimal context (the field name, the previous stage for provenance).

| Task                | Input                                        | Output                                                                                                                                                                           |
| :------------------ | :------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `provenance_stage`  | one provenance item                          | kind (collection/auction), spans for holder, place, dates, organiser, lot, price, consignor, buyer, note; choices for transfer method, collection type, currency; uncertain flag |
| `inscription`       | the inscription part of the material field   | spans for type word, position, content, note; choice for inscription type                                                                                                        |
| `location`          | the location field                           | spans for holder, place, inventory number; choice for collection type; lost/destroyed with cause                                                                                 |
| `attribution`       | heading or copy attribution                  | span for actor; choice for attribution status                                                                                                                                    |
| `citation_leftover` | an unmatched literature or abbreviation item | spans for author, title, date, pages                                                                                                                                             |

The checks on every answer: valid against the schema; every span is a substring of the input (after whitespace normalisation); every choice in the list; dates only as spans (parsed by rules afterwards). Rejected answers are stored in `llm_calls` with the reason and the item is flagged for review. Temperature 0 and a fixed seed, so a rerun gives the same answer.

### Models

The hardware available for development has no GPU, 15 GB RAM and 8 CPU cores. That is enough for a quantised model of about 7–8 billion parameters at a few tokens per second: fine for the POC (tens of entries), too slow for the whole corpus (tens of thousands of items).

Escalation path, each step only if the measurement of the previous one is insufficient:

1. **POC, local:** two open models of about 8B parameters, compared on the same development items: a Qwen model (strong at structured output) and a Mistral model (EU, the project's preference). Exact versions are chosen when the work starts.
2. **Full run, open model on EU infrastructure:** an open model of about 24–32B parameters on a rented GPU server in the EU, or the Mistral API (EU).
3. **Frontier model** (Claude, OpenAI, Gemini), only for the fields where 1 and 2 do not reach the threshold.

Runtime: Ollama or the llama.cpp server (a llamafile is llama.cpp packaged as one file; the results are the same), called from Python over HTTP, with the JSON schema passed for constrained decoding. The runtime is behind a small interface so a cloud API can be swapped in for step 2 or 3 of the escalation without changing the tasks.

Every model and runtime used is added to `README.md` under AI usage.

### Reference records

The offer states: "Op basis van de analyse, datamapping en reeds aanwezige data in RKD/Axiell, worden referentierecords aangemaakt. Deze referentierecords worden gebruikt voor controle, evaluatie en ontwikkeling van de AI prompt." Reference records are the ground truth for step 4, for the rules and the LLM alike: they say, for a selection of entries, exactly which rows step 4 should produce. They are made by hand.

**What a reference record contains.** For one entry (and its copies and prints): every row step 4 should produce, in the same tables and columns as the extraction (`ro_objects`, `ro_dimensions`, `ro_collection_stays`, `ro_auctions`, `ro_object_sources`, …), with the verbatim values as they are in the CRLB text and the list choices (transfer method, collection type, attribution status, …). Where the annotator knows the RKD term or authority of a value, it is recorded as well; it is loaded as a `reference` run of step 5 (`normalised_values`, `cluster_uris`) and serves as reference for that step. Reference rows are anchored to word ranges, not segment ids, so they stay valid when the segmentation is rerun. A reference record also confirms the step 3 segments of the entry (boundaries of entry, copies, fields and items), so the same set serves as hand-checked set for step 3.

**What a reference record follows: the CRLB text, not the RKD record.** RKD records may contain information from other sources, later updates or different interpretations. The reference record encodes what the CRLB text says, because that is what extraction can find. Where the RKD record differs, the difference is noted in the reference record (`note`), because it is useful input for step 5 (reconciliation).

**Selection.** Per POC volume (XIX (4) and II part 1) about 25 entries, chosen to cover the variation rather than at random:

- primary works, copies and prints; entries with many and with no copies;
- short and long provenance chains, with sales, dealers, inheritance, uncertain stages (`?`), `his sale`, prices in old currencies and cross-references (`see No. 21`);
- lost and destroyed works, whereabouts unknown;
- entries spread over two pages, and entries with damaged OCR (in II);
- entries with and without exhibitions, literature with resolved and unresolved abbreviations.

The selection is split once, with a fixed seed and recorded in git, into a **development set** (about 15 entries per volume) and a **test set** (about 10). Prompt examples (few-shot) and rule tuning use only the development set. The test set is used once per version of rules and prompts.

**How they are made.** Starting from an empty record costs most time; starting from a pre-filled one is faster but risks copying its mistakes. The procedure is therefore:

1. A script pre-fills a reference record per entry from the RKD/Axiell export (`rkd_records`, step 5a) where it exists (mapped to the step 4 columns), otherwise from a rules-only extraction run. The source of each pre-filled value is marked.
2. The annotator checks every value against the PDF (with the review file of step 3: the PDF region next to the values), corrects, completes and removes, and marks the record as done. Every pre-filled value must be confirmed or changed; untouched values block the import.
3. An import script checks the record (schema, list values, verbatim values occur in the entry text, positions consistent) and loads it into the database as a run with `method = 'reference'` (in `ro_runs`) and `status = 'accepted'`.

The pre-filled files are JSON per entry (readable in an editor, diffable), or a spreadsheet per table if the annotators prefer that; the import accepts both.

**Who.** Domain knowledge is needed to decide, for example, whether a stage is a collection stay or a sale, or what the transfer method is. The reference records are therefore made by or with the Rubenshuis, with the developer preparing, importing and checking them. A short **annotation guide** (in `doc/`) records the decisions, with examples, so that annotators decide in the same way and the LLM prompts can follow the same rules: what counts as a stage, how `his sale` and buyers are recorded, when a removal date is derived, how uncertainty is marked, which list value is used for borderline cases. Where the RO model, the RKD manual and the CRLB style guide differ, the guide states which one is followed in step 4 (in principle: the verbatim CRLB text for values, the RO lists for choices).

**Agreement.** If two annotators are available, a few entries (for example 5) are done by both, to measure agreement and to sharpen the annotation guide. Disagreement between people is an upper bound for what extraction can be expected to reach.

**Storage.** Reference records contain verbatim fragments of the CRLB text, so they are stored with the data (`data/reference/`, outside git), not in the public repository. The selection, the split, the annotation guide and the scripts are in git.

**Effort.** The offer reserves 3 person-days for analysis, mapping and reference records together. About 50 entries with all their copies is the realistic size within that budget; a larger set needs more time from the Rubenshuis.

### Measurement

**Reference data:** the reference records (see above). An export of the RKD/Axiell records of the POC volumes is requested to pre-fill them.

**Development and test split** per volume, as defined for the reference records: rules and prompts are tuned on development entries only; test entries are used once per version.

**Metrics** per field and per method:

- precision and recall of extracted values against the reference (exact and normalised match), per RO property;
- for provenance: correct number and order of stages, correct kind (collection/auction);
- for literature and exhibitions: share of items resolved to an abbreviation;
- for the LLM: share of rejected answers (schema, span, list), duration per item, and the projected time for the whole corpus;
- for review: share of rows accepted unchanged.

**Threshold.** As in step 2, the user sets beforehand what is sufficient per field. Fields below the threshold move up the escalation path; fields above it stay local.

### Entry export (Markdown)

Besides the structured records, each catalogue entry is exported as a whole, as one Markdown file: the text of the entry for reading, publishing and reuse ("records per entry van corpusdeel"). The Markdown is an **export, generated from the database**; the entry itself is stored in the tables of steps 1–4 (segments, corrected text, typography, notes, word ids and coordinates). The export can therefore be regenerated at any time, and other formats (HTML, TEI, JSON-LD) can be added later from the same tables.

Dialect: CommonMark with the GFM/Pandoc extensions for footnotes and YAML front matter, so the files can be converted with Pandoc and read by most tools.

Content of one file:

- **Front matter** (YAML): part, catalogue number, title, object type, RKD URI(s), document, PDF pages and printed pages, and the ids of the runs the file was generated from (correction, segmentation, extraction).
- **Heading** of the entry, then the unlabelled fields (material and dimensions, location, date) as paragraphs.
- **Labelled fields** as headings (`## Provenance`, `## Exhibited`, `## Copies`, `## Literature`, …), with list fields (provenance stages, references) as their text, and copies as a numbered list with their own `prov.:` and `lit.:` parts.
- **Description** as paragraphs, numbered as suggested in "Analyses entries".
- **Notes** as footnotes (`[^12]`), at the place of their marker (`note_refs`), with the note text at the end.
- **Italics** from the font flags of step 1 (titles of works, locations, quotations); bold for the heading.
- **Printed page breaks** as HTML comments (`<!-- p. 291 -->`), invisible when rendered but available for citation.

Two versions per entry, following "Analyses entries":

- **faithful:** the corrected text (step 2) as printed, with figure references and `Ibid.` as in the book;
- **display:** for Rubens Online, with figure references removed and `Ibid.`/`op. cit.` written out (`text_display` of `ro_text_paragraphs` and `ro_text_notes`).

Characters with a meaning in Markdown (`*`, `_`, `#`, `[`, `` ` ``, `<`) are escaped where they occur in the text; OCR note markers are often `*`.

Files are written to `data/entries/<part>/<catalogue number>.md` and `…-display.md`, outside git (they contain the CRLB text). Entities and links to authorities (step 5) are not marked in the Markdown; they are available in the database and the JSON export.

### Order of work

0. Annotation guide, selection and split of the reference entries; pre-filling and hand-checking of the development set.
1. XIX (4), a few entries: object core, literature and exhibitions (rules only) and the abbreviation list.
2. XIX (4): provenance with rules plus the local LLM; comparison of the two local models.
3. The same for II part 1 (`02_1_links`), with the OCR correction of step 2.
4. Descriptive text and notes (rules).
5. Measurement against the reference data; decision on escalation per field.

### Code

Subpackage `crlb.extraction`, schema `04_extraction.sql`:

- `crlb extract lists | objects | references | provenance | texts`: each writes one `ro_runs` row and its tables, and prints only counts.
- `crlb.llm` (core): the runtime interface, schema-constrained calls, the span and list checks, logging to `llm_calls`.
- `crlb/extraction/prompts/`: one prompt and one JSON schema per task.
- `crlb/extraction/vocabularies/`: the RO value lists used (Object names, Material_support, Attribution status, Transfer method, Collection Type, Currencies, Inscription Type, Source Types, Artistic relation types) as CSV with label and URI, and the CRLB-to-RO mapping tables.
- `crlb extract review`: writes a local review file per entry (the PDF region next to the extracted rows) to `data/`, never to the console.
- `crlb export ro` and `crlb export markdown`: the RO JSON records and the Markdown files of the entries, from the active runs.
- `crlb reference prefill | import`: pre-filled reference records (JSON per entry, in `data/reference/`) from the RKD/Axiell export or a rules run; checking and loading hand-made records as a `reference` run.
- `data_manifest/reference_selection.csv` (in git): the selected entries with their development/test assignment.
- `crlb extract compare`: compares an extraction run with the reference run per table and property, and writes the metrics (counts to the console, details to `data/`).

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
- the export produces RO property names and leaves out rejected rows;
- the reference import rejects a record with a value that does not occur in the entry text, a value outside a list, or an unconfirmed pre-filled value;
- the comparison aligns provenance stages by position and reports missing, extra and different stages;
- the Markdown export of an entry has valid front matter, headings per field, footnotes at the place of their markers, italics from the font flags, page-break comments, and escaped `*` and `_`; Pandoc converts it without warnings;
- the display version leaves out figure references and writes out `Ibid.`, the faithful version does not.

### Points to check first

- Whether the RO model will get its own records for collections, agents and auctions with Rubens Online URIs, or link to RKD records (validation lists for collections, the RKD auction file, RKD exhibitions, citation abbreviations, RKDartists); this decides what step 5 has to produce.
- How the RKD/Axiell export of the registered volumes is structured (Adlib field names and tags are in the RKD manual), so the pre-filling and comparison can be automated.
- Whether `unreviewed` rows may be exported.
- How private owners named in the CRLB provenance are handled in an export, given the RKD rule that protected private collections are not shown publicly.
- Who at the Rubenshuis makes the reference records, and how much time is available for them.

## Step 5: normalisation, enrichment and comparison

### Goal

Make the verbatim values of step 4 usable in Rubens Online or RKDimages, following the components of the offer:

| Part | Offer                                                                                                                                                                                                                 | In short                                                                   |
| :--- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------- |
| 5a   | "Op basis van beschikbare data in RKD/Axiell en registers uit de corpusdelen worden controlelijsten gemaakt"                                                                                                          | control lists: the accepted values, from RKD/Axiell and the corpus indexes |
| 5b   | "Component voor het normaliseren van geëxtraheerde gegevens op basis van controlelijsten en invoerinstructies"                                                                                                        | normalisation: each verbatim value to the value RKD would enter            |
| 5c   | "Component voor het verrijken van geëxtraheerde gegevens met een LOD URI"                                                                                                                                             | enrichment: URIs from linked open data vocabularies                        |
| 5d   | "Op beschrijvende teksten wordt een verrijking uitgevoerd … named entities … gekoppeld aan … authorities (bijvoorbeeld Iconclass). Voor entity recognition kan gebruik worden gemaakt van de indexen van het Corpus." | named entities in the descriptive texts                                    |
| 5e   | kick-off: "wat zit er al in de databank, en enkel het ontbrekende vullen we aan"                                                                                                                                      | comparison with the existing RKD/Axiell records                            |

This follows the architecture in the offer, where "data normalisatie" (with the control lists) and "data verrijking" (with the LOD vocabularies) are separate components. The distinction:

- **Normalisation (5b)** answers: _how would this value be entered in RKD?_ It uses local control lists (the RKD validation lists, the corpus indexes) and the RKD entry instructions (the [RKD manual](<project/Handleiding_RKDdatabases (15).pdf>), "Invoer RKD" in the project notes). Its result is a normalised value or a term of a control list.
- **Enrichment (5c)** answers: _which URI in a linked open data vocabulary does this value correspond to?_ It uses Getty AAT and TGN, Iconclass, Wikidata and the URIs of the RKD databases themselves.

Step 5 never changes the step 4 rows. Its results are separate layers that refer to them, with the same traceability (run, method, status) as the earlier steps.

### 5a: control lists

Control lists are the lists of accepted values that extracted values are normalised to. They are built from:

| List                   | Source                                                                                                                  | Used for                                                                |
| :--------------------- | :---------------------------------------------------------------------------------------------------------------------- | :---------------------------------------------------------------------- |
| artists                | RKDartists (names as validated in RKD)                                                                                  | attribution, makers of copies and prints                                |
| collections and owners | RKD validation list of collections (RKDimages _Herkomst 1_)                                                             | holders, current locations                                              |
| auctions               | RKD auction file (barcode, place, auction house, dates)                                                                 | provenance auctions                                                     |
| exhibitions            | RKD exhibitions validation list                                                                                         | exhibitions                                                             |
| literature             | RKD citation abbreviations (RKDlibrary), Rubenianum library (Brocade)                                                   | literature references, abbreviation lists                               |
| geographic terms       | RKD geographic terms                                                                                                    | places of collections, auctions, exhibitions, production                |
| RO value lists         | the RO data model (Object names, Material_support, Attribution status, Transfer method, Collection Type, Currencies, …) | the list choices of step 4                                              |
| corpus indexes         | the index documents and index sections of each part                                                                     | names, places, collections and subjects with the pages where they occur |
| existing records       | the RKDimages records of the CRLB works (`rkd_records`)                                                                 | the values already used for these works, and the comparison in 5e       |

Notes:

- **The corpus indexes** are the most valuable list for this corpus: they are compiled by the authors, use the spellings of the text, and say on which (printed) pages each name occurs. They are segmented in step 3 (rule 10: index entries, sub-entries, page references) and parsed here into terms with page references.
- **RKD data** comes either from an export of RKD/Axiell provided by the Rubenshuis or RKD, or from the RKD's public interfaces, whichever is available; to be agreed. It is stored locally with its source and date, so runs are reproducible.
- **Effort:** the offer reserves 3 person-days for creating the control lists ("Creëren controlelijsten").

```sql
-- One row per term of a control list (5a) or of a LOD vocabulary (5c).
CREATE TABLE control_terms (
    id            INTEGER PRIMARY KEY,
    vocabulary    TEXT NOT NULL,     -- 5a: 'rkdartists', 'rkd_collections', 'rkd_auctions', 'rkd_exhibitions',
                                     --     'rkd_citations', 'rkd_places', 'ro_lists', 'crlb_index'
                                     -- 5c: 'tgn', 'aat', 'iconclass', 'wikidata'
    uri           TEXT,              -- NULL for corpus index terms and list values without a URI
    label         TEXT NOT NULL,     -- preferred label, as entered in RKD for RKD lists
    alt_labels    TEXT,              -- JSON list of variant names and spellings
    type          TEXT,              -- person, collection, place, concept, subject, auction, exhibition, source
    extra         TEXT,              -- JSON: dates of life or activity, coordinates, broader terms, place of a collection, ...
    source        TEXT NOT NULL,     -- where it was fetched from
    retrieved_at  TEXT NOT NULL,
    segment_id    INTEGER REFERENCES segments(id)  -- for corpus index terms: the index entry
);
CREATE INDEX control_terms_vocabulary_label ON control_terms(vocabulary, label);

-- Page references of corpus index terms.
CREATE TABLE index_references (
    term_id       INTEGER NOT NULL REFERENCES control_terms(id),
    part          TEXT NOT NULL REFERENCES parts(part),
    printed_page  TEXT NOT NULL,     -- as printed in the index; resolved to pages through printed_pages
    note_number   TEXT,              -- 'n. 12' in the index
    entry_number  TEXT               -- if the index refers to catalogue numbers instead of pages
);

-- The RKD records themselves (export or interface), as fetched.
CREATE TABLE rkd_records (
    rkd_id        TEXT PRIMARY KEY,  -- RKDimages artwork number
    data          TEXT NOT NULL,     -- the raw record as JSON (Adlib field names or interface format)
    source        TEXT NOT NULL,     -- 'axiell export <date>', 'rkd interface', ...
    retrieved_at  TEXT NOT NULL
);
```

`rkd_records` is used twice: to pre-fill the reference records of step 4, and for the comparison in 5e. It is filled once per export and replaced as a whole when a newer export arrives.

### 5b: normalisation

For each value of step 4, the normalised value is the value as it would be entered in RKD: a term of a control list where the field is a validation field in RKD, or a value formatted according to the entry instructions where it is free text.

**Matching to a control list** (holder, artist, auction, exhibition, abbreviation, place):

1. **Candidates** from the relevant list: exact match on label or variant after simplification (case, accents, punctuation, word order `Last, First` against `First Last`, OCR-tolerant comparison for OCR volumes), then fuzzy matching.
2. **Filters and scores** from the context: dates of life against the date of the provenance stage, the place of a collection against the place in the text, the auction house and date for an auction, the corpus index of the same part (a holder listed in the index of the part is strong evidence), the values already in the RKD record of the same work.
3. **Decision:** a term is assigned automatically only if there is one candidate above the threshold and no close second. Otherwise the candidates are stored for review. An LLM may be used as a judge to choose between the candidates or decide "none of these", under the same constraint as in step 4: it can only return one of the given candidates.
4. **Clusters:** values that denote the same thing across entries and parts ("Duarte Pinto Coehlo", "D. Pinto Coelho") are grouped, with or without a term. A cluster is normalised once, and the result applies to all its values. If Rubens Online gets its own records for collections, agents and auctions, the clusters are the starting point for them; if it links to RKD, a cluster without an RKD term is a candidate for a new RKD term.

**Entry instructions** (RKD manual), applied by rules where a value is written out rather than taken from a list:

| Instruction                                                                                                                          | Example                                                                  |
| :----------------------------------------------------------------------------------------------------------------------------------- | :----------------------------------------------------------------------- |
| dates are already ISO start and end from step 4; 5b adds the uncertainty as date remark                                              | `c. 1598–1600` → remark `circa`                                          |
| no end date for the current or last known location                                                                                   | —                                                                        |
| date remarks in the standard wording                                                                                                 | `seen`, `reported`, `date of auction`, `bought at 1783 sale`             |
| personal names as `Last, First`                                                                                                      | `Duarte Pinto Coelho` → `Pinto Coelho, Duarte`                           |
| unnamed owners and dealers                                                                                                           | _Private collection_, _Art dealer_; no provenance: _Whereabouts unknown_ |
| amounts without thousands separators or currency; pounds, shillings and pence as `3.4.2` with currency `Lsd`; currency from the list | `£3 4s 2d` → `3.4.2`, `Lsd`                                              |
| inventory numbers in the institution's spelling, without `Inv. no.`                                                                  | `Inv. no. 2258` → `2258`                                                 |
| lot number only, without `lot`                                                                                                       | `lot 550` → `550`                                                        |
| one exhibition per venue for travelling exhibitions                                                                                  | `Liverpool – London, 1998–99` → two exhibitions                          |
| remarks on references and auctions in the standard wording                                                                           | `(as Jan van Eyck)` → `as by Jan van Eyck`; `listed as '…'`              |
| comment fields in American English, telegram style                                                                                   | —                                                                        |

The instructions are kept as a rules file in git (`src/crlb/enrichment/entry_rules/`), with the section of the RKD manual each rule implements, so the client can check them.

**Specific cases:**

- **Literature:** normalised per abbreviation of the abbreviation list (a few hundred per part), not per reference: `Jaffé, Catalogo, 1989` → RKD citation abbreviation `Jaffé 1989`; the page reference to the RKD form (`p. 22-24, no. 6a, ill.`). Every reference using that abbreviation inherits the result. This is a small, semi-manual task: automatic candidates, confirmed by a person.
- **Auctions:** step 4 rows of different objects that describe the same sale (same auction house, place and date) are merged into one sale, and matched to the RKD auction file.
- **Missing terms:** values with no term in an RKD list are collected in a request list in the format of the RKD manual (_Bijlage 2: Termen aanvragen voor validatielijsten_), so the Rubenshuis can request them from the RKD thesaurus instead of entering them one by one.

```sql
-- One row per run of 5b, 5c, 5d, 5e or 5f.
CREATE TABLE enrichment_runs (
    id                  INTEGER PRIMARY KEY,
    started_at          TEXT NOT NULL,
    part_of_step        TEXT NOT NULL CHECK (part_of_step IN ('5b', '5c', '5d', '5e', '5f')),
    method              TEXT NOT NULL CHECK (method IN ('rules', 'llm', 'gliner', 'manual', 'reference')),
    model               TEXT,
    ro_run_ids          TEXT NOT NULL,     -- JSON list of the ro_runs used
    correction_run_id   INTEGER REFERENCES correction_runs(id),      -- text the mentions were found in (5d)
    segmentation_run_id INTEGER REFERENCES segmentation_runs(id),    -- paragraphs and notes used (5d)
    based_on            TEXT,              -- JSON list of enrichment_runs this run builds on (e.g. 5c on 5b)
    version             TEXT NOT NULL,
    options             TEXT NOT NULL
);

-- A group of values (or entity mentions) that denote the same thing.
CREATE TABLE clusters (
    id           INTEGER PRIMARY KEY,
    run_id       INTEGER NOT NULL REFERENCES enrichment_runs(id),
    type         TEXT NOT NULL,          -- person, collection, place, auction, exhibition, source, subject, ...
    label        TEXT NOT NULL,          -- normalised form: the control-list term, or formatted per the entry instructions
    term_id      INTEGER REFERENCES control_terms(id),  -- the control-list term (5a lists); NULL = none found
    status       TEXT NOT NULL DEFAULT 'unreviewed'
);

-- One row per normalised value of step 4.
CREATE TABLE normalised_values (
    id                INTEGER PRIMARY KEY,
    run_id            INTEGER NOT NULL REFERENCES enrichment_runs(id),
    table_name        TEXT NOT NULL,         -- e.g. 'ro_collection_stays'
    row_id            INTEGER NOT NULL,
    column_name       TEXT NOT NULL,         -- e.g. 'holder_text'
    value_text        TEXT NOT NULL,         -- the verbatim value
    normalised_value  TEXT,                  -- as it would be entered in RKD
    cluster_id        INTEGER REFERENCES clusters(id),  -- for values matched to a control list
    rule              TEXT NOT NULL,         -- matching rule or entry instruction applied
    score             REAL,
    candidates        TEXT,                  -- JSON: candidate term ids with scores, for review
    status            TEXT NOT NULL DEFAULT 'unreviewed'
);
CREATE INDEX normalised_values_row ON normalised_values(table_name, row_id);
```

### 5c: enrichment with LOD URIs

Each cluster and each list value gets the URIs that identify it in linked open data vocabularies, as the RO model asks for in its `*_id` properties:

| What                                                                                          | Vocabulary (per the RO model)                               |
| :-------------------------------------------------------------------------------------------- | :---------------------------------------------------------- |
| artists, persons                                                                              | RKDartists URI; Wikidata as a second identifier             |
| works                                                                                         | RKDimages URI (from the RKD links in the PDFs)              |
| places                                                                                        | Getty TGN                                                   |
| object names, materials, supports, techniques, transfer methods, collection types, currencies | Getty AAT (most RO value lists already carry the AAT URI)   |
| depicted subjects, mythological and biblical figures, events                                  | Iconclass; Wikidata for persons and events not in Iconclass |
| literature                                                                                    | Rubenianum library (Brocade) record, RKDlibrary             |

How:

1. **Through the control list first.** An RKD term often already carries a URI, or a link to Wikidata, ULAN or TGN; an RO list value carries its AAT URI. These are taken over directly.
2. **Otherwise by matching** against a local copy of the vocabulary, with the same candidate, score and decision procedure as in 5b (with type and dates as filters: a place must be a TGN place, a person's dates must fit).
3. **Local copies:** external vocabularies are fetched in bulk (Getty and Wikidata SPARQL endpoints, Iconclass data downloads), limited to relevant subsets (for example TGN places in Europe, RKDartists active 1550–1750), and stored in `control_terms` with their source and date. Matching happens locally. This keeps runs reproducible and avoids sending names from the text (including private owners) to outside services one by one.
4. **Term lists** that contain no personal names (object names, materials, subjects) may also be reconciled through the NDE Termennetwerk, which offers AAT, Iconclass and other vocabularies behind one API; an earlier script for this exists (`scripts/archive/get_termennetwerk_URI.py`, see "Earlier work").

```sql
-- LOD URIs of a cluster (a cluster can have several: RKDartists and Wikidata, TGN and RKD places).
CREATE TABLE cluster_uris (
    id           INTEGER PRIMARY KEY,
    run_id       INTEGER NOT NULL REFERENCES enrichment_runs(id),
    cluster_id   INTEGER NOT NULL REFERENCES clusters(id),
    vocabulary   TEXT NOT NULL,          -- 'rkdartists', 'rkdimages', 'tgn', 'aat', 'iconclass', 'wikidata', ...
    uri          TEXT NOT NULL,
    term_id      INTEGER REFERENCES control_terms(id),
    rule         TEXT NOT NULL,          -- 'from control list', 'matched', 'manual'
    score        REAL,
    candidates   TEXT,                   -- JSON, for review
    status       TEXT NOT NULL DEFAULT 'unreviewed'
);
CREATE INDEX cluster_uris_cluster ON cluster_uris(cluster_id);
```

The export of step 4 (`crlb export ro`) takes the normalised values from 5b and fills the `*_id` properties of the RO model from `cluster_uris`, choosing per property the vocabulary the RO model prescribes, for rows with a status other than `rejected`.

### 5d: named entities in the descriptive texts

Approach as described in [NER.md](NER.md): structure first, then extraction with spans, then normalisation and enrichment of the entities through 5b and 5c.

- **Scope:** the paragraphs and notes of step 4 (`ro_text_paragraphs`, `ro_text_notes`). The structured fields are already covered by steps 4, 5b and 5c.
- **Entity types:** persons (artists, owners, historical and mythological figures), works (titles and cross-references such as `No. 15`), collections and institutions, places, dates, literature references (already resolved through the abbreviation lists), iconographic subjects.
- **Order of methods**, as in the earlier steps:
    1. **Gazetteer matching** with the control lists, above all the corpus index of the same part: a name from the index found on a page the index refers to is almost certainly a correct mention. Cross-references (`No. 15`, `Fig. 58`) and literature abbreviations by rules.
    2. **A compact local model** (GLiNER or similar, runs on CPU) for the remaining mentions, with the entity types as labels.
    3. **An LLM** only where 1 and 2 fall short, returning spans that are verified against the text.
- **Clusters and URIs:** mentions are grouped into the same clusters as the structured values (5b), and get their URIs through those clusters (5c), with Iconclass for subjects and mythological and biblical figures.
- **Role.** The same kind of entity plays different roles: in the text of a _Diana and Callisto_, "Diana" is a depicted subject, "Burchard" a scholar being cited, "Amalia van Solms" an owner, "Wildens" an artist working on the picture. Each mention gets a role relative to the work the text is about. The role is decided by rules where the context is clear (the title of the work, a provenance-like sentence, a literature reference) and otherwise by the model, as a choice from the list of roles.
- **Targets.** A mention points to a cluster (persons, places, collections, subjects), to another work (cross-references such as `No. 15` → `ro_objects`) or to a source (a literature reference in the text → `ro_text_resources`).
- **Aboutness.** Mentions with the role "depicted" (and the title of the work) are the evidence for the RO aboutness properties of the work: `represented_person`, `represented_place`, `represented_event`, `represented_type` and `subject`. These are recorded per work in `ro_subjects`, each with the mentions it is based on, and exported with the work.

```sql
CREATE TABLE entity_mentions (
    id                INTEGER PRIMARY KEY,
    run_id            INTEGER NOT NULL REFERENCES enrichment_runs(id),
    segment_id        INTEGER NOT NULL REFERENCES segments(id),   -- paragraph or note
    first_word_id     INTEGER NOT NULL REFERENCES words(id),
    last_word_id      INTEGER NOT NULL REFERENCES words(id),
    text              TEXT NOT NULL,       -- verbatim (corrected text)
    type              TEXT NOT NULL,       -- person, work, collection, place, date, source, subject
    role              TEXT,                -- 'depicted', 'owner', 'artist', 'scholar', 'place_of_work', 'other'
    object_id         INTEGER REFERENCES ro_objects(id),          -- the work the text is about
    cluster_id        INTEGER REFERENCES clusters(id),            -- target: person, place, collection, subject, ...
    target_object_id  INTEGER REFERENCES ro_objects(id),          -- target: another work ('No. 15')
    target_source_id  INTEGER REFERENCES ro_text_resources(id),   -- target: a source (literature reference)
    method            TEXT NOT NULL,       -- 'gazetteer', 'rules', 'gliner', 'llm'
    rule              TEXT,                -- which rule or prompt decided type, role and target
    score             REAL,
    candidates        TEXT,                -- JSON: candidate targets with scores, for review
    status            TEXT NOT NULL DEFAULT 'unreviewed'
);
CREATE INDEX entity_mentions_segment ON entity_mentions(segment_id);
CREATE INDEX entity_mentions_object ON entity_mentions(object_id);

-- RO aboutness of a work, derived from 'depicted' mentions and the title.
CREATE TABLE ro_subjects (
    id           INTEGER PRIMARY KEY,
    run_id       INTEGER NOT NULL REFERENCES enrichment_runs(id),
    object_id    INTEGER NOT NULL REFERENCES ro_objects(id),
    property     TEXT NOT NULL CHECK (property IN ('represented_person', 'represented_place',
                                                   'represented_event', 'represented_type', 'subject')),
    cluster_id   INTEGER REFERENCES clusters(id),   -- its URIs (Iconclass, RKDartists, TGN, Wikidata, AAT) via cluster_uris
    label        TEXT NOT NULL,
    evidence     TEXT NOT NULL,                     -- JSON: entity_mentions ids, and 'title' if taken from the title
    status       TEXT NOT NULL DEFAULT 'unreviewed'
);
CREATE INDEX ro_subjects_object ON ro_subjects(object_id);
```

Because mentions point to word ids, the validation tool can highlight them on the page, as for the OCR and the extracted fields. At most one of `cluster_id`, `target_object_id` and `target_source_id` is set per mention; none is set when the mention is found but not (yet) linked.

### 5e: comparison with RKD/Axiell

For each work with an RKD ID (from the RKD links in the PDFs, step 4 `ro_object_identifiers`), the normalised data is compared with the existing RKDimages record (`rkd_records`), per property:

- **same:** present in both and equal after normalisation;
- **only in CRLB:** a candidate addition to RKD/Rubens Online;
- **only in RKD:** information from other sources or later updates; kept, not touched;
- **different:** both present but different (another date, another order of provenance, another attribution); for review by the Rubenshuis.

Because 5b normalises to the RKD lists and entry instructions, most comparisons are exact comparisons of terms and formatted values, not of free text.

Works without an RKD ID are matched to RKD records through title, collection, inventory number and dimensions, as candidates for review; unmatched works are candidates for new records.

```sql
CREATE TABLE rkd_comparison (
    id             INTEGER PRIMARY KEY,
    run_id         INTEGER NOT NULL REFERENCES enrichment_runs(id),
    object_id      INTEGER NOT NULL REFERENCES ro_objects(id),
    rkd_id         TEXT,                -- NULL = no RKD record matched
    property       TEXT NOT NULL,       -- RO property or group, e.g. 'provenance', 'exhibition_id'
    crlb_value     TEXT,                -- JSON, normalised
    rkd_value      TEXT,                -- JSON
    verdict        TEXT NOT NULL CHECK (verdict IN ('same', 'only_crlb', 'only_rkd', 'different')),
    status         TEXT NOT NULL DEFAULT 'unreviewed'
);
```

The result is a report per part and per work: what can be added, and what needs a decision. Writing back to RKD/Axiell or the Rubens Online datahub is not part of this step; the export provides the data in the format agreed with the client.

### 5f: RKD links as products

The RKD links in the PDFs, together with the segments of step 3, make two products possible that the project notes ask for (section 4.3.2) and that need little extra work:

1. **A CRLB reference per RKDimages record.** For every work with an RKD ID (from the links, or matched in 5e): the CRLB part, catalogue number (and copy number), title, document, PDF page and printed page of the entry, and the Markdown export of the entry (step 4) as preview. This lets RKDimages (or Rubens Online) show a reference to the CRLB and a preview of the entry, without the full extraction having to be accepted first.
2. **Embedded RKD links in PDFs that lack them.** "Het is gewenst het toevoegen van embedded URL's verder te zetten voor de hoofdnummers": for the parts without `_links` version, a copy of the PDF is made with a link annotation on the heading of each main entry (not the copies), pointing to the RKDimages record found in 5e. The link rectangle is the bounding box of the heading words (step 1 coordinates). Only links with an accepted RKD match are added.

Rules:

- The original PDFs are never changed. The linked copies are new files (`data/linked/<part>/…_links.pdf`), stored with their own hash in `pdfs.sqlite` and registered as `documents` with `derived_from` set to the original, so `open_pdf` can open and check them. Their text is not extracted again.
- The existing link conventions are followed: the URI pattern of the most recent `_links` files (`https://rkd.nl/images/<id>`), one link per main number.
- Before adding links, the existing link annotations of a PDF are checked, so no duplicates are made.

```sql
-- One row per RKD link added to a PDF copy.
CREATE TABLE added_links (
    id                 INTEGER PRIMARY KEY,
    run_id             INTEGER NOT NULL REFERENCES enrichment_runs(id),
    document_id        INTEGER NOT NULL REFERENCES documents(id),   -- the original PDF
    linked_path        TEXT NOT NULL,                               -- the PDF copy with links (sqlar name)
    linked_sha256      TEXT NOT NULL,
    object_id          INTEGER NOT NULL REFERENCES ro_objects(id),  -- the main entry
    rkd_id             TEXT NOT NULL,
    uri                TEXT NOT NULL,
    page_id            INTEGER NOT NULL REFERENCES pages(id),
    x0                 REAL NOT NULL,
    y0                 REAL NOT NULL,
    x1                 REAL NOT NULL,
    y1                 REAL NOT NULL,
    status             TEXT NOT NULL DEFAULT 'unreviewed'
);
```

The CRLB references (product 1) are an export (CSV and JSON, one row per RKD ID), generated from `ro_objects`, `ro_object_identifiers`, `segments` and `printed_pages`; they need no table of their own.

### Measurement

- **Normalisation:** share of values matched to a control-list term automatically, sent to review, and without candidates; precision and recall of the terms against the reference records (step 4) where the annotators filled them in, and against review decisions; share of values correctly formatted per entry instruction (on a reviewed sample).
- **Clusters:** share of clusters that combine values wrongly (checked on a sample) and share of values that should have been combined but were not.
- **Enrichment:** share of clusters with a URI per vocabulary; precision on a reviewed sample.
- **NER:** recall against the corpus indexes (share of index entries found on the referenced page), precision on a reviewed sample; per entity type and per role.
- **Aboutness:** `ro_subjects` against the depicted subjects in the reference records, where the annotators filled them in.
- **Comparison:** share of works matched to an RKD record; per property the distribution over same/only CRLB/only RKD/different.
- **RKD link products:** share of main entries of each part with a CRLB reference and, for parts without links, with an added link; all added links checked on a sample by opening them in the linked PDF.

Thresholds per part are set by the user beforehand, as in steps 2 and 4.

### Order of work

1. **5a** Corpus indexes of the POC parts: segmentation (step 3, rule 10) and parsing into `control_terms` and `index_references`; RKD data for the POC parts (export or interface) into `control_terms` and `rkd_records`.
2. **5b** Normalisation of the abbreviation lists (literature and exhibitions), confirmed by hand; then of holders, places, auctions and artists, with clusters; the entry-instruction rules.
3. **5c** LOD URIs for the clusters and list values: first those carried by the control lists, then by matching against TGN, AAT and Iconclass subsets.
4. **5d** NER on the descriptive texts of the POC parts, gazetteer first.
5. **5e** Comparison with RKD for the works with an RKD ID.
6. **5f** CRLB references per RKD record; then linked PDF copies for the parts without links.

### Code

Subpackage `crlb.enrichment`, schema `05_enrichment.sql`:

- `crlb lists fetch`: fetches and caches the RKD lists and records (5a) and the LOD vocabulary subsets (5c) into `control_terms` and `rkd_records`; prints only counts.
- `crlb lists indexes`: turns the index segments of step 3 into `control_terms` and `index_references` (5a).
- `crlb normalise`: matching to control lists, clusters and the entry-instruction rules (5b); `crlb/enrichment/entry_rules/` holds the entry instructions, each with a reference to the section of the RKD manual.
- `crlb normalise request-terms`: the list of missing terms in the RKD request format.
- `crlb enrich`: LOD URIs for clusters and list values (5c).
- `crlb ner`: gazetteer matching, compact model and LLM fallback on the descriptive texts, roles and `ro_subjects` (5d), using `crlb.llm`.
- `crlb compare-rkd`: the comparison with RKD (5e), with a report file in `data/`.
- `crlb export rkd-references` and `crlb add-links`: the CRLB reference per RKD record, and the PDF copies with embedded RKD links (5f).
- `crlb enrich review`: a local review file with the value, its context in the PDF, the candidates and the URIs.

New dependencies, to be confirmed when the code is written: a SPARQL or HTTP client for the external lists (rapidfuzz, for fuzzy matching, is already a dependency), and a compact NER model (GLiNER) if 5d needs it. Every model used is added to `README.md` under AI usage.

### Tests

`tests/enrichment/`, on small hand-made control lists and values:

- name matching handles `Last, First` against `First Last`, accents and OCR errors, and does not assign a term when two candidates score close together;
- a candidate whose dates of life exclude the date of the provenance stage is filtered out;
- an LLM judge answer outside the candidate list is rejected;
- each entry-instruction rule gives the RKD form (`£3 4s 2d` → `3.4.2` + `Lsd`, `Inv. no. 2258` → `2258`, `lot 550` → `550`, `(as Jan van Eyck)` → `as by Jan van Eyck`, no end date for the current location);
- a literature abbreviation normalised once applies to all references using it;
- rows of different objects for the same sale are merged into one auction;
- an exhibition abbreviation with two venues becomes two exhibitions;
- a URI carried by a control-list term is taken over; a cluster can have URIs from several vocabularies, and the export picks the one the RO model prescribes;
- index parsing gives terms with printed pages and resolves them to page ids;
- an index term found on its referenced page is a gazetteer mention; the same term elsewhere needs more evidence;
- a figure named in the title of the work gets the role `depicted` and ends up in `ro_subjects` with the mention as evidence; a cited author gets `scholar` and does not;
- a cross-reference `No. 15` points to the right `ro_objects` row of the same part, and a mention never has more than one target;
- the comparison gives `same`, `only_crlb`, `only_rkd` and `different` correctly for a small pair of records;
- a linked PDF copy has exactly one new link per main entry, on the heading, with the right URI; the original file is unchanged; an existing link is not duplicated.

### Out of scope for this step

- Writing data into RKD/Axiell or the Rubens Online datahub.
- The validation interface (side-by-side view of the PDF with highlighted OCR, segments, values and entities, with accept/correct actions). All steps are designed for it (word ids, coordinates, status columns, `reviews`), but it is not yet planned as a step.

### Points to check first

- How RKD data can be obtained: an export from Axiell (by the Rubenshuis or RKD), or the RKD's public interfaces; and under which conditions.
- Which authority the RO model uses per property where several are possible (persons: RKDartists or Wikidata; places: TGN or RKD's geographic terms).
- Licences and terms of use of the external lists when cached and redistributed (Iconclass, Getty, RKD).
- Whether new terms should be requested from the RKD thesaurus, or Rubens Online keeps its own list.
- Whether the normalised values should follow the RKD entry instructions in every case, or Rubens Online has its own conventions for some fields (for example names as `First Last` for display).

## Earlier work

Work done before this project that the plan builds on or compares with:

- **`scripts/archive/OCR_correct.py`**: an experiment with LLM-based OCR correction, using the LoRA fine-tune `pbevan11/llama-3.1-8b-ocr-correction` of Llama 3.1 8B (Hugging Face `transformers` and `peft`, CUDA GPU required), tried on a CRLB example with the typical spacing errors ("Pierre Bautier, Les esquisses d e R ubens au M u sée d e B ru xelles"). The model rewrites the text freely, which is what step 2 avoids; it is a candidate for comparison in step 2c, as a judge between candidates, not as a rewriter. Running it needs a GPU, which the development machine does not have.
- **`scripts/archive/get_termennetwerk_URI.py`**: reconciliation of a CSV list of terms against the NDE Termennetwerk GraphQL API (`termennetwerk-api.netwerkdigitaalerfgoed.nl`), with Iconclass or AAT as source, writing URI and preferred label per term. Useful for step 5c for term lists without personal names; for names, step 5 matches against local copies instead. The script queries one term at a time, keeps every hit without a decision, and has Dutch identifiers; it would be rewritten to the conventions of this repository if reused.
- **Un2Structured** (Arnoud Wils, AI4Culture hackathon, KU Leuven, February 2025): extraction of structured JSON from Corpus Rubenianum PDFs, focused on provenance and iconography, with LlamaParse (PDF parsing), LlamaIndex, the Cohere LLM API and Pydantic; the team tweaked its prompt templates extensively and raised the question of how to valorise the extracted data ([Europeana write-up, March 2025](https://pro.europeana.eu/post/how-ai-is-transforming-digital-cultural-heritage)). With the team it was agreed to explore a continuation, starting with the technical requirements. The write-up does not describe how pages were segmented, how results were checked or how well it worked; if its code or results are available, they serve as a comparison for step 4. Its question about valorisation is what steps 4 and 5 answer: records in the RO model, normalised to the RKD lists, with LOD URIs.
- **A script that splits the PDFs on the RKD links**, mentioned at the kick-off, has not been found in the project data. If it turns up, it is compared with the entry detection of step 3.

## Knowledge sharing

The offer commits to sharing the scripts and the knowledge built in this work package:

- **Open licence.** The repository is published on GitHub under the MIT licence (`LICENSE`, copyright Datable). The licence covers the code and the documentation in the repository. It does not cover the CRLB content: PDFs, extracted text, reference records and exports stay in `data/`, outside git.
- **Language.** Everything in the repository is in English: code, comments, documentation, commit messages and the plan. This was agreed with the client.
- **Documentation** of the procedures, the scripts and the architecture:
    - `README.md`: what the project does, how to install and run it (`uv sync`, the `crlb` command, `make` targets), the external tools and models with their versions, and the AI tools and models used in development and production;
    - `doc/plan.md` (this plan), `doc/OCR.md`, `doc/NER.md` and per step a short description of what was actually built and measured, kept up to date with the code;
    - the annotation guide for the reference records (step 4) and the entry-instruction rules (step 5b), which are written for domain experts;
    - docstrings and tests in the code, so each step can be understood and rerun on its own.
- **Involvement of the client.** Each step ends with a measurement against a threshold the client agrees to, and the review files of each step are made for the Rubenshuis to check. Decisions that are the client's (open questions, thresholds, export of unreviewed data) are listed in the plan.
- **Workshop.** The offer includes a workshop (Workshop 2) for an audience that can use Python and AI. Its material is built from the repository: the plan, the measurements per step, and runnable examples on a small, shareable sample (for example a born-digital page or synthetic test PDFs, since the CRLB content itself cannot be published).

## Review and corrections (all steps)

Every table from step 2 on that holds results has a `status` column (`unreviewed`, `accepted`, `corrected`, `rejected`): `corrected_words`, `segments`, `printed_pages`, `note_refs`, the `ro_*` tables, and the step 5 tables. The rows of a run are never changed after the run. A reviewer's decision, including a corrected value, is therefore stored separately, as an event:

```sql
-- One row per review decision, for any table with a status column.
CREATE TABLE reviews (
    id           INTEGER PRIMARY KEY,
    table_name   TEXT NOT NULL,      -- e.g. 'segments', 'ro_collection_stays', 'normalised_values', 'entity_mentions'
    row_id       INTEGER NOT NULL,
    column_name  TEXT,               -- NULL = the row as a whole
    action       TEXT NOT NULL CHECK (action IN ('accept', 'correct', 'reject', 'comment')),
    old_value    TEXT,               -- the value at the time of review
    new_value    TEXT,               -- for 'correct'
    reviewer     TEXT NOT NULL,
    reviewed_at  TEXT NOT NULL,      -- ISO 8601, UTC
    comment      TEXT
);
CREATE INDEX reviews_row ON reviews(table_name, row_id);
```

Rules:

- The `status` of a row follows from its latest review (`accept` → `accepted`, `correct` → `corrected`, `reject` → `rejected`); rows without a review are `unreviewed`. The review scripts and the validation tool write a review and update the `status` in the same transaction, so `status` stays a quick filter.
- Exports and later steps use the **effective value**: the `new_value` of the latest `correct` review of that column, or otherwise the value in the row.
- A rerun of a step produces new rows in a new run. Reviews of the old run are carried over to the new run where the row is unchanged (same word range, same values); the others are listed for review again.
- Review decisions are the most expensive data in the project. `crlb.sqlite` is backed up before every run and every import, and `reviews` can be exported to a file on its own.

## Volumes without a PDF

Eleven volumes exist only as Word files: I, VII, VIII, X, XIII (1), XV, XVI, XXII (1), XXIV, XXVI (1) and XXVI (2.3). Four of them also have original scans (XV, XXII (1), XXVI (1), XXVI (2.3); VI and XIII (3) have scans as well but already have a PDF). There is no decision yet; the options are:

1. Import the Word text. Fast, but there is nothing to validate it against and its OCR quality is unknown. It also needs schema changes: a `text_source` value `docx`, words without coordinates, and documents without a PDF in `pdfs.sqlite`; every later step works on word ids and coordinates, so this has to be designed carefully.
2. OCR the scans where they exist (this gives text with coordinates, comparable to the PDFs). Redoing OCR is not planned for now, so this option is deferred.
3. Leave them out for now.

Before choosing, measure the quality of the Word text on a few pages that also exist as ABBYY PDF (for example `Boekdeel_II_I.docx` against `CRLB_02_1_links`, both 416 pages), with the same method as the OCR quality test.

## Open questions

- Sub-part or physical volume for `02_1`/`02_2`, `18_1`, `21_1`/`21_2` and `23_1`/`23_2`/`23_3`: to be read from the colophons and checked with the Rubenshuis.
- Whether XIII (2) `CRLB_13_2_1` and `CRLB_13_2_2` (both 392 pages, created a minute apart) are two volumes or two versions of one.
- Where the Word files come from (which OCR, made by whom), and whether there are two versions on purpose (`Boekdeel_X.docx` and `Boekdeel_X(1).docx`).
- Whether a PDF of XXVI (2.3) exists.
- Whether the final edition of XXVII (2) is available instead of the proof.
