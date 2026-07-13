"""mid dedupe: process once, bounded LRU, TTL expiry."""

import app.channel.dedupe_store as dedupe_mod
from app.channel.dedupe_store import DedupeStore


def test_same_mid_processed_once():
    store = DedupeStore()
    assert store.seen("m1") is False      # first time → record, not seen
    assert store.seen("m1") is True       # duplicate


def test_distinct_mids_independent():
    store = DedupeStore()
    assert store.seen("a") is False
    assert store.seen("b") is False


def test_bounded_lru():
    store = DedupeStore(maxsize=10)
    for i in range(100):
        store.seen(f"m{i}")
    assert len(store) <= 10


def test_ttl_expiry(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(dedupe_mod.time, "monotonic", lambda: clock[0])
    store = DedupeStore(ttl=10)
    assert store.seen("m1") is False
    clock[0] = 1005.0
    assert store.seen("m1") is True       # within TTL → still seen
    clock[0] = 1020.0
    assert store.seen("m1") is False      # expired → treated as new
