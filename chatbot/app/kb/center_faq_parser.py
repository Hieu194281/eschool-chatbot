"""Parse the `Center` + `FAQ` tabs into always-on text, verbatim map and documents.

Pure logic (no gspread / no langchain) so it is unit-testable standalone.

`Center.loai` routes each row to one of three destinations:
- `always`   → concatenated into `always_text`, injected into every system prompt
               (address / hours / procedures — the centre-level questions that used
               to force a handoff).
- `verbatim` → `verbatim_map[chu_de]`, quoted word-for-word by the sales layer
               (Phase 04/05 needs `Trả góp`, `Test đầu vào`, `Cam kết gọi lại`).
- `embed`    → a Document in the vector store.

Every Document carries a stable `doc_id`. Without it `tool_exec._merge_hits`
dedupes on `course_id`, and centre-wide FAQ rows all share `course_id=""` — many
distinct hits would silently collapse into one (plan review C1).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .course_parser import ParsedDoc, is_prose_cell_safe, is_verbatim_cell_safe

CENTER_TYPES = ("always", "verbatim", "embed")
CENTER_COLUMNS = ("chu_de", "noi_dung", "loai")
FAQ_COLUMNS = ("cau_hoi", "tra_loi")

# Quoted word-for-word by the sales layer; missing ones are a content gap, not a bug.
REQUIRED_VERBATIM_TOPICS = ("Trả góp", "Test đầu vào", "Cam kết gọi lại")


@dataclass
class CenterFaqResult:
    always_text: str = ""
    verbatim_map: dict = field(default_factory=dict)   # chu_de -> verbatim str
    docs: list = field(default_factory=list)           # list[ParsedDoc]
    errors: list = field(default_factory=list)


def _clean(value) -> str:
    return str(value).strip() if value is not None else ""


def _has_columns(rows: list[dict], columns: tuple, tab: str, errors: list) -> bool:
    """A malformed optional tab degrades that tab only — never the whole sync."""
    if not rows:
        return False
    missing = [c for c in columns if c not in rows[0]]
    if missing:
        errors.append(f"Tab '{tab}': thiếu cột {missing} — bỏ qua toàn bộ tab.")
        return False
    return True


def parse_center_faq(center_rows: list[dict], faq_rows: list[dict]) -> CenterFaqResult:
    result = CenterFaqResult()
    always_parts: list[str] = []

    if _has_columns(center_rows, CENTER_COLUMNS, "Center", result.errors):
        for idx, row in enumerate(center_rows, start=2):
            _parse_center_row(row, idx, always_parts, result)

    if _has_columns(faq_rows, FAQ_COLUMNS, "FAQ", result.errors):
        for idx, row in enumerate(faq_rows, start=2):
            _parse_faq_row(row, idx, result)

    result.always_text = "\n".join(always_parts)
    _warn_missing_topics(result)
    return result


def _parse_center_row(row: dict, idx: int, always_parts: list, result: CenterFaqResult) -> None:
    chu_de = _clean(row.get("chu_de"))
    noi_dung = _clean(row.get("noi_dung"))
    loai = _clean(row.get("loai")).lower()
    if not chu_de and not noi_dung:
        return                                     # fully-empty row
    if loai not in CENTER_TYPES:
        result.errors.append(
            f"Center dòng {idx} ('{chu_de}'): loai='{loai}' không hợp lệ "
            f"(chỉ nhận {list(CENTER_TYPES)}) — bỏ qua dòng."
        )
        return
    if not noi_dung:
        result.errors.append(f"Center dòng {idx} ('{chu_de}'): thiếu noi_dung — bỏ qua dòng.")
        return

    if loai == "always":
        # Lands ABOVE the catalog in the prompt — the highest-trust position there
        # is. Multi-line centre info is legitimate, forged structure is not.
        if not is_prose_cell_safe(noi_dung):
            result.errors.append(
                f"Center dòng {idx} ('{chu_de}'): nội dung always chứa dấu hiệu "
                f"giả cấu trúc/chỉ thị — cách ly, KHÔNG đưa vào prompt."
            )
            return
        always_parts.append(f"{chu_de}: {noi_dung}" if chu_de else noi_dung)
    elif loai == "verbatim":
        # Injected under a high-trust label just like course facts → same gate.
        if not is_verbatim_cell_safe(noi_dung):
            result.errors.append(
                f"Center dòng {idx} ('{chu_de}'): nội dung verbatim khả nghi "
                f"(xuống dòng / trust-marker / lệnh) — cách ly, KHÔNG dùng."
            )
            return
        result.verbatim_map[chu_de] = noi_dung
    else:                                          # embed
        tu_khoa = _clean(row.get("tu_khoa"))
        result.docs.append(ParsedDoc(
            page_content=_with_keywords(f"{chu_de}\n{noi_dung}", tu_khoa),
            metadata={"source": "center", "doc_id": _doc_id("center", chu_de, noi_dung),
                      "course_id": "", "ten_khoa": ""},
        ))


def _parse_faq_row(row: dict, idx: int, result: CenterFaqResult) -> None:
    cau_hoi = _clean(row.get("cau_hoi"))
    tra_loi = _clean(row.get("tra_loi"))
    if not cau_hoi and not tra_loi:
        return
    if not cau_hoi or not tra_loi:
        result.errors.append(f"FAQ dòng {idx}: thiếu câu hỏi hoặc trả lời — bỏ qua dòng.")
        return
    result.docs.append(ParsedDoc(
        page_content=_with_keywords(f"Q: {cau_hoi}\nA: {tra_loi}", _clean(row.get("tu_khoa"))),
        metadata={"source": "faq", "doc_id": _doc_id("faq", cau_hoi, tra_loi),
                  "course_id": _clean(row.get("course_id")), "ten_khoa": ""},
    ))


def _doc_id(source: str, *parts: str) -> str:
    """Content-derived id: unique per row AND stable when rows move.

    A row-index id (`faq:7`) collides across a sync that inserted a row above —
    checkpointed `retrieved` entries would then dedupe against different content.
    Two rows with the same `chu_de` would collide on a title-based id.
    """
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return f"{source}:{digest[:10]}"


def _with_keywords(text: str, tu_khoa: str) -> str:
    """Aliases ride in `page_content` so unaccented/abbreviated queries still match."""
    return f"{text}\nTừ khóa: {tu_khoa}" if tu_khoa else text


def _warn_missing_topics(result: CenterFaqResult) -> None:
    present = {topic.lower() for topic in result.verbatim_map}
    missing = [t for t in REQUIRED_VERBATIM_TOPICS if t.lower() not in present]
    if missing:
        result.errors.append(
            f"Tab 'Center': thiếu dòng verbatim bắt buộc {missing} — "
            f"tầng sales sẽ không trích dẫn được các chủ đề này."
        )
