"""The three deterministic checks the pricing-guard runs against a bound course.

Each returns a list of violation strings (empty = clean). Split out of
`pricing_guard.py` so the orchestration stays readable and each rule is testable
on its own — this is the last gate before send, there is no net below it.

Money and dates are treated DIFFERENTLY on purpose:
- A money token always belongs to a course. No course bound → block.
- A date/time token may legitimately come from centre info (giờ mở cửa) or an FAQ.
  No course bound → skip silently rather than block a correct answer.
"""

from __future__ import annotations

import re

from ...common.vn_dates import iter_date_tokens, token_allowed
from ...common.vn_numerals import iter_money_tokens

_FREE_RE = re.compile(r"miễn\s*phí|mien\s*phi|\bfree\b", re.IGNORECASE)


class Kind:
    """Violation categories — the only guard detail safe to put in metrics.

    The message itself quotes the draft ("số tiền ... '4tr5'"), so shipping
    messages to the metrics log would smuggle free text into it.
    """

    MONEY = "money"
    PERCENT = "percent"
    FREE_CLAIM = "free_claim"
    SCHEDULE = "schedule"
    CONCESSION = "concession"
    NO_COURSE = "no_course"
    AMBIGUOUS = "ambiguous"
    INTERNAL = "internal"


class Violation(str):
    """A violation message that also carries its category.

    Subclassing `str` keeps every existing consumer (joins, `in` checks, logs)
    working unchanged while `.kind` rides along for metrics.
    """

    kind: str

    def __new__(cls, kind: str, message: str):
        obj = super().__new__(cls, message)
        obj.kind = kind
        return obj


def kinds_of(violations) -> list[str]:
    return sorted({getattr(v, "kind", Kind.INTERNAL) for v in violations})

# Phrases that invent a discount out of thin air. The sales playbook (Phase 05)
# WILL push the model toward these, so they are checked deterministically rather
# than forbidden in prose.
#
# "giảm"/"bớt" must be tied to price (a following số, "giá" or "học phí"): a bot
# that says "giúp con giảm áp lực" is not making a concession.
_CONCESSION_RE = re.compile(
    r"(giảm\s*(?:giá|học\s*phí|thêm|\d)|bớt\s*(?:giá|học\s*phí|\d)|"
    r"ưu\s*đãi\s*(?:riêng|đặc\s*biệt)|giá\s*(?:đặc\s*biệt|riêng)|"
    r"xin\s*(?:sếp|thêm\s*ưu\s*đãi)|trường\s*hợp\s*của\s*(?:anh|chị)|"
    r"linh\s*động\s*(?:giá|học\s*phí)|"
    # Paraphrases the `gia_cao` playbook actively pushes the model toward.
    r"mức\s*(?:tốt|ưu\s*đãi)\s*hơn|hỗ\s*trợ\s*thêm|tặng\s*thêm|"
    r"ưu\s*tiên\s*riêng|em\s*xin\s*cho\s*(?:anh|chị))",
    re.IGNORECASE,
)


def check_money(draft: str, facts: list[str]) -> list[str]:
    """Every money/percent token in the draft must be literally in the bound facts.

    A model-COMPUTED discount (5tr − 10% → "4tr5") is not literally in the Sheet,
    so it fails here without needing a rule about arithmetic.
    """
    allowed_money: set[int] = set()
    allowed_pct: set[int] = set()
    for text in facts:
        for tok in iter_money_tokens(text):
            (allowed_money if tok.kind == "money" else allowed_pct).add(tok.value)

    violations = []
    for tok in iter_money_tokens(draft):
        if tok.kind == "money" and tok.value not in allowed_money:
            violations.append(Violation(
                Kind.MONEY,
                f"số tiền không thuộc KB khóa đang nói: '{tok.raw}' ({tok.value})"))
        elif tok.kind == "pct" and tok.value not in allowed_pct:
            violations.append(Violation(
                Kind.PERCENT, f"phần trăm không có trong KB: '{tok.raw}'"))

    if _FREE_RE.search(draft) and not any(_FREE_RE.search(f) for f in facts):
        violations.append(Violation(
            Kind.FREE_CLAIM, "tuyên bố 'miễn phí' không có căn cứ trong KB"))
    return violations


def check_schedule(draft: str, facts: list[str]) -> list[str]:
    """Dates/times in the draft must appear in the bound course's facts."""
    allowed = [tok for text in facts for tok in iter_date_tokens(text)]
    return [
        Violation(Kind.SCHEDULE, f"ngày/giờ không khớp KB khóa đang nói: '{tok.raw}'")
        for tok in iter_date_tokens(draft)
        if not token_allowed(tok, allowed)
    ]


def check_concession(draft: str, facts: list[str]) -> list[str]:
    """A concession phrase is only allowed if the KB itself says it.

    Matching on the phrase's own words (not on the whole sentence) keeps a bot
    that correctly READS the `Ưu đãi` cell passing, while "để em xin ưu đãi riêng
    cho chị" — an offer the centre never made — fails.
    """
    joined = " ".join(facts).lower()
    return [
        Violation(Kind.CONCESSION, f"nhượng bộ giá không có trong ô Ưu đãi: '{m.group(0)}'")
        for m in _CONCESSION_RE.finditer(draft)
        if _normalize(m.group(0)) not in _normalize(joined)
    ]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()
