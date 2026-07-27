"""Validate + split Sheet `Courses` rows into the in-context catalog + facts map.

Pure logic (no gspread / no langchain) so it is unit-testable standalone.

Golden-rule split (schema v2): PROSE_FIELDS are paraphrasable and embeddable;
VERBATIM_FIELDS are 9 staff-editable cells injected under the trust marker, kept
byte-identical in `facts_map`, never embedded.

Tiered sanitization — a dirty cell must not cost more than it has to (red-team
#13/#14). `hoc_phi` missing or dirty excludes the WHOLE course: never serve one
without an official price, nor a forged one. Any other dirty verbatim cell drops
only THAT line (+ alert) — a malformed `si_so` is no reason to stop selling.
Every verbatim cell is injected with a high-trust label, so `khai_giang` is as
much an injection vector as `hoc_phi`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .cell_sanitizer import (        # noqa: F401 — is_*_cell_safe re-exported
    collect_prose,
    collect_verbatim,
    is_prose_cell_safe,
    is_verbatim_cell_safe,
)
from .course_block_builder import build_course_block, build_index_line, join_labeled

REQUIRED_FIELDS = ("course_id", "ten_khoa", "hoc_phi")

# Injected verbatim under the trust marker. Order = order of the facts block.
VERBATIM_FIELDS = (
    ("hoc_phi", "Học phí"),
    ("uu_dai", "Ưu đãi"),
    ("khai_giang", "Khai giảng"),
    ("lich_hoc", "Lịch học"),
    ("thoi_luong", "Thời lượng"),
    ("si_so", "Sĩ số"),
    ("hinh_thuc", "Hình thức"),
    ("giao_vien_ten", "Giáo viên"),
    ("co_so", "Cơ sở"),
)

PROSE_FIELDS = (
    ("doi_tuong", "Đối tượng"), ("muc_tieu", "Mục tiêu"), ("lo_trinh", "Lộ trình"),
    ("chinh_sach", "Chính sách"), ("giao_vien_gioi_thieu", "Giới thiệu giáo viên"),
    ("ghi_chu", "Ghi chú"),
)

# Deprecated v1 columns kept readable so a not-yet-migrated row still serves.
# Read ONLY when the v2 column is empty. Sheet stays backward compatible: v2 only
# ADDS columns, so reverting the code needs no Sheet change.
FALLBACK_COLUMNS = {
    "giao_vien_gioi_thieu": "giao_vien",
    "khai_giang": "lich_khai_giang",
}

class KbSchemaError(Exception):
    """Required header columns missing from the sheet (whole-sheet fatal)."""


@dataclass
class ParsedDoc:
    page_content: str
    metadata: dict


@dataclass
class ParseResult:      # every map keyed by course_id — see plan §Đường tăng trưởng
    docs: list = field(default_factory=list)          # list[ParsedDoc]
    facts_map: dict = field(default_factory=dict)     # cid -> verbatim facts str
    course_index: dict = field(default_factory=dict)  # cid -> 1-line index entry
    course_blocks: dict = field(default_factory=dict) # cid -> full detail block
    course_meta: dict = field(default_factory=dict)   # cid -> {ten_khoa, tu_khoa}
    errors: list = field(default_factory=list)        # human-readable alerts


def _clean(value) -> str:
    return str(value).strip() if value is not None else ""


def _cell(row: dict, key: str) -> str:
    """Cell value, falling back to the deprecated v1 column when v2 is empty."""
    value = _clean(row.get(key))
    if not value and key in FALLBACK_COLUMNS:
        value = _clean(row.get(FALLBACK_COLUMNS[key]))
    return value


def _check_schema(rows: list[dict]) -> None:
    if not rows:
        return
    missing = [c for c in REQUIRED_FIELDS if c not in rows[0]]
    if missing:
        raise KbSchemaError(f"KB Sheet missing required columns: {missing}")


def parse_courses(rows: list[dict]) -> ParseResult:
    _check_schema(rows)
    result = ParseResult()
    seen_ids: set[str] = set()

    for idx, row in enumerate(rows, start=2):     # sheet row number (header = row 1)
        cid = _clean(row.get("course_id"))
        if not cid:
            if any(_clean(v) for v in row.values()):
                result.errors.append(f"Dòng {idx}: thiếu course_id (bỏ qua).")
            continue                              # silently skip fully-empty rows
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

        def cell(key, _row=row):
            return _cell(_row, key)

        verbatim = collect_verbatim(cell, VERBATIM_FIELDS, cid, result.errors)
        if verbatim is None or "hoc_phi" not in verbatim:
            continue

        ten_khoa = _clean(row.get("ten_khoa"))
        if not is_verbatim_cell_safe(ten_khoa):
            # `ten_khoa` heads the block AND the index line — a dirty one can
            # invent an entire course. Same blast radius as `hoc_phi`.
            result.errors.append(
                f"Khóa '{cid}': ô 'ten_khoa' chứa nội dung khả nghi — KHÔNG phục vụ khóa này."
            )
            continue

        prose = collect_prose(cell, PROSE_FIELDS, cid, result.errors)
        prose_text = join_labeled(prose, PROSE_FIELDS)
        facts_text = join_labeled(verbatim, VERBATIM_FIELDS)
        result.docs.append(ParsedDoc(
            page_content=f"Khóa: {ten_khoa}\n{prose_text}".strip(),
            metadata={"source": "course", "doc_id": f"course:{cid}",
                      "course_id": cid, "ten_khoa": ten_khoa},
        ))
        result.facts_map[cid] = facts_text
        result.course_index[cid] = build_index_line(
            cid, ten_khoa, prose.get("doi_tuong", ""), verbatim.get("hinh_thuc", "")
        )
        result.course_blocks[cid] = build_course_block(
            cid, ten_khoa, prose_text, facts_text
        )
        result.course_meta[cid] = {
            "ten_khoa": ten_khoa,
            "tu_khoa": _split_keywords(row.get("tu_khoa")),
        }

    return result


def _split_keywords(raw) -> list[str]:
    """`tu_khoa` → normalized alias list (guard course-mention matching, Phase 03).

    Aliases shorter than 4 chars and bare numbers are dropped here rather than at
    the guard: a staff-typed "anh" or "9" would otherwise bind every polite draft
    to one course, and the guard treats an alias hit as certain.
    """
    parts = (part.strip().lower() for part in _clean(raw).split(","))
    return [p for p in parts if len(p) >= 4 and not p.isdigit()]
