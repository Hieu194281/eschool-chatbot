"""Abuse/cost controls (red-team #6): per-PSID sliding-window rate limit, a global
concurrency semaphore for in-flight graph turns, and a daily Gemini-spend counter
that trips a Telegram alert + canned-degrade when the budget is exceeded.
"""

import asyncio
import time
from collections import OrderedDict, deque


class RateLimiter:
    def __init__(
        self,
        per_min: int,
        per_day: int,
        max_concurrent: int,
        daily_budget: int = 0,
        on_budget_alert=None,
        maxsize: int = 20000,
    ) -> None:
        self._per_min = per_min
        self._per_day = per_day
        self._maxsize = maxsize
        self._windows: "OrderedDict[str, dict]" = OrderedDict()   # psid -> {min:deque, day:deque}
        self.sem = asyncio.Semaphore(max_concurrent)
        self._daily_budget = daily_budget
        self._on_budget_alert = on_budget_alert
        self._spend = 0
        self._spend_day = int(time.time() // 86400)
        self._alerted = False

    # ── per-PSID sliding window ──────────────────────────────
    def allow(self, psid: str) -> bool:
        now = time.monotonic()
        win = self._windows.get(psid)
        if win is None:
            win = {"min": deque(), "day": deque()}
            self._windows[psid] = win
            self._evict()
        self._windows.move_to_end(psid)
        self._prune(win["min"], now - 60)
        self._prune(win["day"], now - 86400)
        if len(win["min"]) >= self._per_min or len(win["day"]) >= self._per_day:
            return False
        win["min"].append(now)
        win["day"].append(now)
        return True

    @staticmethod
    def _prune(dq: deque, cutoff: float) -> None:
        while dq and dq[0] < cutoff:
            dq.popleft()

    def _evict(self) -> None:
        while len(self._windows) > self._maxsize:
            self._windows.popitem(last=False)

    # ── daily spend / budget ─────────────────────────────────
    def add_spend(self, tokens: int) -> None:
        today = int(time.time() // 86400)
        if today != self._spend_day:
            self._spend_day, self._spend, self._alerted = today, 0, False
        self._spend += max(0, tokens)
        if self._daily_budget and self._spend >= self._daily_budget and not self._alerted:
            self._alerted = True
            if self._on_budget_alert:
                self._on_budget_alert(self._spend)

    def budget_exceeded(self) -> bool:
        return bool(self._daily_budget) and self._spend >= self._daily_budget
