"""Test-suite guards.

Several tests build the ingestion pipeline without explicit settings, which
would otherwise read the developer's ``.env``. A configured ``KB_MINERU_URL``
or ``KB_DOCLING_URL`` there would make the suite call a live OCR/parsing
service, so the environment is pinned to "no external services" here. Tests
that need a service always pass explicit ``Settings(...)`` values or
monkeypatch the HTTP client, so they are unaffected.
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _no_live_parsing_services(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KB_MINERU_URL", "")
    monkeypatch.setenv("KB_DOCLING_URL", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()