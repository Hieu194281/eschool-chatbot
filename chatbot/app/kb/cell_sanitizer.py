"""Trust gates for Sheet cells that get injected into the system prompt.

Split out of `course_parser.py` (200-LOC ceiling) and kept free of any schema
knowledge — the field lists are passed in — so `center_faq_parser` can reuse the
same gates without importing the course parser.

Two tiers, and the difference is deliberate:
- VERBATIM cells are quoted word-for-word under a trust marker and are single
  values, so a newline in one can only be an attempt to fake block structure.
- PROSE cells are multi-line by nature (a real `lo_trinh` is a syllabus), so
  newlines are allowed and only forged structure and instructions are rejected.

Everything is matched against FOLDED text (accents and repeat whitespace removed).
Dropping diacritics is the cheapest bypass there is: with accented patterns,
"Bo qua cac nguyen tac phia tren" walks through untouched.
"""

from __future__ import annotations

import re

from .course_block_builder import BLOCK_DELIMITER_RE, FOLDED_TRUST_MARKER, fold

# Patterns are written UNACCENTED because they run against folded text.
#
# "quy tac"/"nguyen tac" appear only as the object of an imperative: a
# `chinh_sach` cell reading "Chính sách & quy tắc lớp học" is ordinary content,
# and quarantining it would teach staff to ignore the alerts.
_INJECTION_RE = re.compile(
    r"(?:```|</?\w+>|"
    r"ignore|disregard|override|instruction|prompt|"
    r"(?:system|assistant|user|he\s*thong|tro\s*ly)\s*:|"
    r"(?:bo\s*qua|phot\s*lo|khong\s*theo|vi\s*pham)\s*(?:cac\s*|moi\s*)?"
    r"(?:quy\s*tac|nguyen\s*tac|huong\s*dan|chi\s*dan)|"
    r"you\s+are|ban\s+la|hay\s+(?:coi|bo|giam))",
    re.IGNORECASE,
)


def is_prose_cell_safe(raw: str) -> bool:
    """Gate for cells that reach the prompt but may legitimately be multi-line."""
    folded = fold(raw)
    if FOLDED_TRUST_MARKER in folded or BLOCK_DELIMITER_RE.search(folded):
        return False
    return not _INJECTION_RE.search(folded)


def is_verbatim_cell_safe(raw: str) -> bool:
    """Stricter gate for the 9 verbatim cells: the above, plus no newline."""
    if "\n" in raw or "\r" in raw:
        return False
    return is_prose_cell_safe(raw)


def collect_verbatim(cell, fields: tuple, cid: str, errors: list) -> dict | None:
    """Sanitized verbatim cells, or None when the course must be excluded.

    Tiered on purpose: a dirty `hoc_phi` costs the whole course (never serve a
    missing or forged official price), any other dirty cell costs only its own
    line — a malformed `si_so` is no reason to stop selling.
    """
    values, dropped = {}, []
    for key, _label in fields:
        raw = cell(key)
        if not raw:
            continue
        if is_verbatim_cell_safe(raw):
            values[key] = raw
        elif key == "hoc_phi":
            errors.append(
                f"Khóa '{cid}': ô 'hoc_phi' chứa nội dung khả nghi "
                f"(xuống dòng / trust-marker / lệnh) — cách ly, KHÔNG phục vụ khóa này."
            )
            return None
        else:
            dropped.append(key)
    if dropped:
        errors.append(
            f"Khóa '{cid}': ô {dropped} khả nghi — bỏ các dòng đó khỏi số liệu, "
            f"khóa vẫn phục vụ."
        )
    return values


def collect_prose(cell, fields: tuple, cid: str, errors: list) -> dict:
    """Sanitized prose cells. A dirty one drops its own field, never the course."""
    values, dropped = {}, []
    for key, _label in fields:
        raw = cell(key)
        if not raw:
            continue
        if is_prose_cell_safe(raw):
            values[key] = raw
        else:
            dropped.append(key)
    if dropped:
        errors.append(
            f"Khóa '{cid}': ô mô tả {dropped} chứa dấu hiệu giả cấu trúc/chỉ thị — "
            f"bỏ các ô đó, khóa vẫn phục vụ."
        )
    return values
