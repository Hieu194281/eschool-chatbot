"""Shared long-lived async Postgres pool (psycopg3). Opened in lifespan, closed on
shutdown. Used by handoff_status + retention (NOT by the checkpointer)."""

import logging

logger = logging.getLogger(__name__)

_pool = None


async def open_pool(dsn: str):
    global _pool
    if _pool is not None:
        return _pool
    from psycopg_pool import AsyncConnectionPool

    _pool = AsyncConnectionPool(conninfo=dsn, min_size=1, max_size=5, open=False)
    await _pool.open()
    logger.info("Postgres pool opened")
    return _pool


def get_pool():
    if _pool is None:
        raise RuntimeError("DB pool not opened — call open_pool() in the app lifespan.")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Postgres pool closed")
