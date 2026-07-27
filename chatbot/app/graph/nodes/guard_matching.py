"""Resolve WHICH course(s) a draft reply is talking about — the guard's binding step.

Every number the guard checks is bound to a course. Getting this wrong in either
direction is expensive: too loose and a right-number-wrong-course price slips
through; too tight and the bot honest-fallbacks on valid answers.

Four tiers, first tier with a hit wins:
  1. `course_id` appears literally     → certain
  2. `ten_khoa` is a substring          → certain
  3. an alias from `tu_khoa` matches    → certain
  4. word overlap above threshold       → accepted ONLY if exactly one course qualifies

Tiers 1-3 are exact containment, so several courses matching just means the draft
really did mention several — not ambiguity.

Tier 4 exists because a draft may paraphrase ("khóa mất gốc lớp 7"). It is also
where collisions live: with the WHOLE catalog in scope, "Toán 7 Mất Gốc" and
"Toán 9 Mất Gốc" share 3 of 4 words. Shared subject/level words are therefore
stripped before scoring, the bar is high, and ≥2 survivors means AMBIGUOUS →
caller fails closed. That risk grows with catalog size, which is why it is tight
now, at 15 courses, rather than later.
"""

from __future__ import annotations

import re

_WORD_RE = re.compile(r"[\w]+", re.UNICODE)

# Words shared across course names — they carry no discriminating signal at tier 4.
# Digits are NOT here: "7" vs "9" is exactly what separates two "Mất Gốc" courses.
_STOPWORDS = {
    "toán", "toan", "văn", "van", "anh", "tiếng", "tieng", "lý", "ly", "hóa", "hoa",
    "sinh", "sử", "su", "địa", "dia", "lớp", "lop", "khóa", "khoa", "lớp", "cấp",
    "cap", "trung", "tâm", "tam", "học", "hoc", "chương", "chuong", "trình", "trinh",
    "và", "va", "cho", "của", "cua",
}

# High bar: tier 4 is a guess, and a wrong guess here mis-binds a price.
_OVERLAP_THRESHOLD = 0.8
_MIN_FUZZY_WORDS = 2


def _without_numeric_tokens(text: str) -> str:
    """Remove money/date SPANS only — using the same tokenizers the guard uses.

    "9.000.000" must not donate a "9" that scores a perfect match against a course
    named "Lớp 9". But a bare grade number is a real name token: stripping every
    digit would make "khóa mất gốc lớp 7" stop resolving to "Toán 7 Mất Gốc",
    which is the paraphrase tier 4 exists for.
    """
    from ...common.vn_dates import iter_date_tokens
    from ...common.vn_numerals import iter_money_tokens

    for token in list(iter_money_tokens(text)) + list(iter_date_tokens(text)):
        text = text.replace(token.raw, " ")
    return text


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _significant_words(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(_normalize(text)) if w not in _STOPWORDS}


def _id_in_draft(course_id: str, draft: str) -> bool:
    if not course_id:
        return False
    return re.search(rf"(?<![\w-]){re.escape(course_id.lower())}(?![\w-])", draft) is not None


# An alias is staff-editable and controls guard binding. A 3-letter one like
# "anh" appears in almost every polite Vietnamese sentence and would bind the
# entire catalog's drafts to one course.
MIN_ALIAS_LENGTH = 4


def _whole_word_in(needle: str, text: str) -> bool:
    """Containment on word boundaries — "Anh Văn" must not match "Anh Văn phòng"."""
    return bool(needle) and bool(
        re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", text))


def _alias_in_draft(aliases, draft: str) -> bool:
    return any(
        _whole_word_in(_normalize(a), draft)
        for a in (aliases or []) if len(_normalize(a)) >= MIN_ALIAS_LENGTH
    )


def _spans(needle: str, text: str) -> list[tuple]:
    """Occurrences of `needle`, using the SAME boundary rule as `_whole_word_in`.

    A raw-substring scan here would count a boundary-invalid occurrence as a
    standalone mention, so the matcher and the span counter would disagree about
    what a match even is.
    """
    if not needle:
        return []
    pattern = rf"(?<!\w){re.escape(needle)}(?!\w)"
    return [(m.start(), m.end()) for m in re.finditer(pattern, text)]


def _drop_shadowed(hits: list[dict], text: str) -> list[dict]:
    """Drop a course only where its name appears SOLELY inside a longer match.

    Naming "Toán 9 Nâng Cao" also contains "Toán 9", so both bind and the pair
    becomes un-attributable. But a draft that names BOTH separately — "Toán 9 và
    Toán 9 Nâng Cao" — genuinely means both, and dropping the shorter one there
    would silently re-open the wrong-price hole. Hence spans, not substrings.
    """
    matched = [(c, _spans(_normalize(c.get("ten_khoa", "")), text)) for c in hits]
    kept = []
    for course, own in matched:
        covered = [
            span for span in own
            if any(span != other and other[0] <= span[0] and span[1] <= other[1]
                   for _, others in matched for other in others)
        ]
        if not own or len(covered) < len(own):
            kept.append(course)          # at least one standalone mention survives
    return kept


def _overlap_ratio(course: dict, draft_words: set[str]) -> float:
    words = _significant_words(course.get("ten_khoa", ""))
    if len(words) < _MIN_FUZZY_WORDS:
        return 0.0          # a one-token name is too thin to guess from
    return len(words & draft_words) / len(words)


def resolve_named(draft: str, courses: list[dict]) -> tuple[list[dict], bool]:
    """Return `(named_courses, ambiguous)`.

    `ambiguous=True` means the draft plausibly refers to more than one course and
    the guard must NOT pick one — the caller blocks instead.
    """
    text = _normalize(draft)
    if not text or not courses:
        return [], False

    # UNION of tiers 1-3, not the first tier that hits. Returning early let a draft
    # naming one course by id and another by alias resolve to a single course — and
    # the multi-course block, which works by COUNTING, then never fired.
    certain = [
        c for c in courses
        if _id_in_draft(c.get("course_id", ""), text)
        or _whole_word_in(_normalize(c.get("ten_khoa", "")), text)
        or _alias_in_draft(c.get("tu_khoa"), text)
    ]
    if certain:
        return _drop_shadowed(certain, text), False

    # Money/date spans are stripped first: "9.000.000" would otherwise donate a
    # "9" that scores a perfect overlap against a course named "Lớp 9", laundering
    # an unattributed price onto a course nobody mentioned.
    draft_words = _significant_words(_without_numeric_tokens(text))
    fuzzy = [c for c in courses if _overlap_ratio(c, draft_words) >= _OVERLAP_THRESHOLD]
    if len(fuzzy) == 1:
        return fuzzy, False
    return [], len(fuzzy) > 1
