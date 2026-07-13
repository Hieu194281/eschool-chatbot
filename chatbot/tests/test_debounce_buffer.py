"""Debounce: N fragments → one flush on joined text; timer reset; bounded."""

import asyncio

from app.channel.debounce_buffer import DebounceBuffer


async def test_fragments_coalesced_into_one_flush():
    flushes = []

    async def on_flush(uid, text):
        flushes.append((uid, text))

    buf = DebounceBuffer(0.05, on_flush)
    buf.add("u", "xin")
    buf.add("u", "chào")
    buf.add("u", "em")
    await asyncio.sleep(0.15)
    assert flushes == [("u", "xin chào em")]


async def test_timer_resets_on_each_fragment():
    flushes = []

    async def on_flush(uid, text):
        flushes.append(text)

    buf = DebounceBuffer(0.1, on_flush)
    buf.add("u", "a")
    await asyncio.sleep(0.05)
    buf.add("u", "b")
    await asyncio.sleep(0.05)
    assert flushes == []            # not yet — timer was reset
    await asyncio.sleep(0.12)
    assert flushes == ["a b"]


async def test_bounded_buffer():
    async def noop(uid, text):
        pass

    buf = DebounceBuffer(10.0, noop, maxsize=5)
    for i in range(20):
        buf.add(f"u{i}", "x")
    assert len(buf) <= 5
