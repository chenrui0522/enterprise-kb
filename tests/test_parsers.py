import fitz
import pytest

from app.core.errors import AppError
from app.ingestion.parsers import TextPdfParser


def _write_pdf(path, text: str) -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text, fontsize=12)
    document.save(path)
    document.close()


def test_text_pdf_parser_extracts_content(tmp_path) -> None:
    target = tmp_path / "sample.pdf"
    _write_pdf(str(target), "Model ZB-100 manual page one content")
    pages = TextPdfParser(extract_tables=False).parse(str(target))
    assert pages
    assert "ZB-100" in pages[0].text
    assert pages[0].page_number == 1


def test_parser_rejects_corrupt_pdf(tmp_path) -> None:
    target = tmp_path / "broken.pdf"
    target.write_bytes(b"not a pdf at all")
    with pytest.raises(AppError):
        TextPdfParser().parse(str(target))
