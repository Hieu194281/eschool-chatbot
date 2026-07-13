"""Webhook idempotency: a resent `mid` triggers a single flush (dedupe)."""

import asyncio
import types

from app.api.webhook_messenger import process_events
from app.channel.debounce_buffer import DebounceBuffer
from app.channel.dedupe_store import DedupeStore
from app.channel.messenger_adapter import MessengerAdapter
from app.channel.rate_limiter import RateLimiter


def _payload(mid, psid="1", text="hi"):
    return {"entry": [{"messaging": [{"sender": {"id": psid}, "message": {"mid": mid, "text": text}}]}]}


class _Dispatcher:
    async def deliver_text(self, uid, text):
        pass


def _fake_app(on_flush):
    state = types.SimpleNamespace(
        adapter=MessengerAdapter(None, "secret"),
        dedupe=DedupeStore(),
        debounce=DebounceBuffer(0.05, on_flush),
        rate_limiter=RateLimiter(100, 1000, 10),
        dispatcher=_Dispatcher(),
    )
    return types.SimpleNamespace(state=state)


async def test_duplicate_mid_single_flush():
    flushes = []

    async def on_flush(uid, text):
        flushes.append((uid, text))

    app = _fake_app(on_flush)
    await process_events(app, _payload("m1"))
    await process_events(app, _payload("m1"))    # Meta redelivery of same event
    await asyncio.sleep(0.12)
    assert len(flushes) == 1


async def test_distinct_mids_each_flush():
    flushes = []

    async def on_flush(uid, text):
        flushes.append((uid, text))

    app = _fake_app(on_flush)
    await process_events(app, _payload("m1", text="a"))
    await asyncio.sleep(0.12)
    await process_events(app, _payload("m2", text="b"))
    await asyncio.sleep(0.12)
    assert len(flushes) == 2
