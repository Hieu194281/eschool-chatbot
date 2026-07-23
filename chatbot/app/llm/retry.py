"""Bounded retry-with-jitter for LLM calls (red-team #4).

Each turn issues 2-4 LLM calls; a transient 429/5xx/timeout should not lose the
turn. Wrap each call in `with_retry`. On final give-up the exception propagates so
the caller (dispatcher) can send a soft-fail line + alert — the user's message is
NOT silently dropped.
"""

import asyncio
import logging
import random

logger = logging.getLogger(__name__)

_RETRYABLE_MARKERS = (
    "429", "500", "502", "503", "504",
    "timeout", "timed out", "deadline", "unavailable",
    "resourceexhausted", "resource exhausted", "rate limit", "overloaded",
)


def is_retryable(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in _RETRYABLE_MARKERS)


async def with_retry(fn, *, retries: int = 3, base: float = 0.5, cap: float = 8.0):
    """Call async zero-arg `fn`, retrying transient failures with exp backoff+jitter."""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001 — classify then re-raise
            last_exc = exc
            if attempt == retries or not is_retryable(exc):
                raise
            delay = min(cap, base * (2 ** attempt)) + random.uniform(0, base)
            logger.warning("LLM call failed (attempt %d/%d), retrying in %.2fs: %s",
                           attempt + 1, retries, delay, exc)
            await asyncio.sleep(delay)
    raise last_exc  # unreachable, keeps type-checkers happy
