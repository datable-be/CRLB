-- Step 4: extraction. The segments of step 3 as records in the Rubens Online
-- (RO) data model: verbatim values and their parsing into the RO structure.
-- Column names follow the RO model where a column is an RO property; the extra
-- columns are for traceability.
--
-- Every extracted row carries:
--   segment_id     the field or item it comes from (step 3)
--   first_word_id  the same source as a word range, stable across segmentation runs
--   last_word_id
--   run_id         the extraction run
--   status         review status
--   note           remark made when the row was created

-- One row per extraction run (per field and method).
CREATE TABLE ro_runs (
    id                   INTEGER PRIMARY KEY,
    started_at           TEXT NOT NULL,     -- ISO 8601, UTC
    field                TEXT NOT NULL,     -- 'objects', 'references', 'provenance'
    method               TEXT NOT NULL CHECK (method IN ('rules', 'llm', 'reference')),
    model                TEXT,              -- name, file and SHA-256; NULL for rules
    runtime              TEXT,              -- e.g. 'llama.cpp server b6000'; NULL for rules
    prompt_sha           TEXT,              -- hash of prompt + JSON schema; NULL for rules
    correction_run_id    INTEGER REFERENCES correction_runs(id),
    segmentation_run_id  INTEGER NOT NULL REFERENCES segmentation_runs(id),
    version              TEXT,              -- git commit of the code, '-dirty' if the tree had changes
    options              TEXT NOT NULL      -- JSON: sample, objects run, model options
);

-- Object: one per entry, copy and print.
CREATE TABLE ro_objects (
    id                      INTEGER PRIMARY KEY,
    segment_id              INTEGER NOT NULL REFERENCES segments(id),  -- the entry or copy
    first_word_id           INTEGER NOT NULL REFERENCES words(id),
    last_word_id            INTEGER NOT NULL REFERENCES words(id),
    run_id                  INTEGER NOT NULL REFERENCES ro_runs(id),
    status                  TEXT NOT NULL DEFAULT 'unreviewed'
                            CHECK (status IN ('unreviewed', 'accepted', 'corrected', 'rejected')),
    note                    TEXT,
    part                    TEXT NOT NULL REFERENCES parts(part),
    crlb_number             TEXT NOT NULL,   -- '22', '10a', '22, Copy 3'
    title_value             TEXT,
    title_type_label        TEXT,            -- from Title types: 'titel'
    object_name_label       TEXT,            -- from Object names: 'schilderij'
    object_name_text        TEXT,            -- verbatim: 'Painting', 'BOZZETTO'
    production_date_label   TEXT,            -- verbatim: 'c. 1598–1600'
    production_date_start   TEXT,            -- YYYY[-MM[-DD]]
    production_date_end     TEXT,
    material_note           TEXT,            -- verbatim: 'Oil on panel'
    material_support_label  TEXT,            -- from Material_support: 'paneel (hout)'
    destruction_cause       TEXT,            -- from Destruction cause: 'vermist'
    destruction_text        TEXT             -- verbatim: 'presumably lost'
);
CREATE INDEX ro_objects_run ON ro_objects(run_id);
CREATE INDEX ro_objects_segment ON ro_objects(segment_id);

CREATE TABLE ro_object_identifiers (
    id                            INTEGER PRIMARY KEY,
    object_id                     INTEGER NOT NULL REFERENCES ro_objects(id),
    segment_id                    INTEGER NOT NULL REFERENCES segments(id),
    first_word_id                 INTEGER NOT NULL REFERENCES words(id),
    last_word_id                  INTEGER NOT NULL REFERENCES words(id),
    run_id                        INTEGER NOT NULL REFERENCES ro_runs(id),
    status                        TEXT NOT NULL DEFAULT 'unreviewed'
                                  CHECK (status IN ('unreviewed', 'accepted', 'corrected', 'rejected')),
    note                          TEXT,
    object_identifier             TEXT NOT NULL,   -- 'XIX (4), No. 22', '58171'
    object_identifier_type_label  TEXT NOT NULL,   -- from Identifier Types: 'CRLB nummer', 'RKD ID'
    link_id                       INTEGER REFERENCES links(id)
);

