"""Dispatcher: flush → per-thread single-flight lock → handoff gate (Ph05 seam) →
global concurrency semaphore → graph.ainvoke → deliver.

Single-flight (red-team #5): one `asyncio.Lock` per thread_id serializes
flush→invoke→send so two messages on the same thread never launch concurrent
`ainvoke` calls (which would clobber the checkpoint). A fragment arriving mid-turn
lands in a fresh debounce buffer and awaits this lock → runs as the next batch.

The handoff gate + shadow gate are injected seams so Phases 05/06 wire behavior
without changing this file's control flow.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

SOFT_FAIL_LINE = (
    "Dạ hệ thống đang hơi bận, anh/chị nhắn lại giúp em sau ít phút nhé. Em xin lỗi ạ! 🙏"
)
RATE_LIMIT_LINE = "Dạ em nhận hơi nhiều tin một lúc, anh/chị chờ em chút rồi nhắn lại nhé ạ 🌸"
BUDGET_DEGRADE_LINE = (
    "Dạ hôm nay em hơi quá tải, để tư vấn viên hỗ trợ mình trực tiếp nhé. "
    "Anh/chị để lại số điện thoại giúp em ạ 🌸"
)
_EST_TOKENS_PER_TURN = 2000   # crude proxy for the daily Gemini-spend guard (Pha 1)


def _extract_reply(state: dict) -> str:
    from langchain_core.messages import AIMessage

    for msg in reversed(state.get("messages", []) or []):
        if isinstance(msg, AIMessage) and getattr(msg, "content", None):
            return msg.content if isinstance(msg.content, str) else str(msg.content)
    return ""


class MessageDispatcher:
    def __init__(self, adapter, rate_limiter, deliver_fn=None,
                 handoff_gate=None, error_notify=None) -> None:
        self._adapter = adapter
        self._rate_limiter = rate_limiter
        self._deliver_fn = deliver_fn or adapter.send_text   # Ph06 overrides w/ shadow gate
        self._handoff_gate = handoff_gate                    # Ph05 provides
        self._error_notify = error_notify                    # Ph05 Telegram alert
        self._locks: dict = {}

    def _lock(self, thread_id: str):
        import asyncio

        lock = self._locks.get(thread_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[thread_id] = lock
        return lock

    async def on_flush(self, user_id: str, joined_text: str) -> None:
        thread_id = f"{self._adapter.channel}:{user_id}"
        async with self._lock(thread_id):                    # SINGLE-FLIGHT
            await self._handle(thread_id, user_id, joined_text)

    async def _handle(self, thread_id: str, user_id: str, text: str) -> None:
        # Ph05 seam: touch last_user_ts + handoff gate + auto-resume. None → no gating.
        if self._handoff_gate is not None:
            if await self._handoff_gate.before_invoke(thread_id, user_id):
                logger.info("handoff active for %s → bot skips", thread_id)
                return

        # Gemini daily-budget degrade: stop spending, hand to humans (red-team #6).
        if self._rate_limiter.budget_exceeded():
            await self.deliver_text(user_id, BUDGET_DEGRADE_LINE)
            return

        async with self._rate_limiter.sem:                   # global concurrency cap
            reply = await self._invoke_graph(thread_id, user_id, text)
        self._rate_limiter.add_spend(_EST_TOKENS_PER_TURN)

        if not reply:
            return
        # TOCTOU close (Ph05): drop reply if handoff went active during the invoke.
        if self._handoff_gate is not None and await self._handoff_gate.before_send(thread_id):
            logger.info("handoff flipped mid-invoke for %s → drop reply", thread_id)
            return
        await self.deliver_text(user_id, reply)

    async def _invoke_graph(self, thread_id: str, user_id: str, text: str) -> str:
        from langchain_core.messages import HumanMessage

        from ..graph.graph_builder import get_graph

        try:
            graph = get_graph()
            state = await graph.ainvoke(
                {"messages": [HumanMessage(content=text)],
                 "user_id": user_id, "channel": self._adapter.channel},
                config={"configurable": {"thread_id": thread_id}},
            )
            return _extract_reply(state)
        except Exception as exc:                             # never lose the turn silently
            logger.exception("graph invoke failed for %s", thread_id)
            if self._error_notify is not None:
                await self._error_notify(f"⚠️ Lỗi xử lý {thread_id}: {exc}")
            return SOFT_FAIL_LINE

    async def deliver_text(self, user_id: str, text: str) -> None:
        """Typing indicator + deliver (shadow-gate aware in Ph06)."""
        try:
            await self._adapter.send_typing(user_id, True)
        except Exception:
            logger.debug("typing_on failed (non-fatal)")
        await self._deliver_fn(user_id, text)
