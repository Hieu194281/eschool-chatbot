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
# Spelled-out numerals. Sales chat says "bốn triệu rưỡi" as often as "4tr5", and a
# price the tokenizer cannot see is a price the guard cannot check — the draft
# sails through instead of failing closed.
# Unaccented spellings are NOT optional extras — Messenger chat drops diacritics
# constantly, and a missing entry makes the whole phrase unmatchable, i.e. an
# invisible price rather than a wrong one.
_WORD_DIGITS = {
    "một": 1, "mot": 1, "mốt": 1, "hai": 2, "ba": 3, "bốn": 4, "bon": 4,
    "tư": 4, "tu": 4, "năm": 5, "nam": 5, "lăm": 5, "lam": 5, "nhăm": 5, "nham": 5,
    "sáu": 6, "sau": 6, "bảy": 7, "bay": 7, "tám": 8, "tam": 8, "chín": 9, "chin": 9,
}
_BILLION = 1_000_000_000
_WORD_ALT = "|".join(sorted(_WORD_DIGITS, key=len, reverse=True))

# Tens must be parsed, not ignored: matching only the trailing word of
# "mười lăm triệu" yields 5.000.000 — a WRONG value that then passes against a
# course actually priced at 5tr while the customer reads fifteen million. A wrong
# value is worse than a missed one, because it looks verified.
_TENS_ALT = rf"mười|muoi|(?:{_WORD_ALT})\s*mươi|(?:{_WORD_ALT})\s*muoi"
_WORD_NUM = rf"(?:(?:{_TENS_ALT})(?:\s*(?:{_WORD_ALT}))?|(?:{_WORD_ALT}))"


_TEN_WORDS = ("mười", "muoi", "mươi")


def _word_number(text: str) -> int:
    """'bốn' → 4 · 'mười' → 10 · 'mười lăm' → 15 · 'hai mươi mốt' → 21."""
    parts = [p for p in text.strip().lower().split() if p]
    if not parts:
        return 0
    if parts[0] in ("mười", "muoi"):                  # 10..19
        return 10 + (_WORD_DIGITS.get(parts[1], 0) if len(parts) > 1 else 0)
    if len(parts) > 1 and parts[1] in _TEN_WORDS:     # 20..99
        return _WORD_DIGITS.get(parts[0], 0) * 10 + (
            _WORD_DIGITS.get(parts[2], 0) if len(parts) > 2 else 0)
    return _WORD_DIGITS.get(parts[0], 0)

_TOKEN_RE = re.compile(
    r"(?P<pct>\d+(?:[.,]\d+)?)\s*%"
    r"|(?P<mil>\d+(?:[.,]\d+)?)\s*(?:triệu|trieu|tr(?![a-zà-ỹ])|củ|cu(?![a-zà-ỹ]))"
    r"\.?\s*(?P<milhalf>rưỡi|ruoi)?\s*(?P<milsub>\d+)?"
    r"|(?P<k>\d+(?:[.,]\d+)?)\s*(?:nghìn|nghin|ngàn|ngan|k)(?![a-zà-ỹ])"
    # `tỷ lệ` (pass rate — everywhere in admissions talk) and `tỉ mỉ` (praise for a
    # teacher) are NOT billions. Without this guard "một tỷ lệ nhỏ học viên" becomes
    # 1.000.000.000 and honest-fallbacks an ordinary sentence.
    rf"|(?P<bil>\d+(?:[.,]\d+)?|{_WORD_NUM})\s*(?:tỷ|tỉ|ty(?![a-zà-ỹ]))"
    r"(?!\s*(?:lệ|le(?![a-zà-ỹ])|mỉ|mi(?![a-zà-ỹ])|phú|phu(?![a-zà-ỹ])))"
    r"|(?P<grouped>\d{1,3}(?:[.,]\d{3})+)"
    rf"|(?P<milw>{_WORD_NUM})\s*(?:triệu|trieu|củ|cu(?![a-zà-ỹ]))"
    rf"\s*(?:(?P<milwhalf>rưỡi|ruoi)|(?P<milwsub>{_WORD_ALT})(?![a-zà-ỹ]))?"
    rf"|(?P<hundw>{_WORD_NUM})\s*(?:trăm|tram)\s*(?:nghìn|nghin|ngàn|ngan)"
    rf"|(?P<kw>{_WORD_NUM})\s*(?:nghìn|nghin|ngàn|ngan)(?![a-zà-ỹ])"
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
        elif m.group("milw") is not None:
            value = _word_number(m.group("milw")) * _MILLION
            if m.group("milwhalf"):
                value += _MILLION // 2
            elif m.group("milwsub"):                 # "một triệu tám" → 1.8tr
                value += _WORD_DIGITS[m.group("milwsub").lower()] * 100 * _THOUSAND
            yield MoneyToken(m.group(0), value, "money")
        elif m.group("hundw") is not None:
            yield MoneyToken(m.group(0),
                             _word_number(m.group("hundw")) * 100 * _THOUSAND, "money")
        elif m.group("kw") is not None:
            yield MoneyToken(m.group(0), _word_number(m.group("kw")) * _THOUSAND, "money")
        elif m.group("bil") is not None:
            raw = m.group("bil")
            count = _to_float(raw) if raw[0].isdigit() else _word_number(raw)
            yield MoneyToken(m.group(0), round(count * _BILLION), "money")
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
