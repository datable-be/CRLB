# Named Entity Recognition for the Corpus Rubenianum Ludwig Burchard

This document outlines the state of the art (as of mid-2026) for named entity recognition (NER) in art-historical catalogues such as the CRLB, and how it fits with the planned OCR text database and validation tool.

**Summary:** the strongest results for this kind of source come from a **hybrid approach**: exploit the catalogue's structure first, then extract entities with an LLM, then link them to authority files. Classic off-the-shelf NER alone performs poorly here.

## Why standard NER falls short

General-purpose models (spaCy, standard BERT NER) are trained on news text with labels like PERSON, ORG and LOC. A Rubens catalogue needs different entity types:

- **Artists and workshop roles**: "Rubens and workshop", "after Rubens", "J. van der Biest after P. Candido"
- **Works**: titles, often in variant forms ("Susanna and the Elders")
- **Collections and owners over time**: provenance chains, auctions with dates and lot numbers
- **Places**: museums, churches, cities
- **Dates**: often approximate ("c. 1615–16")
- **Literature references**: abbreviations such as "Rooses, _Œuvre_, II, no. 123", resolved through the Abbreviations list
- **Iconographic subjects**

On top of that, the text mixes English with Dutch, Latin, French, Italian and Spanish quotations, and contains OCR noise from ABBYY FineReader.

## Current approaches

### 1. LLM extraction (best quality today)

Large models given a schema and few-shot examples, returning structured output, handle unfamiliar entity types, multilingual quotations and OCR errors far better than trained NER models. They also capture **relations** (who owned what, and when), which matter more for provenance than the entities alone.

- **Drawbacks:** cost over ~5,000 pages, and the risk of invented values.
- **Mitigation:** have the model return the **literal text span**, then verify in code that the span actually occurs in the OCR text. A span that can be found also yields its word boxes, so every entity can be highlighted on the page in the validation tool.

### 2. GLiNER and similar compact models

Small encoder models that do zero-shot NER with arbitrary labels ("artist", "collection", "auction"). They run locally, are cheap and fast, and return spans by design. Weaker than an LLM on complex cases and relations, but a good option for bulk extraction, and they can be fine-tuned on a small gold set.

### 3. Fine-tuned BERT-type models (XLM-R, historical BERTs)

The classic approach when enough annotated data is available. The CLEF **HIPE** shared tasks (2020 and 2022) on historical, OCR-noisy text showed it works, but it needs hundreds to thousands of annotated examples. Less attractive now that options 1 and 2 exist.

## Where the biggest gains are

- **Use the structure first.** Catalogue entries follow a fixed pattern: number, title, medium/dimensions, _Provenance_, _Copies_, _Exhibited_, _Literature_, then discussion. Splitting entries along those headings with rules makes every downstream step easier and more accurate. A name under _Provenance_ is almost certainly an owner.
- **Link entities to authority files.** Extracted strings only become useful once they point to an identifier: **RKDartists / RKDimages**, Wikidata, Getty ULAN and TGN, and **Iconclass** for subjects.
- **Gold data already exists.** The `*_links` PDFs contain hundreds of hand-made links from figures to RKDimages records. These can serve as anchors and as an evaluation set for linking works.
- **Build a small gold set** of a few dozen annotated catalogue entries. Without it there is no way to tell which approach really works best on this material.

## Fit with the OCR database and validation tool

The OCR text layer in the PDFs (ABBYY FineReader 11) already contains word-level coordinates, so no new OCR is needed. The planned SQLite database stores each word with its bounding box.

If NER results are stored as spans pointing to word IDs, the same web viewer that shows OCR text on the page can show each entity in place, so a person can accept or correct it. One tool then validates both the OCR and the NER.
