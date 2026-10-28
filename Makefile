# The two POC entries, one born-digital and one OCR (chosen from make entries_poc);
# steps 4 and 5 run on them with --sample
POC_SAMPLE = XIX (4)/4;II (1)/12c

# Print a bold step header, and echo each command in colour before running it,
# so commands stand out from their output
header = @printf '\n\033[1m== %s ==\033[0m\n' '$(1)'
run = @printf '\033[36m$$ %s\033[0m\n' '$(1)' && $(1)

sample_specimens:
	$(call run,uv run --locked crlb ocr sample doc/CRLB_pdfs doc/CRLB_pdfs/specimens)

analyse_specimens:
	$(call run,uv run --locked crlb ocr analyse doc/CRLB_pdfs/specimens)

# Rebuilds from scratch: the command itself never overwrites an existing database
build_poc:
	$(call header,Step 1: text database)
	$(call run,rm -f data/poc/crlb.sqlite data/poc/pdfs.sqlite)
	$(call run,uv run --locked crlb build data_manifest/documents.csv data/poc)

lexicon_poc:
	$(call header,Step 2: lexicon from the born-digital volumes)
	$(call run,uv run --locked crlb lexicon data/poc/crlb.sqlite data_manifest/lexicon_sources.csv)

correct_poc:
	$(call header,Step 2a: OCR space repair (R1–R3))
	$(call run,uv run --locked crlb correct run data/poc/crlb.sqlite)

measure_poc:
	$(call header,Step 2: measurement against the specimen pages)
	$(call run,uv run --locked crlb correct measure data/poc/crlb.sqlite doc/CRLB_pdfs/specimens data_manifest/specimen_split.csv)

# Side-by-side HTML of raw and corrected text for a XXVI (2.1) specimen page, in data/poc/review/
show_poc:
	$(call header,Step 2: raw and corrected pages side by side)
	$(call run,uv run --locked crlb correct show data/poc/crlb.sqlite 26_2_I_1 393)

# All POC steps up to the acceptance of the correction run, which is a separate decision
poc: build_poc lexicon_poc correct_poc measure_poc show_poc

# The explicit decision after measuring and checking: later steps read the text of this run
accept_poc:
	$(call header,Step 2: accept the correction run)
	$(call run,uv run --locked crlb set-active data/poc/crlb.sqlite 2 latest --note "accepted after measurement and review (POC)")

segment_poc:
	$(call header,Step 3: segmentation)
	$(call run,uv run --locked crlb segment run data/poc/crlb.sqlite)

# The entries of both POC documents with their fields and item counts (no text)
entries_poc:
	$(call header,Step 3: the catalogue entries)
	$(call run,uv run --locked crlb segment entries data/poc/crlb.sqlite 19_4_links)
	$(call run,uv run --locked crlb segment entries data/poc/crlb.sqlite 02_1_links)

# HTML view of the segmentation of the two POC entries, in data/poc/review/
show_segment_poc:
	$(call header,Step 3: segmentation of the POC entries on the page)
	$(call run,uv run --locked crlb segment show data/poc/crlb.sqlite 19_4_links 4)
	$(call run,uv run --locked crlb segment show data/poc/crlb.sqlite 02_1_links 12c)

# The explicit decision after checking: step 4 reads the entries and fields of this run
accept_segment_poc:
	$(call header,Step 3: accept the segmentation run)
	$(call run,uv run --locked crlb set-active data/poc/crlb.sqlite 3 latest --note "accepted after checking (POC)")

# Objects, exhibitions and literature, and provenance by rules, for the two POC entries
extract_poc:
	$(call header,Step 4: extraction by rules)
	$(call run,uv run --locked crlb extract run data/poc/crlb.sqlite --sample "$(POC_SAMPLE)")

# The explicit decision after checking: exports read the runs of these fields
accept_extract_poc:
	$(call header,Step 4: accept the extraction runs)
	$(call run,uv run --locked crlb set-active data/poc/crlb.sqlite 4:objects latest --note "accepted after checking (POC)")
	$(call run,uv run --locked crlb set-active data/poc/crlb.sqlite 4:references latest --note "accepted after checking (POC)")
	$(call run,uv run --locked crlb set-active data/poc/crlb.sqlite 4:provenance latest --note "accepted after checking (POC)")

help:
	@echo "sample_specimens, analyse_specimens, build_poc, lexicon_poc, correct_poc, measure_poc, show_poc, poc, accept_poc, segment_poc, entries_poc, show_segment_poc, accept_segment_poc, extract_poc, accept_extract_poc"
