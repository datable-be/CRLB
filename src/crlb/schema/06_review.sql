-- Reviews: the decisions of reviewers on the results of any step, as events.
-- The rows of a run are never changed, except their status, which follows
-- the latest decision; a corrected value lives only here.

-- One row per review decision, for any table with a status column.
CREATE TABLE reviews (
    id             INTEGER PRIMARY KEY,
    table_name     TEXT NOT NULL,      -- 'ro_collection_stays', 'normalised_values', ...
    row_id         INTEGER NOT NULL,
    column_name    TEXT,               -- NULL = the row as a whole
    action         TEXT NOT NULL CHECK (action IN ('accept', 'correct', 'reject', 'comment')),
    old_value      TEXT,               -- the effective value at the time of review
    new_value      TEXT,               -- for 'correct'
    reviewer       TEXT NOT NULL,      -- user name in the validation interface
    reviewed_at    TEXT NOT NULL,      -- ISO 8601, UTC
    comment        TEXT,
    first_word_id  INTEGER REFERENCES words(id),  -- the source of the row, stable across runs:
    last_word_id   INTEGER REFERENCES words(id)   -- for carrying reviews over to a rerun
);
CREATE INDEX reviews_row ON reviews(table_name, row_id);
