"""Per-user debounce buffer (red-team #6 bounded).

VN users send 3-5 fragment messages → buffer per user, coalesce, run the graph once
on the joined text. Cancel-and-reschedule the flush timer on each new fragment.
Bounded (LRU) so idle users don't leak memory.

Single-flight note: the flush pops the buffer BEFORE awaiting on_flush. A fragment
arriving during an in-flight turn therefore starts a FRESH buffer that flushes after
the current turn's per-thread lock releases (next batch) — never a parallel run.
"""

import asyncio
import logging
from collections import OrderedDict

logger = logging.getLogger(__name__)


class DebounceBuffer:
    def __init__(self, delay: float, on_flush, maxsize: int = 10000) -> None:
        self._delay = delay
        self._on_flush = on_flush                 # async (user_id, joined_text) -> None
        self._maxsize = maxsize
        self._buffers: "OrderedDict[str, dict]" = OrderedDict()

    def add(self, user_id: str, text: str) -> None:
        buf = self._buffers.get(user_id)
        if buf is None:
            buf = {"parts": [], "task": None}
            self._buffers[user_id] = buf
            self._evict()
        self._buffers.move_to_end(user_id)
        buf["parts"].append(text)
        if buf["task"] is not None:
            buf["task"].cancel()
        buf["task"] = asyncio.create_task(self._flush_later(user_id))

    async def _flush_later(self, user_id: str) -> None:
        try:
            await asyncio.sleep(self._delay)
        except asyncio.CancelledError:
            return
        buf = self._buffers.pop(user_id, None)     # pop BEFORE flush → fresh buffer next time
        if not buf:
            return
        joined = " ".join(p for p in buf["parts"] if p).strip()
        if not joined:
            return
        try:
            await self._on_flush(user_id, joined)
        except Exception:
            logger.exception("debounce on_flush failed for %s", user_id)

    def _evict(self) -> None:
        while len(self._buffers) > self._maxsize:
            _uid, buf = self._buffers.popitem(last=False)
            if buf["task"] is not None:
                buf["task"].cancel()

    def __len__(self) -> int:
        return len(self._buffers)
