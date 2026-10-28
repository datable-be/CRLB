-- Step 2: OCR correction. The lexicon decides whether a joined form is a real
-- word; the correction layer refers to words.id and never changes the raw text.

-- Word forms of the born-digital volumes (casefolded, NFC), replaced completely
-- by every `crlb lexicon` run.
CREATE TABLE lexicon (
    form          TEXT PRIMARY KEY,   -- casefolded, NFC
    born_digital  INTEGER NOT NULL,   -- count in the born-digital sources
    ocr           INTEGER NOT NULL    -- count in the OCR documents of the database (for statistics only)
);

-- Two consecutive words on one line of a born-digital source, to compare "a part" with "apart".
CREATE TABLE bigrams (
    first         TEXT NOT NULL,
    second        TEXT NOT NULL,
    born_digital  INTEGER NOT NULL,
    PRIMARY KEY (first, second)
);

-- The born-digital PDFs the lexicon was built from, read directly from disk.
CREATE TABLE lexicon_sources (
    path      TEXT PRIMARY KEY,   -- as in data_manifest/lexicon_sources.csv
    sha256    TEXT NOT NULL,
    pages     INTEGER NOT NULL,
    words     INTEGER NOT NULL,
    built_at  TEXT NOT NULL       -- ISO 8601, UTC
);

-- One row per correction run.
CREATE TABLE correction_runs (
    id           INTEGER PRIMARY KEY,
    started_at   TEXT NOT NULL,     -- ISO 8601, UTC
    step         TEXT NOT NULL,     -- '2a', later '2b', '2c'
    based_on     INTEGER REFERENCES correction_runs(id),  -- NULL = raw layer
    version      TEXT,              -- git commit of the code, '-dirty' if the tree had changes
    options      TEXT NOT NULL      -- JSON: thresholds, sample, lexicon summary
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
    reason         TEXT,            -- e.g. 'pieces: M|useum; bd=412'
    status         TEXT NOT NULL DEFAULT 'unreviewed'
);
CREATE INDEX corrected_words_run_page ON corrected_words(run_id, page_id);
CREATE INDEX corrected_words_run_first ON corrected_words(run_id, first_word_id);

-- Cases a rule considered but did not change.
CREATE TABLE correction_flags (
    id             INTEGER PRIMARY KEY,
    run_id         INTEGER NOT NULL REFERENCES correction_runs(id),
    page_id        INTEGER NOT NULL REFERENCES pages(id),
    first_word_id  INTEGER NOT NULL REFERENCES words(id),
    last_word_id   INTEGER NOT NULL REFERENCES words(id),
    rule           TEXT NOT NULL,
    candidate      TEXT NOT NULL,   -- the joined form that was not applied
    reason         TEXT NOT NULL    -- e.g. 'all 2 pieces are words; bd=40; doc=3; bigram=30'
);
