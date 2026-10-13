sample_specimens:
	uv run scripts/sample_specimens.py doc/CRLB_pdfs doc/CRLB_pdfs/specimens

analyse_specimens:
	uv run scripts/analyse_specimens.py doc/CRLB_pdfs/specimens

help:
	@echo "sample_specimens, analyse_specimens"
