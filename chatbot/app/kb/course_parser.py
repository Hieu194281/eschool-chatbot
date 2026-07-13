"""Validate + split Sheet rows into (documents, pricing_map, course_meta, errors).

Pure logic (no gspread / no langchain) so it is unit-testable standalone.

Golden-rule split:
- DESCRIPTIVE fields  → embedded (RAG) as one Document per course.
- hoc_phi / uu_dai    → STRUCTURED, kept verbatim in `pricing_map`, NEVER embedded.

Two security gates run here (red-team #13, #14):
- Partial-row validation: a row with a `course_id` but empty/whitespace required
  field (esp. `hoc_phi`) is half-edited → excluded + alerted (never served with a
  missing official price).
- Pricing-cell sanitization: `hoc_phi`/`uu_dai` are staff/attacker-editable free
  text injected into the LLM prompt. A cell containing a newline, the trust-marker
  string, or an instruction-like pattern is quarantined → the whole course is
  excluded from pricing (and from serving) until fixed, so a forged
  "SỐ LIỆU CHÍNH THỨC" marker can't be smuggled in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Columns embedded for RAG (descriptive only — pricing excluded).
DESCRIPTIVE_FIELDS = (
    ("ten_khoa", "Khóa"),
    ("doi_tuong", "Đối tượng"),
    ("muc_tieu", "Mục tiêu"),
    ("lo_trinh", "Lộ trình"),
    ("lich_khai_giang", "Lịch khai giảng"),
    ("giao_vien", "Giáo viên"),
    ("faq", "FAQ"),
    ("chinh_sach", "Chính sách"),
)
REQUIRED_FIELDS = ("course_id", "ten_khoa", "hoc_phi")
PRICING_FIELDS = ("hoc_phi", "uu_dai")

TRUST_MARKER = "SỐ LIỆU CHÍNH THỨC"

# Instruction-like / injection patterns forbidden inside a pricing cell.
_INJECTION_RE = re.compile(
    r"(?:```|</?\w+>|"
    r"ignore|disregard|override|system\s*:|assistant\s*:|user\s*:|"
    r"bỏ\s*qua|phớt\s*lờ|quy\s*tắc|nguyên\s*tắc|instruction|prompt|"
    r"you\s+are|bạn\s+là|hãy\s+(?:coi|bỏ))",
    re.IGNORECASE,
)


class KbSchemaError(Exception):
    """Required header columns missing from the sheet (whole-sheet fatal)."""


@dataclass
class ParsedDoc:
    page_content: str
    metadata: dict


@dataclass
class ParseResult:
    docs: list = field(default_factory=list)                 # list[ParsedDoc]
    pricing_map: dict = field(default_factory=dict)          # course_id -> verbatim str
    course_meta: dict = field(default_factory=dict)          # course_id -> {ten_khoa}
    errors: list = field(default_factory=list)               # human-readable alerts


def _clean(value) -> str:
    return str(value).strip() if value is not None else ""


def _is_pricing_cell_safe(raw: str) -> bool:
    if "\n" in raw or "\r" in raw:
        return False
    if TRUST_MARKER.lower() in raw.lower():
        return False
    if _INJECTION_RE.search(raw):
        return False
    return True


def _check_schema(rows: list[dict]) -> None:
    if not rows:
        return
    keys = {k for k in rows[0].keys()}
    missing = [c for c in REQUIRED_FIELDS if c not in keys]
    if missing:
        raise KbSchemaError(f"KB Sheet missing required columns: {missing}")


def parse_courses(rows: list[dict]) -> ParseResult:
    _check_schema(rows)
    result = ParseResult()
    seen_ids: set[str] = set()

    for idx, row in enumerate(rows, start=2):        # sheet row number (header = row 1)
        cid = _clean(row.get("course_id"))
        if not cid:
            if any(_clean(v) for v in row.values()):
                result.errors.append(f"Dòng {idx}: thiếu course_id (bỏ qua).")
            continue                                  # silently skip fully-empty rows
        if cid in seen_ids:
            result.errors.append(f"Dòng {idx}: course_id trùng '{cid}' (bỏ qua).")
            continue
        seen_ids.add(cid)

        missing = [f for f in REQUIRED_FIELDS if not _clean(row.get(f))]
        if missing:
            result.errors.append(
                f"Khóa '{cid}': thiếu trường bắt buộc {missing} — "
                f"KHÔNG phục vụ khóa này (dòng nửa vời)."
            )
            continue

        bad_cell = next(
            (f for f in PRICING_FIELDS
             if _clean(row.get(f)) and not _is_pricing_cell_safe(_clean(row.get(f)))),
            None,
        )
        if bad_cell:
            result.errors.append(
                f"Khóa '{cid}': ô '{bad_cell}' chứa ký tự/nội dung khả nghi "
                f"(xuống dòng / trust-marker / lệnh) — cách ly, KHÔNG phục vụ."
            )
            continue

        ten_khoa = _clean(row.get("ten_khoa"))
        parts = []
        for key, label in DESCRIPTIVE_FIELDS:
            val = _clean(row.get(key))
            if val:
                parts.append(f"{label}: {val}")
        result.docs.append(
            ParsedDoc(page_content="\n".join(parts), metadata={"course_id": cid, "ten_khoa": ten_khoa})
        )

        hoc_phi = _clean(row.get("hoc_phi"))
        uu_dai = _clean(row.get("uu_dai"))
        pricing = f"Học phí: {hoc_phi}"
        if uu_dai:
            pricing += f"\nƯu đãi: {uu_dai}"
        result.pricing_map[cid] = pricing
        result.course_meta[cid] = {"ten_khoa": ten_khoa}

    return result
