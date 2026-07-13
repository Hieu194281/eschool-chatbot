"""FastAPI app factory + lifespan — the single integration point for all phases.

Lifespan order:
  logging+redaction → require secrets → capture loop → DB pool + handoff table →
  KB (error sink + initial rebuild + scheduler) → OPEN AsyncPostgresSaver context
  (kept open for the whole app lifetime — red-team #3) → build+register graph →
  channel stack → retention purge loop → yield → graceful cleanup.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .bootstrap import build_channel_stack, init_db_and_handoff, init_kb, setup_logging
from .config import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings)
    settings.require_serve_secrets()
    os.environ.setdefault(
        "LANGGRAPH_STRICT_MSGPACK", "true" if settings.langgraph_strict_msgpack else "false"
    )

    from .integrations import telegram_notify
    telegram_notify.set_main_loop(asyncio.get_running_loop())

    pool, handoff_manager = await init_db_and_handoff(settings)
    app.state.handoff_manager = handoff_manager
    await init_kb(settings)

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from .db import close_pool
    from .db.retention_purge import run_purge_loop
    from .graph.graph_builder import build_graph, set_graph
    from .kb import sync_scheduler

    # Keep the saver's async context OPEN for the whole app lifetime (pool stays up).
    async with AsyncPostgresSaver.from_conn_string(settings.postgres_dsn) as saver:
        await saver.setup()
        set_graph(build_graph(saver))
        http_client = build_channel_stack(app, settings, handoff_manager)
        purge_task = asyncio.create_task(run_purge_loop(settings.pii_retention_days))
        logger.info("Startup complete (SHADOW_MODE=%s)", settings.shadow_mode)
        try:
            yield
        finally:
            purge_task.cancel()
            sync_scheduler.shutdown()
            await http_client.aclose()
            await close_pool()


def create_app() -> FastAPI:
    app = FastAPI(title="Tuyển Sinh Concierge", lifespan=lifespan)

    from .api.webhook_messenger import router as messenger_router
    from .api.webhook_telegram import router as telegram_router

    app.include_router(messenger_router)
    app.include_router(telegram_router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
