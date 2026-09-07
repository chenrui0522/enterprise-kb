"""Windows-friendly API entry point.

psycopg async (langgraph checkpointer) requires a selector event loop on
Windows; set the policy before uvicorn builds its loop.
"""

from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("app.api.main:app", host="127.0.0.1", port=8000, reload=False)
