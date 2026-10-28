-- Step 1: the raw text of the PDFs, plus the tables shared by all steps.
-- The tables of step 1 are never updated after the build; later steps add
-- their own tables that refer to words.id, pages.id or documents.id.

-- One row per build, for provenance.
CREATE TABLE build_runs (
    id            INTEGER PRIMARY KEY,
    started_at    TEXT NOT NULL,      -- ISO 8601, UTC
    git_commit    TEXT,               -- commit of the code, '-dirty' if the tree had changes
    tool          TEXT NOT NULL,      -- 'pymupdf'
    tool_version  TEXT NOT NULL,      -- PyMuPDF and MuPDF version
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
    pdf_version    TEXT,                   -- PDF metadata 'format', e.g. 'PDF 1.4'
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
    text         TEXT NOT NULL,       -- raw page text
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
    font      TEXT NOT NULL,         -- font of the span with most of the word's characters
    size      REAL NOT NULL,         -- font size of that span, points
    flags     INTEGER NOT NULL,      -- PyMuPDF span flags: 1 superscript, 2 italic, 16 bold, ...
    styles    INTEGER NOT NULL       -- number of distinct (font, size, flags) spans in the word; > 1 = mixed
);
CREATE INDEX words_page ON words(page_id);

-- One row per link annotation, as returned by page.get_links().
CREATE TABLE links (
    id           INTEGER PRIMARY KEY,
    page_id      INTEGER NOT NULL REFERENCES pages(id),
    kind         TEXT NOT NULL,      -- 'uri', 'goto', 'gotor', 'named', 'launch', 'none'
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

-- Shared: the run that later steps and exports use, per step.
CREATE TABLE active_runs (
    step     TEXT PRIMARY KEY,      -- '2', '3', '4:<field>', '5b', '5c', '5d', '5e', '5f'
    run_id   INTEGER NOT NULL,      -- id in the run table of that step
    set_at   TEXT NOT NULL,         -- ISO 8601, UTC
    note     TEXT                   -- why this run was made active
);

-- Shared: every call to a language model, in any step.
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
