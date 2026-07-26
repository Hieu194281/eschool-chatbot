"""Per-thread single-flight: concurrent same-thread messages never run two
graph invokes at once (no checkpoint clobber). Different threads may overlap.
"""

import asyncio

from app.channel.message_dispatcher import MessageDispatcher
from app.channel.rate_limiter import RateLimiter


class FakeAdapter:
    channel = "messenger"

    async def send_text(self, uid, text):
        pass

    async def send_typing(self, uid, on):
        pass


def _make_dispatcher(monkeypatch, tracker):
    delivered = []

    async def deliver(uid, text):
        delivered.append(text)

    disp = MessageDispatcher(FakeAdapter(), RateLimiter(1000, 10000, 50),
                             deliver_fn=deliver, handoff_gate=None)

    async def fake_invoke(thread_id, user_id, text):
        tracker["cur"] += 1
        tracker["max"] = max(tracker["max"], tracker["cur"])
        await asyncio.sleep(0.05)
        tracker["cur"] -= 1
        return f"reply:{text}", False        # (reply, bot escalated to a human?)

    monkeypatch.setattr(disp, "_invoke_graph", fake_invoke)
    return disp, delivered


async def test_same_thread_serialized(monkeypatch):
    tracker = {"cur": 0, "max": 0}
    disp, delivered = _make_dispatcher(monkeypatch, tracker)
    await asyncio.gather(disp.on_flush("1", "a"), disp.on_flush("1", "b"))
    assert tracker["max"] == 1          # never two invokes on the same thread
    assert len(delivered) == 2


async def test_different_threads_may_overlap(monkeypatch):
    tracker = {"cur": 0, "max": 0}
    disp, delivered = _make_dispatcher(monkeypatch, tracker)
    await asyncio.gather(disp.on_flush("1", "a"), disp.on_flush("2", "b"))
    assert tracker["max"] == 2          # distinct threads allowed to run concurrently
    assert len(delivered) == 2
