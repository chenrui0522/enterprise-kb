import pytest

from app.core.errors import AppError
from app.ingestion.conversion import convert_safely
from app.ingestion.converters import ConversionResult, NoExtractableContentError


class _OkConverter:
    async def convert_async(self, file_path: str) -> ConversionResult:  # noqa: ARG002
        return ConversionResult(markdown="# 标题\n\n正文")


class _BoomConverter:
    async def convert_async(self, file_path: str) -> ConversionResult:  # noqa: ARG002
        raise RuntimeError("boom")


class _EmptyConverter:
    async def convert_async(self, file_path: str) -> ConversionResult:  # noqa: ARG002
        return ConversionResult(markdown="   ")


class _NoContentConverter:
    async def convert_async(self, file_path: str) -> ConversionResult:  # noqa: ARG002
        raise NoExtractableContentError("扫描件没有文字层")


@pytest.mark.asyncio
async def test_convert_safely_passes_through_success() -> None:
    result = await convert_safely(_OkConverter(), "a.pdf")
    assert "标题" in result.markdown


@pytest.mark.asyncio
async def test_convert_safely_wraps_unexpected_errors() -> None:
    with pytest.raises(AppError) as excinfo:
        await convert_safely(_BoomConverter(), "a.pdf", label="text")
    assert "boom" in str(excinfo.value)


@pytest.mark.asyncio
async def test_convert_safely_rejects_empty_output() -> None:
    with pytest.raises(AppError):
        await convert_safely(_EmptyConverter(), "a.pdf")


@pytest.mark.asyncio
async def test_convert_safely_keeps_no_content_error_for_fallback() -> None:
    with pytest.raises(NoExtractableContentError):
        await convert_safely(_NoContentConverter(), "a.pdf")


def test_corrupt_pdf_reports_clear_error(tmp_path) -> None:
    from app.ingestion.converters import PDFMarkdownConverter

    target = tmp_path / "broken.pdf"
    target.write_bytes(b"not a real pdf")
    with pytest.raises(AppError):
        PDFMarkdownConverter().convert(str(target))