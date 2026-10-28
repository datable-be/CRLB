sample_specimens:
	uv run --locked crlb ocr sample doc/CRLB_pdfs doc/CRLB_pdfs/specimens

analyse_specimens:
	uv run --locked crlb ocr analyse doc/CRLB_pdfs/specimens

# Rebuilds from scratch: the command itself never overwrites an existing database
build_poc:
	rm -f data/poc/crlb.sqlite data/poc/pdfs.sqlite
	uv run --locked crlb build data_manifest/documents.csv data/poc

help:
	@echo "sample_specimens, analyse_specimens, build_poc"
