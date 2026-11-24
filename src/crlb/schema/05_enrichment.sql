-- Step 5: normalisation and enrichment. The control lists (5a) and the
-- normalised values of step 4 (5b); the step 4 rows are never changed.

-- One row per term of a control list: a corpus index entry or an RKD term.
CREATE TABLE control_terms (
    id            INTEGER PRIMARY KEY,
    vocabulary    TEXT NOT NULL,     -- 'crlb_index'; 'rkd_collections', 'rkdartists', 'rkd_auctions',
                                     -- 'rkd_actors', 'rkd_thesaurus'
    uri           TEXT,              -- NULL for corpus index terms
    label         TEXT NOT NULL,     -- as printed in the index, or the preferred RKD name
    alt_labels    TEXT,              -- JSON list of variant names
    type          TEXT,              -- person, collection, place, dealer, auctioneer, work, auction, ...
    extra         TEXT,              -- JSON: part, broader term and path of an index entry; RKD records using an RKD term, ...
    source        TEXT NOT NULL,     -- 'segmentation run 23', 'RKD Knowledge Graph (SPARQL)'
    retrieved_at  TEXT NOT NULL,
    segment_id    INTEGER REFERENCES segments(id)  -- for corpus index terms: the index item
);
CREATE INDEX control_terms_vocabulary_label ON control_terms(vocabulary, label);
CREATE UNIQUE INDEX control_terms_uri ON control_terms(vocabulary, uri) WHERE uri IS NOT NULL;

-- Page references of corpus index terms; in the collections index also the catalogue number.
CREATE TABLE index_references (
    id            INTEGER PRIMARY KEY,
    term_id       INTEGER NOT NULL REFERENCES control_terms(id),
    segment_id    INTEGER NOT NULL REFERENCES segments(id),  -- the item the reference is printed in
    part          TEXT NOT NULL REFERENCES parts(part),
    printed_page  TEXT,              -- as printed; NULL for a work of the collections index without pages
    note_number   TEXT,              -- '4' for '11 n. 4'
    figure        TEXT,              -- '12' for 'fig. 12'
    entry_number  TEXT,              -- collections index: the catalogue number ('4', '12c'), checked against the entries
    entry_text    TEXT,              -- collections index: the number as printed ('No. 22, Copy 4', OCR 'Cat. nb')
    copy_text     TEXT,              -- collections index: 'Copy', 'Copy 4'
    attribution   TEXT               -- collections index: 'After Rubens, painting', 'José Risueno, paintings after Rubens'
);
CREATE INDEX index_references_term ON index_references(term_id);

-- The RKDimages records of the CRLB works, as fetched: all triples of the record's own nodes.
CREATE TABLE rkd_records (
    rkd_id        TEXT PRIMARY KEY,  -- RKDimages artwork number
    data          TEXT NOT NULL,     -- JSON list of [subject, predicate, object, object type]
    source        TEXT NOT NULL,     -- 'RKD Knowledge Graph (SPARQL)'
    retrieved_at  TEXT NOT NULL
);

-- One row per run of 5b (and later 5c-5f).
CREATE TABLE enrichment_runs (
    id                  INTEGER PRIMARY KEY,
    started_at          TEXT NOT NULL,
    part_of_step        TEXT NOT NULL CHECK (part_of_step IN ('5b', '5c', '5d', '5e', '5f')),
    method              TEXT NOT NULL CHECK (method IN ('rules', 'llm', 'gliner', 'manual', 'reference')),
    model               TEXT,
    ro_run_ids          TEXT NOT NULL,     -- JSON list of the ro_runs used
    correction_run_id   INTEGER REFERENCES correction_runs(id),
    segmentation_run_id INTEGER REFERENCES segmentation_runs(id),
    based_on            TEXT,              -- JSON list of enrichment_runs this run builds on
    version             TEXT,              -- git commit of the code
    options             TEXT NOT NULL      -- JSON: sample, thresholds, control lists used
);

-- A group of values that denote the same thing.
CREATE TABLE clusters (
    id           INTEGER PRIMARY KEY,
    run_id       INTEGER NOT NULL REFERENCES enrichment_runs(id),
    type         TEXT NOT NULL,          -- holder, place, auction house
    label        TEXT NOT NULL,          -- the RKD term, else the index term, else the formatted value
    term_id      INTEGER REFERENCES control_terms(id),  -- NULL = no term assigned
    status       TEXT NOT NULL DEFAULT 'unreviewed'
);

-- One row per normalised value of step 4.
CREATE TABLE normalised_values (
    id                INTEGER PRIMARY KEY,
    run_id            INTEGER NOT NULL REFERENCES enrichment_runs(id),
    table_name        TEXT NOT NULL,         -- 'ro_collection_stays', 'ro_auctions'
    row_id            INTEGER NOT NULL,
    column_name       TEXT NOT NULL,         -- 'holder_text', ...
    value_text        TEXT NOT NULL,         -- the verbatim value
    normalised_value  TEXT,                  -- as it would be entered in RKD
    cluster_id        INTEGER REFERENCES clusters(id),
    rule              TEXT NOT NULL,         -- 'matched', 'review', 'entry instruction: ...'
    score             REAL,                  -- of the assigned or best candidate
    candidates        TEXT,                  -- JSON: candidate terms with scores and evidence
    status            TEXT NOT NULL DEFAULT 'unreviewed'
                      CHECK (status IN ('unreviewed', 'review', 'accepted', 'corrected', 'rejected'))
);
CREATE INDEX normalised_values_row ON normalised_values(table_name, row_id);
