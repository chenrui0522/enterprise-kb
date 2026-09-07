from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.chat.graph import ChatGraph
from app.core.config import get_settings
from app.core.db import create_tables_if_needed, dispose_engine
from app.core.errors import AppError
from app.core.logging import get_logger, setup_logging
from app.core.redis import close_redis, get_redis
from app.providers.factory import build_embedder, build_llm, build_reranker
from app.retrieval.milvus_store import MilvusStore
from app.retrieval.service import SearchService
from app.api.routers import chat, documents, system

logger = get_logger("api")

# psycopg async (used by langgraph-checkpoint-postgres) requires a selector
# event loop on Windows; uvicorn defaults to ProactorEventLoop there.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    await create_tables_if_needed()

    store = MilvusStore(settings)
    try:
        store.ensure_collection()
    except Exception:
        logger.warning("Milvus 暂不可用，将在首次检索/入库时重试", exc_info=settings.debug)

    llm = build_llm(settings)
    embedder = build_embedder(settings)
    reranker = build_reranker(settings)
    redis = get_redis()
    search_service = SearchService(settings, store, embedder, reranker, redis)

    checkpointer = None
    checkpointer_cm = None
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        # Newer langgraph-checkpoint-postgres exposes from_conn_string() as an
        # async context manager; keep it open for the whole app lifetime.
        checkpointer_cm = AsyncPostgresSaver.from_conn_string(settings.langgraph_pg_url)
        checkpointer = await checkpointer_cm.__aenter__()
        await checkpointer.setup()
    except Exception:
        logger.warning(
            "PostgreSQL LangGraph checkpointer 初始化失败，退回无状态模式（历史仍由应用层持久化）",
            exc_info=settings.debug,
        )
        if checkpointer_cm is not None:
            await checkpointer_cm.__aexit__(None, None, None)
        checkpointer = None
        checkpointer_cm = None

    app.state.settings = settings
    app.state.milvus_store = store
    app.state.search_service = search_service
    app.state.chat_graph = ChatGraph(
        llm, search_service, history_turns=settings.history_turns, checkpointer=checkpointer
    )
    app.state.checkpointer = checkpointer
    app.state.checkpointer_cm = checkpointer_cm

    yield

    if checkpointer_cm is not None:
        try:
            await checkpointer_cm.__aexit__(None, None, None)
        except Exception:
            logger.warning("关闭 checkpointer 时出错", exc_info=True)
    await close_redis()
    await dispose_engine()


def create_app() -> FastAPI:
    setup_logging()
    settings = get_settings()
    app = FastAPI(
        title="Enterprise KB API",
        version="0.1.0",
        lifespan=lifespan,
        openapi_url="/api/v1/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    app.include_router(system.router)
    app.include_router(chat.router, prefix="/api/v1")
    app.include_router(documents.router, prefix="/api/v1")
    return app


app = create_app()
