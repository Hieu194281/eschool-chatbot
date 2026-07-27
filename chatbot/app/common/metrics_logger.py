"""Structured shadow-mode metrics — one JSON line per decision point.

WHITELIST, not blacklist. Every field a caller passes is dropped unless it is
listed here, and every value is coerced to a scalar/enum. A blacklist would leak
the first field somebody forgets to add to it, and this log is a brand-new PII
surface sitting next to `sdt` and `khung_gio_tien`.

The metric that matters most is not accuracy, it's the BLOCK RATE. A guard tuned
too tight makes the bot answer with the honest-fallback line forever: no error
fires, no incident is raised, and sales quietly dies. `guard_blocked` +
`violation_kinds` is what makes that visible.

Emitted on its own logger (`shadow.metrics`) so a summarizer can read it without
wading through application logs.
"""

from __future__ import annotations

import json
import logging

metrics_logger = logging.getLogger("shadow.metrics")

# Everything the summarizer needs — and nothing free-text.
ALLOWED_FIELDS = frozenset({
    "event",              # "guard" | "objection" | "lead" | "tools" | "phone_ask" | "turn"
    "stage",              # SalesStage.*
    "objection_type",     # enum from objection_prompt
    "escalated",          # bool — objection routed to a human
    "guard_blocked",      # bool
    "violation_kinds",    # list[str] of guard_checks.Kind — NEVER the message
    "phone_asked",        # bool — an ask went out this turn
    "phone_suppressed",   # bool — a repeat ask was stripped (target: ~0)
    "has_phone",          # bool — presence only, never the number
    "tool_names",         # list[str] of bound tool names
    "retrieved_count",    # int
    "latency_ms",         # int
    "handoff",            # bool
})

_SCALARS = (bool, int, float, str)


def _clean(value):
    """Scalars pass; lists become lists of scalars; anything else is dropped."""
    if isinstance(value, _SCALARS) or value is None:
        return value
    if isinstance(value, (list, tuple, set)):
        return sorted(str(v) for v in value)
    return None


def emit(**event) -> None:
    """Write one metrics line. Unknown fields are dropped, never logged."""
    payload = {}
    for key, value in event.items():
        if key not in ALLOWED_FIELDS:
            continue
        cleaned = _clean(value)
        if cleaned is not None:
            payload[key] = cleaned
    if not payload:
        return
    try:
        metrics_logger.info(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    except Exception:      # metrics must never break a reply
        logging.getLogger(__name__).debug("metrics emit failed", exc_info=True)
