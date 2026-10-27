sample_specimens:
	uv run --locked crlb ocr sample doc/CRLB_pdfs doc/CRLB_pdfs/specimens

analyse_specimens:
	uv run --locked crlb ocr analyse doc/CRLB_pdfs/specimens

help:
	@echo "sample_specimens, analyse_specimens"
