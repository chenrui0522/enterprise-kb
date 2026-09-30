"""Load leave-ledger rule configuration (HQ keywords, holidays)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from app.core.config import Settings, get_settings


def hq_address_keywords(settings: Settings | None = None) -> list[str]:
    s = settings or get_settings()
    return [p.strip() for p in s.leave_ledger_hq_address_keywords.split(",") if p.strip()]


def load_holidays(settings: Settings | None = None) -> set[date] | None:
    """Return holiday set, or None if calendar file missing (caller must warn)."""
    s = settings or get_settings()
    path = Path(s.leave_ledger_holidays_path)
    if not path.is_file():
        return None
    out: set[date] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        text = text.replace("-", "/")
        parts = text.split("/")
        if len(parts) != 3:
            continue
        y, m, d = (int(parts[0]), int(parts[1]), int(parts[2]))
        out.add(date(y, m, d))
    return out


def is_hq_address(address: str, keywords: list[str] | None = None) -> bool:
    if not address:
        return False
    keys = keywords if keywords is not None else hq_address_keywords()
    return any(k in address for k in keys)
