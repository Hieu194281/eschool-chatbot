"""Deterministic "ask for a phone number only once" gate.

A prompt rule cannot enforce this. Told "chỉ xin 1 lần", the model still asks again
two turns later, because it has no memory of having asked — and a customer who
already declined reads the second ask as pressure. So the rule is enforced on
STATE: `phone_asked_at` is stamped when an ask goes out, and any later ask inside
the window is stripped.

Stripping the offending SENTENCE rather than blocking the whole reply is the point:
the rest of the answer is usually fine and worth sending.
"""

from __future__ import annotations

import re

_PHONE_ASK_RE = re.compile(
    r"(số\s*điện\s*thoại|sđt|\bsdt\b|\bzalo\b|số\s*liên\s*hệ|xin\s*số)",
    re.IGNORECASE,
)

# Sentence splitter that keeps the delimiter with the sentence.
_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?\n]*", re.UNICODE)

ASK_WINDOW_SECONDS = 24 * 60 * 60


def wants_phone(text: str) -> bool:
    return bool(_PHONE_ASK_RE.search(text or ""))


def should_suppress(state: dict, now: float) -> bool:
    """True when the bot already asked recently and still has no number."""
    state = state or {}
    if (state.get("lead_profile") or {}).get("sdt"):
        return False                       # already have it — nothing to suppress
    asked_at = state.get("phone_asked_at")
    if not asked_at:
        return False
    return (now - float(asked_at)) < ASK_WINDOW_SECONDS


def strip_phone_ask(text: str) -> str:
    """Drop the sentences that ask for a number, keep the rest of the reply."""
    kept = [s for s in _SENTENCE_RE.findall(text or "") if not wants_phone(s)]
    return re.sub(r"\s+", " ", "".join(kept)).strip()
