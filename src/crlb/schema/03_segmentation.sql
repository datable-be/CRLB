-- Step 3: segmentation. Structural parts of a volume as ranges of raw word ids;
-- nothing in the text is changed or interpreted.

-- One row per segmentation run.
CREATE TABLE segmentation_runs (
    id                 INTEGER PRIMARY KEY,
    started_at         TEXT NOT NULL,     -- ISO 8601, UTC
    correction_run_id  INTEGER REFERENCES correction_runs(id),  -- text used for matching; NULL = raw
    version            TEXT,              -- git commit of the code, '-dirty' if the tree had changes
    options            TEXT NOT NULL      -- JSON: the volume configurations used, sample
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
    label          TEXT,            -- section name, entry number ('22', '10a', 'R3'),
                                    -- copy number ('(3)'), field name ('provenance', 'notes', ...),
                                    -- note number ('19'), item position
    first_word_id  INTEGER NOT NULL REFERENCES words(id),
    last_word_id   INTEGER NOT NULL REFERENCES words(id),
    rule           TEXT NOT NULL,   -- which rule created it
    confidence     TEXT NOT NULL CHECK (confidence IN ('certain', 'probable', 'uncertain')),
    reason         TEXT,            -- e.g. 'heading pattern; bold 11.2 pt; RKD link'
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

-- Note markers in the text, linked to their note (not filled in the POC).
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
