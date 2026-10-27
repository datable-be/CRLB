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
- CRLB content (PDFs, text, exports, reference records) stays in `data/`, outside git.

The code and documentation are published under the MIT licence; everything in the repository is in English.

## AI usage

- In development:
    - Claude Code Opus 5.5
    - Gemini 3.6 Flash
