-- pdfs.sqlite: the PDF files as raw bytes, in the standard sqlar format,
-- so the archive can be inspected and unpacked with `sqlite3 -A`.
-- PDFs barely compress, so they are stored uncompressed (length(data) = sz).
CREATE TABLE IF NOT EXISTS sqlar (
    name  TEXT PRIMARY KEY,  -- path, as in the manifest
    mode  INT,               -- file mode
    mtime INT,               -- file modification time, Unix seconds
    sz    INT,               -- original size in bytes
    data  BLOB               -- the file
);
