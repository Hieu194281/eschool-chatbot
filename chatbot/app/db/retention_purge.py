"""PII retention (PDPD Decree 13/2023, red-team #12): scheduled purge of old
checkpoints + lead rows, and an on-request `delete_by_psid` erase procedure.

Thread activity is tracked in handoff_status.last_user_ts (touched on every inbound),
so it doubles as the retention clock for checkpoints.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from .pool import get_pool

logger = logging.getLogger(__name__)

_CHECKPOINT_TABLES = ("checkpoints", "checkpoint_writes", "checkpoint_blobs")


async def _delete_thread_rows(thread_id: str) -> None:
    pool = get_pool()
    for table in _CHECKPOINT_TABLES:
        try:
            async with pool.connection() as conn:
                await conn.execute(f"DELETE FROM {table} WHERE thread_id = %s", (thread_id,))
        except Exception:
            logger.debug("purge: table %s missing or delete failed (ignored)", table)


async def delete_by_psid(psid: str, channel: str = "messenger") -> str:
    """Erase all data for a user: checkpoints + handoff_status + lead row."""
    thread_id = f"{channel}:{psid}"
    await _delete_thread_rows(thread_id)
    try:
        async with get_pool().connection() as conn:
            await conn.execute("DELETE FROM handoff_status WHERE thread_id = %s", (thread_id,))
    except Exception:
        logger.exception("purge: handoff_status delete failed")
    try:
        from ..integrations.lead_sheet import get_lead_sheet

        await get_lead_sheet().delete_lead(thread_id)
    except Exception:
        logger.exception("purge: lead-row delete failed")
    logger.info("delete_by_psid complete for %s", thread_id)
    return thread_id


async def purge_expired(retention_days: int) -> int:
    """Delete checkpoints + handoff rows + lead rows older than the retention window."""
    pool = get_pool()
    interval = f"{int(retention_days)} days"
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT thread_id FROM handoff_status WHERE last_user_ts < now() - %s::interval",
            (interval,),
        )
        thread_ids = [row[0] for row in await cur.fetchall()]

    for thread_id in thread_ids:
        await _delete_thread_rows(thread_id)
    if thread_ids:
        async with pool.connection() as conn:
            await conn.execute(
                "DELETE FROM handoff_status WHERE last_user_ts < now() - %s::interval",
                (interval,),
            )

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    try:
        from ..integrations.lead_sheet import get_lead_sheet

        await get_lead_sheet().purge_older_than(cutoff)
    except Exception:
        logger.exception("purge: lead-sheet purge failed")

    logger.info("purge_expired removed %d expired threads", len(thread_ids))
    return len(thread_ids)


async def run_purge_loop(retention_days: int, interval_sec: int = 86400) -> None:
    """Daily retention sweep (started as an asyncio task in the lifespan)."""
    while True:
        try:
            await purge_expired(retention_days)
        except Exception:
            logger.exception("retention purge loop error")
        await asyncio.sleep(interval_sec)
