"""Defensive wrapper around file converters.

Guarantees that a conversion either returns usable content or raises an
``AppError`` with the converter name and underlying cause attached, so the API
never surfaces a raw traceback for a bad document.
"""

from __future__ import annotations

from app.core.errors import AppError
from app.core.logging import get_logger
from app.ingestion.converters import ConversionResult, FileConverter

logger = get_logger("ingestion.conversion")


async def convert_safely(
    converter: FileConverter, file_path: str, *, label: str = ""
) -> ConversionResult:
    name = type(converter).__name__
    try:
        result = await converter.convert_async(file_path)
    except AppError:
        raise
    except Exception as exc:
        logger.warning("Converter %s failed on %s", name, file_path, exc_info=True)
        raise AppError(f"文档解析失败（{name}{'/' + label if label else ''}）：{exc}") from exc

    if result is None:
        raise AppError(f"文档解析未返回结果（{name}）")
    blocks = getattr(result.structure, "blocks", None) if result.structure else None
    if not (result.markdown or "").strip() and not blocks:
        raise AppError(f"文档解析后没有可用内容（{name}）")
    return result