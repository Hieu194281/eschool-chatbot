"""Vietnamese date/time tokenization for the deterministic schedule guard.

Deliberately a SEPARATE module from `vn_numerals.py`. That module's `_TOKEN_RE`
goes out of its way to NOT match dates ("15/8", "năm 2026", phone numbers); a date
tokenizer bolted into the same alternation would fight it. Two regexes, two files,
no interference (plan review H2).

Same contract as the money side: canonicalize BOTH the draft and the KB facts with
this function, then compare. Non-matching → fail closed.

Two false-positive rules, both deliberate:
- A bare `Nh` with N ≤ 4 and no minutes is a DURATION ("mỗi buổi 2h"), not a clock
  time. Reading it as 02:00 would block a perfectly normal sentence.
- Day/month must be a real calendar pair (1-31 / 1-12), so "3/4 học viên" and
  similar fractions mostly fall out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Ordered alternation, most specific first — finditer consumes each match, so a
# date is never re-read as a time.
_DATE_RE = re.compile(
    r"(?P<dmy>\b(?P<d1>\d{1,2})/(?P<m1>\d{1,2})/(?P<y>\d{2,4})\b)"
    r"|(?P<dm>\b(?P<d2>\d{1,2})/(?P<m2>\d{1,2})\b)"
    r"|ngày\s+(?P<d3>\d{1,2})\s*tháng\s*(?P<m3>\d{1,2})"
    r"|ngày\s+(?P<d4>\d{1,2})(?![\d/])"
    # `h` must not be the first letter of a word: "lớp 7 học" is not 07:00, and
    # reading it as one both blocks valid replies and hides the "7" that names the
    # course. The digits of "18h30" still pass — only LETTERS are excluded.
    r"|(?P<time>\b(?P<hh>\d{1,2})\s*(?:h(?![a-zà-ỹ])|:|giờ)\s*(?P<mm>\d{2})?)",
    re.IGNORECASE,
)

_MAX_DURATION_HOURS = 4       # above this, a bare "Nh" reads as a clock time


@dataclass(frozen=True)
class DateToken:
    raw: str
    kind: str                  # "date" | "time"
    day: int | None = None
    month: int | None = None
    year: int | None = None
    minutes: int | None = None  # minutes since midnight, for kind="time"


def _valid_day_month(day: int, month: int) -> bool:
    return 1 <= day <= 31 and 1 <= month <= 12


def _normalize_year(raw: str | None) -> int | None:
    if not raw:
        return None
    year = int(raw)
    return year + 2000 if year < 100 else year


def _time_token(raw: str, hour: str, minute: str | None) -> DateToken | None:
    hh = int(hour)
    if hh > 23:
        return None
    if minute is None and hh <= _MAX_DURATION_HOURS:
        return None                              # "2h" = thời lượng, not 02:00
    mm = int(minute) if minute else 0
    if mm > 59:
        return None
    return DateToken(raw=raw, kind="time", minutes=hh * 60 + mm)


def iter_date_tokens(text: str):
    """Yield a DateToken for every date/time-like token in `text`."""
    for m in _DATE_RE.finditer(text or ""):
        if m.group("dmy"):
            day, month = int(m.group("d1")), int(m.group("m1"))
            if _valid_day_month(day, month):
                yield DateToken(m.group(0), "date", day, month, _normalize_year(m.group("y")))
        elif m.group("dm"):
            day, month = int(m.group("d2")), int(m.group("m2"))
            if _valid_day_month(day, month):
                yield DateToken(m.group(0), "date", day, month)
        elif m.group("d3"):
            day, month = int(m.group("d3")), int(m.group("m3"))
            if _valid_day_month(day, month):
                yield DateToken(m.group(0), "date", day, month)
        elif m.group("d4"):
            day = int(m.group("d4"))
            if 1 <= day <= 31:
                yield DateToken(m.group(0), "date", day)      # month unknown
        elif m.group("time"):
            token = _time_token(m.group(0), m.group("hh"), m.group("mm"))
            if token:
                yield token


def token_allowed(token: DateToken, allowed: list[DateToken]) -> bool:
    """Is `token` covered by any KB token? Missing parts are wildcards.

    A draft that omits the year ("khai giảng 05/08") must still match a KB value
    that states one ("05/08/2026") — and vice versa. Only stated parts must agree.
    """
    for other in allowed:
        if other.kind != token.kind:
            continue
        if token.kind == "time":
            if other.minutes == token.minutes:
                return True
            continue
        if other.day != token.day:
            continue
        if None not in (token.month, other.month) and token.month != other.month:
            continue
        if None not in (token.year, other.year) and token.year != other.year:
            continue
        return True
    return False
