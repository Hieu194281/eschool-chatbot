"""Startup wiring helpers (keeps main.py lean). Heavy imports live inside functions
so `import app.main` stays cheap for tooling/tests.
"""

from __future__ import annotations

import asyncio
import logging

from .config import Settings

logger = logging.getLogger(__name__)


def setup_logging(settings: Settings) -> None:
    from . import log_redaction_filter

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log_redaction_filter.install()      # enforced phone redaction on all handlers


async def init_db_and_handoff(settings: Settings):
    """Open the shared pool, create handoff_status, register the HandoffManager."""
    from .db import open_pool
    from .db.handoff_status_table import PostgresHandoffStore, create_table
    from .handoff import HandoffManager, set_handoff_manager

    pool = await open_pool(settings.postgres_dsn)
    await create_table(pool)
    manager = HandoffManager(PostgresHandoffStore(pool), settings.handoff_auto_resume_hours)
    set_handoff_manager(manager)
    return pool, manager


async def init_kb(settings: Settings) -> None:
    """Wire the KB error sink → Telegram, do the initial off-loop rebuild, start sync."""
    from .integrations import telegram_notify
    from .kb import knowledge_base
    from .kb import sync_scheduler

    knowledge_base.set_error_callback(telegram_notify.notify_sync_errors)
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, knowledge_base.rebuild)   # off the event loop
    except Exception:
        logger.exception("Initial KB rebuild failed; serving will retry on next sync")
    sync_scheduler.start()


def build_channel_stack(app, settings: Settings, handoff_manager):
    """Create the Messenger adapter + dispatcher + dedupe/debounce/rate-limiter and
    attach them to app.state. Returns the shared httpx client (closed on shutdown)."""
    import httpx

    from .channel.debounce_buffer import DebounceBuffer
    from .channel.dedupe_store import DedupeStore
    from .channel.message_dispatcher import MessageDispatcher
    from .channel.messenger_adapter import MessengerAdapter
    from .channel.messenger_send_client import MessengerSendClient
    from .channel.rate_limiter import RateLimiter
    from .channel.shadow_gate import make_deliver_fn
    from .integrations import telegram_notify

    http_client = httpx.AsyncClient()
    send_client = MessengerSendClient(
        http_client, settings.page_access_token, settings.messenger_api_version
    )
    adapter = MessengerAdapter(send_client, settings.app_secret)

    def _budget_alert(spend: int) -> None:
        telegram_notify.notify_sync_errors([f"Gemini spend ~{spend} vượt ngân sách ngày."])

    rate_limiter = RateLimiter(
        settings.rate_limit_per_min, settings.rate_limit_per_day,
        settings.max_concurrent_invokes, settings.gemini_daily_budget,
        on_budget_alert=_budget_alert,
    )
    dispatcher = MessageDispatcher(
        adapter, rate_limiter,
        deliver_fn=make_deliver_fn(adapter),
        handoff_gate=handoff_manager,
        error_notify=telegram_notify.notify,
    )
    app.state.adapter = adapter
    app.state.dispatcher = dispatcher
    app.state.rate_limiter = rate_limiter
    app.state.dedupe = DedupeStore()
    app.state.debounce = DebounceBuffer(settings.debounce_seconds, dispatcher.on_flush)
    app.state.http_client = http_client
    return http_client
