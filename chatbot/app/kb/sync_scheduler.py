"""APScheduler BackgroundScheduler wrapper for periodic KB rebuilds.

BackgroundScheduler (thread) is the committed choice: `rebuild()` is blocking/sync
and must NOT run on the event loop. The scheduler thread runs it every
`KB_SYNC_INTERVAL_SEC`; the atomic snapshot swap in KnowledgeBase makes concurrent
async reads safe.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from ..config import get_settings
from .vector_store import knowledge_base

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def start() -> None:
    """Start the interval job. Idempotent."""
    global _scheduler
    if _scheduler is not None:
        return
    settings = get_settings()
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        knowledge_base.rebuild,
        trigger="interval",
        seconds=settings.kb_sync_interval_sec,
        id="kb_sync",
        max_instances=1,           # never overlap two rebuilds
        coalesce=True,
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("KB sync scheduler started (interval=%ds)", settings.kb_sync_interval_sec)


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("KB sync scheduler stopped")
