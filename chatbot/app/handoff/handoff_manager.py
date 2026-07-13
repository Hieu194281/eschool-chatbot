"""HandoffManager — the dispatcher's injected gate.

`before_invoke` (red-team #10): touches last_user_ts on EVERY inbound (via the
store's atomic touch) and uses the PREVIOUS user timestamp to decide auto-resume, so
the clock never freezes at handoff start. `before_send` (red-team #11) re-checks
`is_active` right before delivery to close the handoff TOCTOU window.

`should_auto_resume` is pure → unit-tested without a DB.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def should_auto_resume(prev_user_ts, prev_human_ts, now_ts, hours: int) -> bool:
    """True iff the user was silent > `hours` AND no recent human activity."""
    if prev_user_ts is None:
        return False
    window = hours * 3600
    if (now_ts - prev_user_ts).total_seconds() <= window:
        return False
    if prev_human_ts is not None and (now_ts - prev_human_ts).total_seconds() <= window:
        return False
    return True


class HandoffManager:
    def __init__(self, store, auto_resume_hours: int = 24) -> None:
        self._store = store
        self._hours = auto_resume_hours

    async def set_active(self, thread_id: str, reason: str) -> None:
        await self._store.set_active(thread_id, reason)

    async def clear(self, thread_id: str) -> None:
        await self._store.clear(thread_id)

    async def is_active(self, thread_id: str) -> bool:
        return await self._store.is_active(thread_id)

    async def before_invoke(self, thread_id: str, user_id: str) -> bool:
        """Return True to SKIP the bot (human handling). Touches the clock first."""
        row = await self._store.touch_user_and_get(thread_id)
        if not (row and row.get("prev_active")):
            return False                                  # not in handoff → proceed
        if should_auto_resume(row.get("prev_user_ts"), row.get("prev_human_ts"),
                              row.get("now_ts"), self._hours):
            logger.info("Auto-resume (24h silence) for %s", thread_id)
            await self._store.clear(thread_id)
            return False                                  # resumed → bot proceeds
        return True                                       # still handed off → skip bot

    async def before_send(self, thread_id: str) -> bool:
        """TOCTOU: return True to DROP the reply if handoff went active mid-invoke."""
        return await self._store.is_active(thread_id)


_manager_singleton: HandoffManager | None = None


def get_handoff_manager() -> HandoffManager:
    if _manager_singleton is None:
        raise RuntimeError("HandoffManager not set — wire it in the app lifespan.")
    return _manager_singleton


def set_handoff_manager(manager: HandoffManager) -> None:
    global _manager_singleton
    _manager_singleton = manager
