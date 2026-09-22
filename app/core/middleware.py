from __future__ import annotations

import logging
import time
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import (
    bind_context,
    clear_context,
    get_logger,
    is_valid_request_id,
    log_event,
    new_request_id,
)

logger = get_logger("api.request")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming.strip() if is_valid_request_id(incoming) else new_request_id()
        clear_context()
        bind_context(request_id=request_id)
        request.state.request_id = request_id

        started = time.perf_counter()
        log_event(
            logger,
            "request start",
            event="http.request_start",
            method=request.method,
            path=request.url.path,
        )
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            duration_ms = int((time.perf_counter() - started) * 1000)
            log_event(
                logger,
                "request failed",
                level=logging.ERROR,
                event="http.request_end",
                method=request.method,
                path=request.url.path,
                status=status_code,
                duration_ms=duration_ms,
                ok=False,
            )
            clear_context()
            raise

        duration_ms = int((time.perf_counter() - started) * 1000)
        response.headers[REQUEST_ID_HEADER] = request_id
        log_event(
            logger,
            "request end",
            event="http.request_end",
            method=request.method,
            path=request.url.path,
            status=status_code,
            duration_ms=duration_ms,
            ok=status_code < 500,
        )
        clear_context()
        return response
