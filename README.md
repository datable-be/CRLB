# CRLB

## Project summary

This project turns the volumes of the **Corpus Rubenianum Ludwig Burchard** (CRLB), the catalogue raisonné of Rubens's work, into structured data for **Rubens Online** (Rubenshuis, Antwerp): provenance, exhibition history, literature and the descriptive texts of every catalogue entry, linked to authorities. The end result is data; the software produces it reproducibly and documents how. The full plan is in [doc/plan.md](doc/plan.md).

### Principles

- **Rules first, AI where rules fall short.** Every step is deterministic where possible. Language models are only used on short, pre-cut pieces of text, may only return text that literally occurs in the source or a choice from a closed list, and every answer is checked and stored.
- **Local first.** Local open models first, then EU infrastructure, a frontier model only if measurements show it is needed.
- **Nothing is overwritten.** Every step writes a new layer that refers to the words of the PDF (and so to their coordinates). Every run records its code version, options and models; reviews by people are stored as separate decisions.
- **Measured against a threshold.** Each step is tested on hand-checked material, with a development and a test set, against a threshold agreed beforehand.

### Steps

1. **Text database.** About 65 PDFs (born-digital and scanned with ABBYY OCR) go into SQLite: per page and per word, with coordinates, typography, links to RKDimages and bookmarks. The PDFs themselves are kept in a separate SQLite archive, checked by hash.
2. **OCR correction.** The main OCR error is superfluous spaces (`M useum`). A deterministic repair only removes spaces and soft hyphens, using a lexicon built from the born-digital volumes. Character substitutions and LLM help follow only if the measured quality is insufficient.
3. **Segmentation.** Each volume is divided into sections, catalogue entries, copies, fields (provenance, exhibited, literature, …), list items, paragraphs and notes, using typography, the RKD links and per-volume rules.
4. **Extraction.** The segments become records in the Rubens Online data model (objects, provenance as collection stays and auctions, exhibitions, literature, texts), verbatim and parsed. Hand-made **reference records** are the ground truth. Each entry is also exported as Markdown.
5. **Normalisation, enrichment and comparison.**
    - Control lists from RKD/Axiell and the corpus indexes.
    - Normalisation to the RKD lists and entry instructions.
    - LOD URIs (RKD, Getty AAT/TGN, Iconclass, Wikidata).
    - Named entities in the descriptive texts.
    - Comparison with the existing RKD records, to add only what is missing.
    - A CRLB reference per RKD record, and RKD links added to PDFs that lack them.

### Implementation

- One Python package (`src/crlb/`) with a single command, `crlb`, called from the Makefile.
- uv for the environment and its lock file. No container: model runtimes, models and external tools are pinned and recorded separately.
- One SQLite database, growing step by step through numbered schema files.
- A proof of concept first runs every step on two catalogue entries, one born-digital (XIX (4)) and one OCR (II part 1), with the same code as the full corpus.
- CRLB content (PDFs, text, exports, reference records) stays in `data/`, outside git.

The code and documentation are published under the MIT licence; everything in the repository is in English.

## Database

`crlb build` writes two SQLite files to the output directory (`data/poc/` for the proof of concept). Both contain CRLB material and stay outside git.

- **`crlb.sqlite`** holds the text and all later layers. Its schema is in `src/crlb/schema/`, one numbered SQL file per step. Opening the database applies the files that are missing.
- **`pdfs.sqlite`** holds the PDF files themselves, in the standard [sqlar](https://sqlite.org/sqlar.html) format (`sqlite3 pdfs.sqlite -Atv` lists them). `crlb.sqlite` refers to each file by path and SHA-256, and the hash is checked whenever a PDF is opened from the archive.

The tables of `crlb.sqlite`:

| Table              | Contains                                                                                                                                                    | Used for                                                                                                          |
| :----------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------- | :---------------------------------------------------------------------------------------------------------------- |
| `schema_version`   | the schema files applied, with their dates                                                                                                                  | upgrading an existing database without rebuilding it                                                              |
| `build_runs`       | one row per build: time, git commit, PyMuPDF version and extraction options                                                                                 | provenance: which code and settings produced the text                                                             |
| `parts`            | one row per CRLB part (`XIX (4)`), with title, year and authors from `data_manifest/parts.csv`                                                              | citations and Rubens Online; the valid part names for `documents`                                                 |
| `documents`        | one row per PDF: path, hash, size, part, volume, section (main or index), text source (OCR or born-digital), PDF metadata, page count                       | the unit of storage; selecting files by part or text source                                                       |
| `pages`            | one row per page: index, page label, size, rotation and the raw page text                                                                                   | reading and searching the text of a page                                                                          |
| `words`            | one row per word: position in block, line and word, coordinates, text, and font, size and style flags (bold, italic, superscript)                           | the base of every later step; later layers refer to `words.id`, so every result traces back to a place in the PDF |
| `links`            | link annotations: kind, URI or target page, and their box on the page                                                                                       | RKDimages links, which mark catalogue entries and carry their RKD permalink; internal links                       |
| `toc`              | the bookmarks (outline): level, title and target page                                                                                                       | finding sections such as the catalogue and the index                                                              |
| `pages_fts`        | a full-text index (FTS5) on `pages.text`, insensitive to case and accents. The `pages_fts_*` tables are its internal storage                                | fast word, phrase and proximity searches across the corpus                                                        |
| `lexicon`          | step 2: word forms of the born-digital volumes (casefolded) with their counts, and their count in the OCR documents                                         | deciding whether a joined OCR form ("M useum" → "Museum") is a real word                                          |
| `bigrams`          | step 2: counts of two consecutive born-digital words whose join is also a form ("a part" / "apart")                                                         | not joining two real words unless the joined form is far more frequent                                            |
| `lexicon_sources`  | step 2: the born-digital PDFs the lexicon was read from, with SHA-256 and counts                                                                            | provenance of the lexicon                                                                                         |
| `correction_runs`  | step 2: one row per correction run: step (2a), git commit, thresholds, sample and lexicon summary                                                           | provenance; comparing runs                                                                                        |
| `corrected_words`  | step 2: the corrected text as tokens, each covering a range of raw words (one or more), with its box, the rule (R1–R3, or none if unchanged) and the reason | the corrected text that later steps read (via `crlb.text`), traceable to the raw words                            |
| `correction_flags` | step 2: joins a rule considered but did not apply, with the candidate and the reason                                                                        | review of doubtful cases                                                                                          |
| `active_runs`      | per step, the run that later steps and exports use (empty until step 2)                                                                                     | choosing between several runs of a step after measuring them                                                      |
| `llm_calls`        | every language-model call: task, input range, input, output, validity, duration and tokens (empty until a step uses a model)                                | auditing and comparing models without calling them again                                                          |

The step 1 tables are never changed after the build. Later steps add their own tables, which refer to `words`, `pages` and `documents`.

## AI usage

- In development:
    - Claude Code Opus 5.5
    - Gemini 3.6 Flash
