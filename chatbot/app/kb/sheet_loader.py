"""Fetch raw KB rows from the 3 Google Sheet tabs (Courses / Center / FAQ).

Three `get_all_records()` calls per sync, NOT one `values_batch_get`. Sync runs
every 5 minutes → 0.6 req/min against a 300 req/min quota, so "saving" two calls
buys nothing and would force hand-mapping header→dict — i.e. manufacturing the
exact column-drift risk `get_all_records()` already solves (plan review C5).

Only `Courses` is fatal when absent. A missing `Center`/`FAQ` tab degrades the
answer surface but must never take the service down.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..config import get_settings
from ..integrations.sheets_client import open_worksheet

logger = logging.getLogger(__name__)

COURSES_WORKSHEET = "Courses"
CENTER_WORKSHEET = "Center"
FAQ_WORKSHEET = "FAQ"


@dataclass
class KbRows:
    courses: list = field(default_factory=list)
    center: list = field(default_factory=list)
    faq: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def _fetch(sheet_id: str, title: str, errors: list, required: bool) -> list[dict]:
    from gspread.exceptions import WorksheetNotFound

    try:
        return open_worksheet(sheet_id, title).get_all_records()
    except WorksheetNotFound:
        if required:
            raise
        logger.warning("KB tab '%s' not found — serving without it", title)
        errors.append(f"Không tìm thấy tab '{title}' trong KB Sheet — bỏ qua phần này.")
        return []


def load_kb() -> KbRows:
    """All three tabs, header-keyed. Raises only when `Courses` is missing."""
    sheet_id = get_settings().kb_sheet_id
    result = KbRows()
    result.courses = _fetch(sheet_id, COURSES_WORKSHEET, result.errors, required=True)
    result.center = _fetch(sheet_id, CENTER_WORKSHEET, result.errors, required=False)
    result.faq = _fetch(sheet_id, FAQ_WORKSHEET, result.errors, required=False)
    return result
