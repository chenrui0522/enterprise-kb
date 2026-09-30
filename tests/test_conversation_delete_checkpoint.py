"""Checkpoint cleanup must not fail conversation delete."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.routers.chat import _best_effort_clear_checkpoint


@pytest.mark.asyncio
async def test_checkpoint_cleanup_swallows_errors() -> None:
    failing = SimpleNamespace(
        adelete_thread=AsyncMock(side_effect=RuntimeError("boom")),
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(checkpointer=failing)))
    await _best_effort_clear_checkpoint(request, "conv-1")  # type: ignore[arg-type]
    failing.adelete_thread.assert_awaited_once_with("conv-1")


@pytest.mark.asyncio
async def test_checkpoint_cleanup_noop_without_checkpointer() -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(checkpointer=None)))
    await _best_effort_clear_checkpoint(request, "conv-1")  # type: ignore[arg-type]
