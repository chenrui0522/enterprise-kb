import io
from pathlib import Path

from PIL import Image

from app.api.routers.documents import _ensure_thumbnail, _thumbnail_path, _thumbnail_width


def test_thumbnail_width_normalizes_to_allowed_steps() -> None:
    assert _thumbnail_width(None) is None
    assert _thumbnail_width(0) is None
    assert _thumbnail_width(50) == 64
    assert _thumbnail_width(200) == 200
    assert _thumbnail_width(500) == 400
    assert _thumbnail_width(2000) == 800


def test_ensure_thumbnail_creates_smaller_jpeg(tmp_path) -> None:
    source = tmp_path / "big.png"
    buffer = io.BytesIO()
    Image.frombytes("RGB", (1600, 900), __import__("os").urandom(1600 * 900 * 3)).save(buffer, format="PNG")
    source.write_bytes(buffer.getvalue())
    target = _thumbnail_path(tmp_path, "a" * 64, 200)

    assert _ensure_thumbnail(source, Path(target), 200) is True
    assert target.exists()
    with Image.open(target) as thumb:
        assert thumb.width == 200
        assert thumb.format == "JPEG"
    assert target.stat().st_size < source.stat().st_size