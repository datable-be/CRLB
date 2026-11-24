# CRLB proof of concept: demo agenda (2026-10-30)

Status of the proof of concept (POC) for WP 5.2, "Extraction Corpus Rubenianum": structured data taken from the CRLB PDFs, in the Rubens Online (RO) data model. Details are in [plan.md](../plan.md).

## 1. Goal and scope of the POC

- Run every step of the pipeline on **two catalogue entries**, with the same code that will later process the whole corpus:
    - **XIX (4) No. 4**, _Study of two Heads (Plato?)_, New York. Born-digital PDF, with RKD links.
    - **II (1) No. 12c**, _The Triumph of Faith_ (modello), Brussels. Scanned PDF with ABBYY OCR, with RKD links.
- Together the two entries have 21 objects (2 entries and 19 copies), 37 main provenance stages (58 including those of the copies), 16 exhibitions and 55 main literature references.
- Steps 1–3 run on the **two volumes in full**: 2 PDFs, 756 pages, 164 entries.
- Steps 1–4 are done. **Step 5** (normalisation, enrichment, the comparison with RKD) is **not started**.

## 2. Approach (principles)

- **Verbatim first.** Every extracted value is stored exactly as written in the PDF and traceable to its words on the page. Parsed and mapped values, such as dates or RO list labels, are stored next to it.
- **Rules where the text is regular, a language model only where it isn't.** The model never invents text: each piece of text in its answer must occur in the source, and each choice must come from the RO value lists. Answers that fail are rejected and logged.
- **Every run is recorded:** the code version, options, model and the full prompt and answer of every model call. Results can be audited and compared without calling a model again.
- **Runs are accepted explicitly.** Each step writes a new run, which a person makes "active" after checking it. Later steps build only on accepted runs.
- **CRLB content stays local.** The text, exports and review pages are kept outside git, and the commands print only counts.
- **Local models first.** They run on the laptop, with no data leaving the machine. The escalation path, used only if the measurements require it: an open model on EU infrastructure, then a frontier model.

## 3. Results per step

### Step 1: text database

- Every page and word goes into SQLite with its coordinates, font, size and style (italic, small caps), plus the RKD links and bookmarks. The PDFs themselves are kept in a separate archive, checked by hash.
- The build takes about 50 s.

### Step 2: OCR correction

- An earlier OCR quality test on 12 hand-corrected specimen pages found that **59% of all OCR errors are superfluous spaces** (`M useum`, `p r o v e n a n c e`).
- **Approach:** deterministic rules that only remove spaces, never change letters, and never touch numbers. A lexicon built from the 31 born-digital volumes decides what counts as a word.
- **Results on the 6 test pages** (not used for tuning):

|                             |   Before |             After |
| :-------------------------- | -------: | ----------------: |
| CER per page                | 1.4–9.9% |          1.4–3.7% |
| superfluous spaces          |      644 | 137 (79% removed) |
| real spaces wrongly removed |        – |                18 |

- **Decision:** step 2a (spaces only) suffices for now. Character corrections (2b) and model-assisted correction (2c) wait until a later step shows they are needed.

### Step 3: segmentation (structure)

- Typography, RKD links and per-volume rules divide each volume into sections, entries, fields (provenance, exhibited, literature, copies, …), copies, list items and notes. No language model is involved.
- **Result** on the two volumes, in about 10 s:
    - **164 entries**: 80 in XIX (4) and 84 in II (1);
    - 414 copies, 2,161 fields, 2,835 list items and 553 notes.
- **Confidence:** in the born-digital volume, 79 of 80 entries are certain. In the OCR volume, 64 of 84 are certain and 20 probable or uncertain, mostly because the OCR damaged the entry numbers.
- **Known gaps:**
    - one entry in II (1) is not found;
    - many note numbers in II (1) are damaged by the OCR;
    - paragraphs, note markers and the index sections are not done in the POC.

### Step 4: extraction into the RO model

**Part 1, rules.** For the two entries:

- **Objects:** 21 objects (2 entries and 19 copies), all with an RKD ID. Each has its title, object name, material and support, dimensions, date, attributions, lost or destroyed status, and the "copy after" relation.
- **References:** 17 exhibitions and 92 literature references (copies included), each split into the reference, page or catalogue number, and note.
- **Provenance:** 58 stages. The rules handle 40 (collection stays and auctions in their fixed forms, plus the current location) and leave 18 for the model. They also derive data across stages: the consignor of "his sale" is taken from the previous stage, and a removal date from the next.
- **Checks:** every verbatim value occurs in its source.
- **Speed:** on all 164 entries the rules take about 20 s and handle 642 of 990 provenance stages, two thirds.

