sample_specimens:
	uv run scripts/OCR/sample_specimens.py doc/CRLB_pdfs doc/CRLB_pdfs/specimens

analyse_specimens:
	uv run scripts/OCR/analyse_specimens.py doc/CRLB_pdfs/specimens

help:
	@echo "sample_specimens, analyse_specimens"
