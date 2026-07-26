#!/usr/bin/env python3
"""Pre-deploy check: does the live KB Sheet actually have the v2 tabs + columns?

Schema v2 only ADDS columns, so a stale Sheet does not crash the service — it just
silently serves thinner answers. This script makes that silence loud BEFORE deploy.

Usage (from the `chatbot/` directory, env loaded as in production):
    python scripts/verify-sheet-schema.py

Exit codes: 0 = ready · 1 = fatal (missing required tab/column) · 2 = warnings only.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.kb.center_faq_parser import (  # noqa: E402
    CENTER_COLUMNS,
    FAQ_COLUMNS,
    REQUIRED_VERBATIM_TOPICS,
)
from app.kb.course_parser import PROSE_FIELDS, REQUIRED_FIELDS, VERBATIM_FIELDS  # noqa: E402
from app.kb.sheet_loader import load_kb  # noqa: E402

OPTIONAL_COURSE_COLUMNS = tuple(
    key for key, _ in VERBATIM_FIELDS + PROSE_FIELDS if key not in REQUIRED_FIELDS
) + ("tu_khoa",)


def _columns(rows: list[dict]) -> set:
    return set(rows[0]) if rows else set()


def _check_courses(rows: list[dict], fatal: list, warn: list) -> None:
    if not rows:
        fatal.append("Tab 'Courses' rỗng hoặc không đọc được.")
        return
    columns = _columns(rows)
    missing_required = [c for c in REQUIRED_FIELDS if c not in columns]
    if missing_required:
        fatal.append(f"Tab 'Courses' thiếu cột BẮT BUỘC: {missing_required}")
    missing_optional = [c for c in OPTIONAL_COURSE_COLUMNS if c not in columns]
    if missing_optional:
        warn.append(
            f"Tab 'Courses' thiếu cột v2 (khóa vẫn phục vụ, mất thông tin): {missing_optional}"
        )
    print(f"  Courses: {len(rows)} dòng, {len(columns)} cột")


def _check_optional_tab(rows: list[dict], columns: tuple, tab: str, warn: list) -> bool:
    if not rows:
        warn.append(f"Tab '{tab}' trống hoặc không tồn tại — mất toàn bộ nội dung {tab}.")
        return False
    missing = [c for c in columns if c not in _columns(rows)]
    if missing:
        warn.append(f"Tab '{tab}' thiếu cột {missing} — cả tab sẽ bị bỏ qua khi sync.")
        return False
    print(f"  {tab}: {len(rows)} dòng")
    return True


def _check_verbatim_topics(center_rows: list[dict], warn: list) -> None:
    present = {
        str(r.get("chu_de", "")).strip().lower()
        for r in center_rows
        if str(r.get("loai", "")).strip().lower() == "verbatim"
    }
    missing = [t for t in REQUIRED_VERBATIM_TOPICS if t.lower() not in present]
    if missing:
        warn.append(f"Tab 'Center' thiếu dòng loai=verbatim bắt buộc: {missing}")

    bad_loai = sorted({
        str(r.get("loai", "")).strip()
        for r in center_rows
        if str(r.get("loai", "")).strip().lower() not in ("always", "verbatim", "embed")
        and any(str(v).strip() for v in r.values())
    })
    if bad_loai:
        warn.append(f"Tab 'Center' có giá trị loai không hợp lệ: {bad_loai}")


def _check_leads_sheet(fatal: list, warn: list) -> None:
    """The 6 elicitation columns were APPENDED to `COLUMNS` — the live sheet's
    header row is not migrated by code. Un-headered PII columns also break
    `get_all_records()`, which the retention purge depends on.
    """
    from app.config import get_settings
    from app.integrations.lead_sheet import COLUMNS
    from app.integrations.sheets_client import open_worksheet

    try:
        header = open_worksheet(get_settings().leads_sheet_id, "Leads").row_values(1)
    except Exception as exc:                       # noqa: BLE001
        warn.append(f"Không đọc được tab 'Leads': {exc}")
        return

    missing = [c for c in COLUMNS if c not in header]
    if missing:
        fatal.append(
            f"Tab 'Leads' thiếu header {missing} — thêm ĐÚNG THỨ TỰ vào hàng 1 "
            f"trước khi deploy (code ghi cả dải A..{_col(len(COLUMNS))})."
        )
    elif header[:len(COLUMNS)] != COLUMNS:
        fatal.append(
            f"Tab 'Leads' có đủ cột nhưng SAI THỨ TỰ. Đúng phải là: {COLUMNS}"
        )
    else:
        print(f"  Leads: header đủ {len(COLUMNS)} cột")


def _col(index: int) -> str:
    from app.integrations.lead_sheet import _col_letter

    return _col_letter(index)


def main() -> int:
    fatal: list[str] = []
    warn: list[str] = []

    print("Đang đọc KB Sheet…")
    try:
        rows = load_kb()
    except Exception as exc:                       # noqa: BLE001 — surface any auth/tab error
        print(f"FATAL: không đọc được KB Sheet: {exc}")
        return 1

    warn.extend(rows.errors)
    _check_courses(rows.courses, fatal, warn)
    if _check_optional_tab(rows.center, CENTER_COLUMNS, "Center", warn):
        _check_verbatim_topics(rows.center, warn)
    _check_optional_tab(rows.faq, FAQ_COLUMNS, "FAQ", warn)
    _check_leads_sheet(fatal, warn)

    for line in fatal:
        print(f"FATAL: {line}")
    for line in warn:
        print(f"WARN : {line}")

    if fatal:
        print("\n=> CHƯA deploy được: sửa Sheet trước.")
        return 1
    if warn:
        print("\n=> Deploy được, nhưng Sheet chưa đủ schema v2 (xem WARN).")
        return 2
    print("\n=> Sheet đúng schema v2.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