-- Attributions stated in the text ('by Lucas Vorsterman', 'possibly by Anthony van Dyck').
CREATE TABLE ro_attributions (
    id                             INTEGER PRIMARY KEY,
    object_id                      INTEGER NOT NULL REFERENCES ro_objects(id),
    segment_id                     INTEGER NOT NULL REFERENCES segments(id),
    first_word_id                  INTEGER NOT NULL REFERENCES words(id),
    last_word_id                   INTEGER NOT NULL REFERENCES words(id),
    run_id                         INTEGER NOT NULL REFERENCES ro_runs(id),
    status                         TEXT NOT NULL DEFAULT 'unreviewed'
                                   CHECK (status IN ('unreviewed', 'accepted', 'corrected', 'rejected')),
    note                           TEXT,
    production_attribution_status  TEXT NOT NULL,  -- from Attribution status: 'huidig', 'mogelijk van'
    production_actor_label         TEXT NOT NULL,  -- verbatim: 'Anthony van Dyck'
    attribution_text               TEXT NOT NULL,  -- verbatim: 'possibly by Anthony van Dyck'
    is_current                     INTEGER NOT NULL
);

CREATE TABLE ro_dimensions (
    id                    INTEGER PRIMARY KEY,
    object_id             INTEGER NOT NULL REFERENCES ro_objects(id),
    segment_id            INTEGER NOT NULL REFERENCES segments(id),
    first_word_id         INTEGER NOT NULL REFERENCES words(id),
    last_word_id          INTEGER NOT NULL REFERENCES words(id),
    run_id                INTEGER NOT NULL REFERENCES ro_runs(id),
    status                TEXT NOT NULL DEFAULT 'unreviewed'
                          CHECK (status IN ('unreviewed', 'accepted', 'corrected', 'rejected')),
    note                  TEXT,
    dimension_value       REAL NOT NULL,
    dimension_unit_label  TEXT NOT NULL,     -- from Dimension Unit: 'cm', 'mm'
    dimension_type_label  TEXT NOT NULL,     -- from Dimension Type: 'hoogte', 'breedte'
    dimension_note        TEXT,              -- verbatim: 'c.', 'approximately'
    dimensions_text       TEXT NOT NULL      -- verbatim: 'c. 68.5 × 52.5 cm'
);

-- Provenance and current location: collection stays. They share `position`
-- with ro_auctions, so the chain reads back in the order of the text.
CREATE TABLE ro_collection_stays (
    id                          INTEGER PRIMARY KEY,
    object_id                   INTEGER NOT NULL REFERENCES ro_objects(id),
    segment_id                  INTEGER NOT NULL REFERENCES segments(id),
    first_word_id               INTEGER NOT NULL REFERENCES words(id),
    last_word_id                INTEGER NOT NULL REFERENCES words(id),
    run_id                      INTEGER NOT NULL REFERENCES ro_runs(id),
    status                      TEXT NOT NULL DEFAULT 'unreviewed'
                                CHECK (status IN ('unreviewed', 'accepted', 'corrected', 'rejected')),
    note                        TEXT,
    method                      TEXT NOT NULL CHECK (method IN ('rules', 'llm', 'reference')),
    position                    INTEGER NOT NULL,  -- order in the chain; current location last
    holder_text                 TEXT NOT NULL,     -- verbatim: 'Cornelia Verdussen', 'The Metropolitan Museum of Art'
    collection_type_label       TEXT,              -- from Collection Type
    collection_place_label      TEXT,              -- verbatim place name
    collection_identifier       TEXT,              -- inventory number
    collection_entry_date       TEXT,              -- YYYY[-MM[-DD]]
    collection_entry_date_text  TEXT,              -- verbatim
    collection_entry_method     TEXT,              -- from Transfer method
    collection_entry_note       TEXT,
    collection_removal_date     TEXT,
    collection_removal_derived  INTEGER NOT NULL DEFAULT 0,  -- 1 = taken from the next stage
    collection_is_current       INTEGER NOT NULL,
    uncertain                   INTEGER NOT NULL DEFAULT 0   -- '?', 'possibly', 'probably'
);
CREATE INDEX ro_collection_stays_object ON ro_collection_stays(object_id);

