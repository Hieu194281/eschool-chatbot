"""In-process mid dedupe: TTL set, bounded LRU (red-team #6).

Meta redelivers unacked events → the same `mid` may arrive twice → process once.
Bounded so a flood of distinct mids can't grow memory without limit.
"""

import time
from collections import OrderedDict


class DedupeStore:
    def __init__(self, ttl: float = 600.0, maxsize: int = 20000) -> None:
        self._ttl = ttl
        self._maxsize = maxsize
        self._seen: "OrderedDict[str, float]" = OrderedDict()   # mid -> expiry

    def seen(self, mid: str) -> bool:
        """Return True if `mid` was already seen (still within TTL); else record it."""
        if not mid:
            return False
        now = time.monotonic()
        self._prune(now)
        expiry = self._seen.get(mid)
        if expiry is not None and expiry > now:
            self._seen.move_to_end(mid)
            return True
        self._seen[mid] = now + self._ttl
        self._seen.move_to_end(mid)
        while len(self._seen) > self._maxsize:
            self._seen.popitem(last=False)          # evict oldest (LRU)
        return False

    def _prune(self, now: float) -> None:
        # Lazily drop a few expired entries from the oldest end.
        for _ in range(8):
            if not self._seen:
                return
            mid, expiry = next(iter(self._seen.items()))
            if expiry > now:
                return
            self._seen.popitem(last=False)

    def __len__(self) -> int:
        return len(self._seen)
