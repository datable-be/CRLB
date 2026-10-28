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

# All POC steps so far; making a run active stays a manual step after measuring and checking
poc: build_poc lexicon_poc correct_poc measure_poc show_poc

help:
	@echo "sample_specimens, analyse_specimens, build_poc, lexicon_poc, correct_poc, measure_poc, show_poc, poc"
