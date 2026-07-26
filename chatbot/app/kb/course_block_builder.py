"""Build the in-context catalog strings for one course: Index line + Detail block.

Split out of `course_parser.py` to keep both files under the 200-LOC ceiling.

Both outputs are keyed by `course_id` upstream. The Detail block is the hinge for
switching to `CATALOG_MODE=index` + `get_course_detail(cid)` above ~30 courses
(plan §Đường tăng trưởng) — it must stay independently addressable, never
pre-joined into one blob.
"""

from __future__ import annotations

import re
import unicodedata

TRUST_MARKER = "SỐ LIỆU CHÍNH THỨC"

# Structural delimiters the block builder emits. A cell containing one could fake
# a whole extra course, so they are matched as patterns, not literals.
BLOCK_DELIMITER_RE = re.compile(r"---\s*id\s*=|\[\s*so\s*lieu", re.IGNORECASE)


def fold(text: str) -> str:
    """Lowercase, strip diacritics, collapse whitespace.

    The trust marker used to be compared as an exact substring, so
    `"SO LIEU CHINH THUC"` and `"SỐ  LIỆU  CHÍNH  THỨC"` both slipped past. Fold
    both sides before comparing and neither does.
    """
    lowered = (text or "").lower().replace("đ", "d")
    stripped = "".join(c for c in unicodedata.normalize("NFD", lowered)
                       if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped).strip()


FOLDED_TRUST_MARKER = fold(TRUST_MARKER)

# `doi_tuong` is free prose; the Index line must stay ~25 tokens so 15+ of them
# can sit in the system prompt permanently.
_INDEX_DOI_TUONG_MAX = 80


def join_labeled(values: dict, fields: tuple) -> str:
    """`Nhãn: giá trị` lines, in declaration order, skipping empty cells."""
    return "\n".join(
        f"{label}: {values[key]}" for key, label in fields if values.get(key)
    )


def build_index_line(cid: str, ten_khoa: str, doi_tuong: str, hinh_thuc: str) -> str:
    """One always-on catalog line: `id  tên — đối tượng — hình thức`."""
    parts = [f"{cid}  {ten_khoa}"]
    if doi_tuong:
        parts.append(_truncate(doi_tuong, _INDEX_DOI_TUONG_MAX))
    if hinh_thuc:
        parts.append(hinh_thuc)
    return " — ".join(parts)


def build_course_block(cid: str, ten_khoa: str, prose: str, facts: str) -> str:
    """Detail block: prose (paraphrasable) then facts under the trust marker.

    The marker is emitted by CODE only; any cell that contains it is quarantined
    upstream, so a forged marker cannot reach this string.
    """
    lines = [f'--- id={cid} "{ten_khoa}" ---']
    if prose:
        lines.append(prose)
    if facts:
        lines.append(f"[{TRUST_MARKER} — id={cid}]")
        lines.append(facts)
    return "\n".join(lines)


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