**Part 2, provenance with a local model,** for the stages the rules leave:

|                                               | Qwen3.5 4B | Ministral 3 8B (Mistral, EU) |
| :-------------------------------------------- | ---------: | ---------------------------: |
| time per stage                                |       24 s |                         40 s |
| answers rejected by the checks                |    4 of 57 |                      8 of 57 |
| rows added (of the 18 stages the rules leave) |         13 |                           13 |

- **The checks work.** For example, Ministral "corrected" OCR errors and borrowed data from the previous stage, and those answers were rejected.
- **The rules beat both models on the regular forms.** On the irregular stages the model rows are mostly right, but there are real errors, such as a room taken as a holder or a dealer read as an auction.
- **The two models agree** on 89–100% of the parts.
- **Recommendation:** Qwen3.5 4B for local runs.
- **Speed is the limit.** On the laptop (no GPU), the 348 leftover stages of these two volumes alone take about 2.3 hours. The whole corpus needs a GPU server in the EU or an API.

**Part 3, review page:** one HTML page per entry, shown in the live demo below.

## 4. Live demo

Open `data/poc/review/extract_XIX_4_No4.html` and `extract_II_1_No12c.html`. To rebuild them: `make review_extract_poc`.

1. **Left:** the PDF pages. The provenance stages are coloured: blue by rules, orange by the model, red where no row was made.
2. **Right:** one card per object (the entry and its copies), with the RO values. Green arrows show what a value was mapped to, for example "Oil on panel" → "paneel (hout)".
3. **Point at a row:** its source words light up in the PDF. Click it and the PDF scrolls there.
4. **Examples to show:**
    - No. 4: the provenance chain, with "his sale" and the consignor taken from the previous stage;
    - No. 4: the last stage, which stays red because no row was made;
    - No. 12c, Copy 1: the same holder appears twice, once from the model and once as the current location from the rules;
    - the rejected model answers, with the reason for each;
    - an RKD ID that links straight to RKDimages.

## 5. Decisions taken

- **POC entries:** XIX (4) No. 4 and II (1) No. 12c, one born-digital and one OCR.
- **OCR:** step 2a (spaces only) is enough for now.
- **Structure:** found by rules only, with no model.
- **Entry attribution:** an entry gets no attribution row, since its attribution to Rubens goes without saying. Only attributions stated in the text, such as those of copies, are recorded.
- **Model runtime:** llama.cpp, a pinned build, running locally. Each model is pinned by file hash.
- **Local model:** Qwen3.5 4B; Ministral 3 8B serves as the EU comparison.
- **No reference records in the POC.** Quality is measured without ground truth: rejected answers, agreement between rules and model, agreement between the two models, and the review pages.
- **Deferred until after the POC:** the Markdown export per entry, the reference records, and step 5.

## 6. Questions for the meeting

1. **Quality check:** who can review the extracted records, and what counts as "good enough"? Reference records (about 25 hand-made entries per volume) would give real precision figures. They need someone's time.
2. **Infrastructure for the full run:** the local model is too slow for the corpus. Is an open model on an EU GPU server, or the Mistral API (EU), acceptable? Is a frontier model acceptable for the fields where these fall short?
3. **Data from the Rubenshuis and RKD:**
    - the registration lists per volume, which would check step 3's completeness;
    - an export of the RKD/Axiell records, needed for step 5's comparison and to pre-fill the reference records.
4. **Re-scans:** the OCR quality of some volumes, such as the older scans, needs a decision on whether the originals are rescanned.
5. **Priorities after the POC:** the Markdown export, the full volumes, step 5 (normalisation, LOD links, named entities in the descriptive texts), or the review interface.

## 7. Next steps (proposal)

1. Act on the demo feedback, and fix the known rules errors: those carried over from step 3, and the order of place and holder in locations.
2. The Markdown export per entry (faithful version).
3. Reference records for a sample of entries, so the quality can be measured.
4. Step 5 on the POC volumes: control lists from the indexes, normalisation to the RKD lists, LOD links.
5. Scale up to the other volumes, one configuration at a time, with the model running on EU infrastructure.
