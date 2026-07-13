"""Vietnamese money/number normalization for the deterministic pricing-guard.

The pricing-guard must decide whether every money token in a draft reply is a
*literal* value from the named course's Sheet pricing. To compare "4tr5",
"4.500.000" and "4,500,000" as equal, both the draft and the KB pricing string
are canonicalized to integer VND with the SAME function here.

Design property that matters most: CONSISTENCY (same input → same output on both
sides). Ambiguous colloquial forms may fail to match — that is acceptable because
the guard is fail-closed (a non-match → honest fallback, never a wrong price).

False-positive avoidance: a bare number is treated as money only when it carries a
VN money unit (triệu/tr/củ/k/nghìn/ngàn/đồng…) OR is a grouped-thousands form
(1.500.000) OR a bare integer ≥ 6 digits. This keeps "lớp 6", "2 buổi/tuần",
"15/8", "năm 2026" and phone numbers from being read as prices.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_MILLION = 1_000_000
_THOUSAND = 1_000

# Ordered alternation — most specific first. finditer consumes each match so a
# number is never double-counted. Applied to lower-cased text.
_TOKEN_RE = re.compile(
    r"(?P<pct>\d+(?:[.,]\d+)?)\s*%"
    r"|(?P<mil>\d+(?:[.,]\d+)?)\s*(?:triệu|trieu|tr(?![a-zà-ỹ])|củ|cu(?![a-zà-ỹ]))"
    r"\.?\s*(?P<milhalf>rưỡi|ruoi)?\s*(?P<milsub>\d+)?"
    r"|(?P<k>\d+(?:[.,]\d+)?)\s*(?:nghìn|nghin|ngàn|ngan|k)(?![a-zà-ỹ])"
    r"|(?P<grouped>\d{1,3}(?:[.,]\d{3})+)"
    r"|(?P<bare>\d{6,})",
    re.IGNORECASE,
)

_PHONE_RE = re.compile(r"^0\d{8,10}$")


@dataclass(frozen=True)
class MoneyToken:
    raw: str          # matched substring
    value: int        # canonical VND (or the raw percent value for kind="pct")
    kind: str         # "money" | "pct"


def _to_float(num: str) -> float:
    """Parse a numeric literal that may use ',' or '.' as a decimal point."""
    return float(num.replace(",", "."))


def _million_value(base: str, milhalf: str | None, milsub: str | None) -> int:
    """Value of an 'X triệu [rưỡi|Y]' expression in VND."""
    if "." in base or "," in base:          # decimal base e.g. "4.5 triệu"
        return round(_to_float(base) * _MILLION)
    value = int(base) * _MILLION
    if milhalf:                              # "4 triệu rưỡi" → +0.5 triệu
        value += _MILLION // 2
    elif milsub:                             # "4tr5"→+500k, "4tr500"→+500k, "4tr05"→+50k
        value += int(milsub) * (10 ** (6 - len(milsub)))
    return value


def _grouped_value(text: str) -> int:
    """'1.500.000' or '1,500,000' → 1500000 (separators stripped)."""
    return int(re.sub(r"[.,]", "", text))


def iter_money_tokens(text: str):
    """Yield MoneyToken for every money/percent-like token in `text`."""
    for m in _TOKEN_RE.finditer(text or ""):
        if m.group("pct") is not None:
            yield MoneyToken(m.group(0), round(_to_float(m.group("pct"))), "pct")
        elif m.group("mil") is not None:
            yield MoneyToken(
                m.group(0),
                _million_value(m.group("mil"), m.group("milhalf"), m.group("milsub")),
                "money",
            )
        elif m.group("k") is not None:
            yield MoneyToken(m.group(0), round(_to_float(m.group("k")) * _THOUSAND), "money")
        elif m.group("grouped") is not None:
            yield MoneyToken(m.group(0), _grouped_value(m.group("grouped")), "money")
        elif m.group("bare") is not None:
            raw = m.group("bare")
            if _PHONE_RE.match(raw):         # skip phone numbers — not prices
                continue
            yield MoneyToken(raw, int(raw), "money")


def money_values(text: str) -> set[int]:
    """Canonical VND set of all money tokens (excludes percentages)."""
    return {t.value for t in iter_money_tokens(text) if t.kind == "money"}


def percent_values(text: str) -> set[int]:
    """Set of percentage values (e.g. {10} for 'giảm 10%')."""
    return {t.value for t in iter_money_tokens(text) if t.kind == "pct"}