-- Provenance: auctions, one row per object per sale.
CREATE TABLE ro_auctions (
    id                       INTEGER PRIMARY KEY,
    object_id                INTEGER NOT NULL REFERENCES ro_objects(id),
    segment_id               INTEGER NOT NULL REFERENCES segments(id),
    first_word_id            INTEGER NOT NULL REFERENCES words(id),
    last_word_id             INTEGER NOT NULL REFERENCES words(id),
    run_id                   INTEGER NOT NULL REFERENCES ro_runs(id),
    status                   TEXT NOT NULL DEFAULT 'unreviewed'
                             CHECK (status IN ('unreviewed', 'accepted', 'corrected', 'rejected')),
    note                     TEXT,
    method                   TEXT NOT NULL CHECK (method IN ('rules', 'llm', 'reference')),
    position                 INTEGER NOT NULL,  -- order in the chain, shared with ro_collection_stays
    auction_label            TEXT,              -- verbatim: 'his sale', 'sale'
    auction_organizer_label  TEXT,              -- verbatim: 'Christie’s'
    auction_place_label      TEXT,              -- verbatim: 'London'
    auction_date_start       TEXT,
    auction_date_end         TEXT,
    auction_date_text        TEXT,              -- verbatim: '20–21 July 2011'
    auction_lot_number       TEXT,
    auction_consignor        TEXT,              -- verbatim, or the previous holder for 'his sale'
    auction_consignor_derived INTEGER NOT NULL DEFAULT 0,  -- 1 = taken from the previous stage
    auction_buyer            TEXT,
    auction_price_amount     TEXT,              -- verbatim: '260'
    auction_price_currency   TEXT,              -- from Currencies
    auction_note             TEXT,              -- verbatim: '(Le Buste de Platon)'
    uncertain                INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX ro_auctions_object ON ro_auctions(object_id);

-- Exhibitions and literature in an entry (step 3 items of 'exhibited' and
-- 'literature'). Resolving the reference to the volume's lists is not done yet,
-- so exhibition_id and source_id are not there: the reference is verbatim.
CREATE TABLE ro_object_exhibitions (
    id                     INTEGER PRIMARY KEY,
    object_id              INTEGER NOT NULL REFERENCES ro_objects(id),
    segment_id             INTEGER NOT NULL REFERENCES segments(id),
    first_word_id          INTEGER NOT NULL REFERENCES words(id),
    last_word_id           INTEGER NOT NULL REFERENCES words(id),
    run_id                 INTEGER NOT NULL REFERENCES ro_runs(id),
    status                 TEXT NOT NULL DEFAULT 'unreviewed'
                           CHECK (status IN ('unreviewed', 'accepted', 'corrected', 'rejected')),
    note                   TEXT,
    exhibition_reference   TEXT,             -- verbatim abbreviation: 'New York, 1934'
    exhibition_cat_number  TEXT,             -- '21'
    exhibition_note        TEXT,             -- verbatim: 'no cat.', 'repr.'
    reference_text         TEXT NOT NULL     -- verbatim item
);

CREATE TABLE ro_object_sources (
    id                     INTEGER PRIMARY KEY,
    object_id              INTEGER NOT NULL REFERENCES ro_objects(id),
    segment_id             INTEGER NOT NULL REFERENCES segments(id),
    first_word_id          INTEGER NOT NULL REFERENCES words(id),
    last_word_id           INTEGER NOT NULL REFERENCES words(id),
    run_id                 INTEGER NOT NULL REFERENCES ro_runs(id),
    status                 TEXT NOT NULL DEFAULT 'unreviewed'
                           CHECK (status IN ('unreviewed', 'accepted', 'corrected', 'rejected')),
    note                   TEXT,
    source_reference       TEXT,             -- verbatim abbreviation: 'Rooses, Oeuvre, 1886–92'
    source_page_reference  TEXT,             -- 'IV, pp. 120, 238–39, no. 1032'
    source_note            TEXT,             -- verbatim: 'as Rubens'
    reference_text         TEXT NOT NULL     -- verbatim item
);

-- Artistic relations: a copy after the entry, the entry copied in print.
CREATE TABLE ro_related_objects (
    id                                     INTEGER PRIMARY KEY,
    object_id                              INTEGER NOT NULL REFERENCES ro_objects(id),
    segment_id                             INTEGER NOT NULL REFERENCES segments(id),
    first_word_id                          INTEGER NOT NULL REFERENCES words(id),
    last_word_id                           INTEGER NOT NULL REFERENCES words(id),
    run_id                                 INTEGER NOT NULL REFERENCES ro_runs(id),
    status                                 TEXT NOT NULL DEFAULT 'unreviewed'
                                           CHECK (status IN ('unreviewed', 'accepted', 'corrected', 'rejected')),
    note                                   TEXT,
    related_object_id                      INTEGER REFERENCES ro_objects(id),
    related_object_artistic_relation_type  TEXT NOT NULL,  -- from Artistic relation types
    relation_text                          TEXT            -- verbatim, e.g. 'See above, No. 1-5a.'
);
