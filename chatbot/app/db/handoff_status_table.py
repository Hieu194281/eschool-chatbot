"""Authoritative handoff state (red-team #8/#10/#11): the `handoff_status` table is
the single source of truth for the O(1) gate. ConvState.handoff is advisory only.

`PostgresHandoffStore` is the production backend; tests inject an in-memory store
with the same async method surface.
"""

from __future__ import annotations

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS handoff_status (
    thread_id     text PRIMARY KEY,
    active        boolean NOT NULL DEFAULT false,
    reason        text,
    since         timestamptz,
    last_user_ts  timestamptz,
    last_human_ts timestamptz
);
"""

# Atomic: capture PREVIOUS row (CTE snapshot) while stamping last_user_ts = now().
# Returns the pre-update values so the caller can measure the user-silence gap
# WITHOUT the clock freezing (red-team #10).
_TOUCH_SQL = """
WITH prev AS (
    SELECT active, last_user_ts, last_human_ts FROM handoff_status WHERE thread_id = %(tid)s
)
INSERT INTO handoff_status (thread_id, last_user_ts, active)
VALUES (%(tid)s, now(), false)
ON CONFLICT (thread_id) DO UPDATE SET last_user_ts = now()
RETURNING
    (SELECT active       FROM prev) AS prev_active,
    (SELECT last_user_ts FROM prev) AS prev_user_ts,
    (SELECT last_human_ts FROM prev) AS prev_human_ts,
    now() AS now_ts;
"""

_SET_ACTIVE_SQL = """
INSERT INTO handoff_status (thread_id, active, reason, since, last_human_ts)
VALUES (%(tid)s, true, %(reason)s, now(), now())
ON CONFLICT (thread_id) DO UPDATE
    SET active = true, reason = EXCLUDED.reason, since = now(), last_human_ts = now();
"""


async def create_table(pool) -> None:
    async with pool.connection() as conn:
        await conn.execute(CREATE_SQL)


class PostgresHandoffStore:
    def __init__(self, pool) -> None:
        self._pool = pool

    async def touch_user_and_get(self, thread_id: str) -> dict:
        from psycopg.rows import dict_row

        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(_TOUCH_SQL, {"tid": thread_id})
                return await cur.fetchone()

    async def is_active(self, thread_id: str) -> bool:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT active FROM handoff_status WHERE thread_id = %s", (thread_id,)
            )
            row = await cur.fetchone()
            return bool(row[0]) if row else False

    async def set_active(self, thread_id: str, reason: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(_SET_ACTIVE_SQL, {"tid": thread_id, "reason": reason})

    async def clear(self, thread_id: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE handoff_status SET active = false WHERE thread_id = %s", (thread_id,)
            )
