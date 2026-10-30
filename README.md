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
3. **Segmentation.** Each volume is divided into sections, catalogue entries, copies, fields (provenance, exhibited, literature, …), list items, paragraphs and notes, using typography, the RKD links and per-volume rules, configured in one TOML file per volume. No language model is used for the structure.
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
- A proof of concept first runs every step on two catalogue entries, one born-digital (XIX (4) No. 4) and one OCR (II part 1, No. 12c), with the same code as the full corpus. The proof of concept makes no reference records yet. Step 4 is checked by comparing rules, local models and the PDF.
- CRLB content (PDFs, text, exports, reference records) stays in `data/`, outside git.

The code and documentation are published under the MIT licence; everything in the repository is in English.

## Database

`crlb build` writes two SQLite files to the output directory (`data/poc/` for the proof of concept). Both contain CRLB material and stay outside git.

- **`crlb.sqlite`** holds the text and all later layers. Its schema is in `src/crlb/schema/`, one numbered SQL file per step. Opening the database applies the files that are missing.
- **`pdfs.sqlite`** holds the PDF files themselves, in the standard [sqlar](https://sqlite.org/sqlar.html) format (`sqlite3 pdfs.sqlite -Atv` lists them). `crlb.sqlite` refers to each file by path and SHA-256, and the hash is checked whenever a PDF is opened from the archive.

The tables of `crlb.sqlite`:

| Table                   | Contains                                                                                                                                                                                                           | Used for                                                                                                          |
| :---------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :---------------------------------------------------------------------------------------------------------------- |
| `schema_version`        | the schema files applied, with their dates                                                                                                                                                                         | upgrading an existing database without rebuilding it                                                              |
| `build_runs`            | one row per build: time, git commit, PyMuPDF version and extraction options                                                                                                                                        | provenance: which code and settings produced the text                                                             |
| `parts`                 | one row per CRLB part (`XIX (4)`), with title, year and authors from `data_manifest/parts.csv`                                                                                                                     | citations and Rubens Online; the valid part names for `documents`                                                 |
| `documents`             | one row per PDF: path, hash, size, part, volume, section (main or index), text source (OCR or born-digital), PDF metadata, page count                                                                              | the unit of storage; selecting files by part or text source                                                       |
| `pages`                 | one row per page: index, page label, size, rotation and the raw page text                                                                                                                                          | reading and searching the text of a page                                                                          |
| `words`                 | one row per word: position in block, line and word, coordinates, text, and font, size and style flags (bold, italic, superscript)                                                                                  | the base of every later step; later layers refer to `words.id`, so every result traces back to a place in the PDF |
| `links`                 | link annotations: kind, URI or target page, and their box on the page                                                                                                                                              | RKDimages links, which mark catalogue entries and carry their RKD permalink; internal links                       |
| `toc`                   | the bookmarks (outline): level, title and target page                                                                                                                                                              | finding sections such as the catalogue and the index                                                              |
| `pages_fts`             | a full-text index (FTS5) on `pages.text`, insensitive to case and accents. The `pages_fts_*` tables are its internal storage                                                                                       | fast word, phrase and proximity searches across the corpus                                                        |
| `lexicon`               | step 2: word forms of the born-digital volumes (casefolded) with their counts, and their count in the OCR documents                                                                                                | deciding whether a joined OCR form ("M useum" → "Museum") is a real word                                          |
| `bigrams`               | step 2: counts of two consecutive born-digital words whose join is also a form ("a part" / "apart")                                                                                                                | not joining two real words unless the joined form is far more frequent                                            |
| `lexicon_sources`       | step 2: the born-digital PDFs the lexicon was read from, with SHA-256 and counts                                                                                                                                   | provenance of the lexicon                                                                                         |
| `correction_runs`       | step 2: one row per correction run: step (2a), git commit, thresholds, sample and lexicon summary                                                                                                                  | provenance; comparing runs                                                                                        |
| `corrected_words`       | step 2: the corrected text as tokens, each covering a range of raw words (one or more), with its box, the rule (R1–R3, or none if unchanged) and the reason                                                        | the corrected text that later steps read (via `crlb.text`), traceable to the raw words                            |
| `correction_flags`      | step 2: joins a rule considered but did not apply, with the candidate and the reason                                                                                                                               | review of doubtful cases                                                                                          |
| `segmentation_runs`     | step 3: one row per segmentation run: the correction run whose text was matched, git commit, the per-volume configurations used                                                                                    | provenance; comparing runs                                                                                        |
| `segments`              | step 3: the structure of a document as a tree of word ranges: furniture, sections, entries, fields, copies, items and notes, each with its label, rule, confidence, reason and RKD link                            | the units that step 4 extracts from; review                                                                       |
| `printed_pages`         | step 3: the printed page number of each PDF page, read from the page furniture or interpolated                                                                                                                     | citations and index references, which use printed page numbers                                                    |
| `note_refs`             | step 3: note markers in the text, linked to their note (not filled in the POC)                                                                                                                                     | linking a note to the place it comments on                                                                        |
| `ro_runs`               | step 4: one row per extraction run and field (objects, references, provenance): method (rules, LLM or reference), model and runtime, the segmentation and correction runs used, git commit and options             | provenance; comparing runs and models; `crlb set-active <db> 4:<field>`                                           |
| `ro_objects`            | step 4: one Rubens Online object per entry and copy: CRLB number, title, object name, production date, material note and support, lost or destroyed                                                                | the core record that the other step 4 tables refer to                                                             |
| `ro_object_identifiers` | step 4: the CRLB number and the RKD id of each object, with the RKD link                                                                                                                                           | linking to RKDimages and citing the CRLB                                                                          |
| `ro_attributions`       | step 4: attributions stated in the text (`possibly by Anthony van Dyck`): status and actor                                                                                                                         | attribution in Rubens Online                                                                                      |
| `ro_dimensions`         | step 4: height and width with unit and note (`c.`), and the dimensions as written                                                                                                                                  | dimensions in Rubens Online                                                                                       |
| `ro_collection_stays`   | step 4: provenance stays and the current location, in chain order: holder, place, type, inventory number, entry date and method, removal date (derived from the next stage where the text gives none), uncertainty | provenance in Rubens Online                                                                                       |
| `ro_auctions`           | step 4: sales in the provenance chain: house, place, date, lot, consignor (taken from the previous stage for `his sale`), buyer, price and currency                                                                | provenance in Rubens Online                                                                                       |
| `ro_object_exhibitions` | step 4: the exhibition items of an object: reference as written, catalogue number and note                                                                                                                         | exhibition history in Rubens Online                                                                               |
| `ro_object_sources`     | step 4: the literature items of an object: reference as written, page reference and note                                                                                                                           | literature in Rubens Online                                                                                       |
| `ro_related_objects`    | step 4: relations between objects: a copy after the entry, an entry copied in print, cross-references                                                                                                              | copies and prints in Rubens Online                                                                                |
| `active_runs`           | per step, the run that later steps and exports use (empty until step 2)                                                                                                                                            | choosing between several runs of a step after measuring them                                                      |
| `llm_calls`             | every language-model call: task, input range, input, output, validity, duration and tokens (empty until a step uses a model)                                                                                       | auditing and comparing models without calling them again                                                          |

The step 1 tables are never changed after the build. Later steps add their own tables, which refer to `words`, `pages` and `documents`.

## Local models

Step 4 uses a local model through the llama.cpp server. The server, the model files and the prompt examples are kept in `data/`, outside git. The models are pinned by repository, commit and SHA-256 in `data_manifest/models.csv`.

1. Start a server in a separate terminal: `make serve_qwen` or `make serve_ministral`.
2. Run the provenance with that model, compared with the rules: `make extract_llm_poc`.
3. After a run with each model, compare the two runs: `uv run --locked crlb extract compare data/poc/crlb.sqlite <run a> <run b>`.

Every call is stored in `llm_calls`. The differences, which contain CRLB text, are written to `data/poc/review/`.

## AI usage

- In development:
    - Claude Code Opus 5.5
    - Gemini 3.6 Flash
- In data processing (step 4, proof of concept), run locally with llama.cpp `llama-server` build b11606 (CPU):
    - Qwen3.5 4B, Q4_K_M (`unsloth/Qwen3.5-4B-GGUF`)
    - Ministral 3 8B Instruct 2512, Q4_K_M (`mistralai/Ministral-3-8B-Instruct-2512-GGUF`)
