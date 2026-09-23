from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings

_CONTEXT: ContextVar[dict[str, Any]] = ContextVar("kb_log_context", default={})

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

# Keys that must never appear in structured log output.
_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "cookie",
        "authorization",
        "api_key",
        "apikey",
        "session",
    }
)


def new_request_id() -> str:
    return uuid.uuid4().hex


def is_valid_request_id(value: str | None) -> bool:
    if not value:
        return False
    return bool(_REQUEST_ID_RE.match(value.strip()))


def get_log_context() -> dict[str, Any]:
    return dict(_CONTEXT.get())


def bind_context(**fields: Any) -> None:
    """Merge fields into the current logging context (same task/request)."""
    current = dict(_CONTEXT.get())
    for key, value in fields.items():
        if value is None:
            current.pop(key, None)
        else:
            current[key] = value
    _CONTEXT.set(current)


def clear_context() -> None:
    _CONTEXT.set({})


@contextmanager
def logging_context(**fields: Any) -> Iterator[None]:
    """Temporarily bind context fields; restores previous context on exit."""
    token = _CONTEXT.set({**_CONTEXT.get(), **{k: v for k, v in fields.items() if v is not None}})
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def preview_text(text: str | None, *, limit: int | None = None) -> str:
    """Truncate user-facing text for safe inclusion in ops logs."""
    if not text:
        return ""
    settings = get_settings()
    max_chars = limit if limit is not None else settings.log_query_preview_chars
    max_chars = max(0, int(max_chars))
    if max_chars == 0:
        return f"<len={len(text)}>"
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}…<len={len(text)}>"


def _is_sensitive_key(key: str) -> bool:
    lower = key.lower()
    if lower in _SENSITIVE_KEYS:
        return True
    for part in ("password", "passwd", "cookie", "authorization", "secret", "api_key", "apikey"):
        if part in lower:
            return True
    # Auth-style tokens only. Keep metric fields: window_tokens, summary_tokens, token_count.
    if lower in {"token", "access_token", "refresh_token", "id_token", "bearer"}:
        return True
    if lower.endswith("_token") and not lower.endswith("_tokens"):
        return True
    return False


def _scrub(value: Any) -> Any:
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if _is_sensitive_key(key_str):
                out[key_str] = "***"
            else:
                out[key_str] = _scrub(item)
        return out
    if isinstance(value, (list, tuple)):
        return [_scrub(item) for item in value]
    return value


class ContextFilter(logging.Filter):
    """Attach contextvars + record.kb_fields onto each LogRecord for formatters."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = get_log_context()
        for key, value in ctx.items():
            if not hasattr(record, key):
                setattr(record, key, value)
        extra_fields = getattr(record, "kb_fields", None)
        if isinstance(extra_fields, dict):
            for key, value in extra_fields.items():
                setattr(record, key, value)
        return True


class JsonFormatter(logging.Formatter):
    _RESERVED = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
        "kb_fields",
        "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in self._RESERVED or key.startswith("_"):
                continue
            if value is None:
                continue
            payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(_scrub(payload), ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras: list[str] = []
        for key in (
            "request_id",
            "job_id",
            "tenant_id",
            "user_id",
            "conversation_id",
            "document_id",
            "event",
            "duration_ms",
            "ok",
        ):
            value = getattr(record, key, None)
            if value is not None:
                extras.append(f"{key}={value}")
        if extras:
            return f"{base} {' '.join(extras)}"
        return base


def setup_logging() -> None:
    settings = get_settings()
    level_name = (settings.log_level or ("DEBUG" if settings.debug else "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(ContextFilter())
    if settings.log_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            TextFormatter(
                fmt="%(asctime)s level=%(levelname)s logger=%(name)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    for noisy in (
        "uvicorn.access",
        "httpx",
        "httpcore",
        "openai",
        "pdfminer",
        "pymilvus",
        "grpc",
        "urllib3",
        "transformers",
        "asyncio",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    msg: str,
    *,
    level: int = logging.INFO,
    event: str | None = None,
    **fields: Any,
) -> None:
    payload = {k: v for k, v in fields.items() if v is not None}
    if event is not None:
        payload["event"] = event
    logger.log(level, msg, extra={"kb_fields": payload})


@contextmanager
def timed_event(
    logger: logging.Logger,
    event: str,
    *,
    msg: str | None = None,
    **fields: Any,
) -> Iterator[dict[str, Any]]:
    """Time a block and emit a structured stage event with duration_ms and ok."""
    started = time.perf_counter()
    state: dict[str, Any] = {"ok": True}
    try:
        yield state
    except Exception as exc:
        state["ok"] = False
        state.setdefault("error", str(exc)[:200])
        raise
    finally:
        duration_ms = int((time.perf_counter() - started) * 1000)
        payload = {**fields, **state, "duration_ms": duration_ms}
        level = logging.INFO if state.get("ok", True) else logging.ERROR
        log_event(
            logger,
            msg or event,
            level=level,
            event=event,
            **payload,
        )
