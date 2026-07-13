"""Enforced phone-number log redaction (red-team #12) — a logging.Filter, NOT a
convention. Installed on the root logger's handlers so every record is masked
regardless of which module logged it.
"""

import logging
import re

# VN phone: leading 0 + 8..10 digits, not embedded in a longer digit run.
_PHONE_RE = re.compile(r"(?<!\d)(0\d{8,10})(?!\d)")


def _mask(match: re.Match) -> str:
    digits = match.group(1)
    return digits[:3] + "*" * (len(digits) - 5) + digits[-2:]


class PhoneRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
            if _PHONE_RE.search(message):
                record.msg = _PHONE_RE.sub(_mask, message)
                record.args = ()
        except Exception:
            pass
        return True


def install() -> None:
    """Attach the redaction filter to every root handler (and the root logger)."""
    root = logging.getLogger()
    flt = PhoneRedactionFilter()
    root.addFilter(flt)
    for handler in root.handlers:
        handler.addFilter(flt)
