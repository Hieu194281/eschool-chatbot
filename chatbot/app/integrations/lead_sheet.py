"""Leads worksheet upsert — keyed by `channel_user_id` (red-team #9).

Critical fix: locate the target row by VALUE via `ws.find(...)` — NEVER by an
enumerate index. A staff mid-sheet row-delete desyncs `get_all_records()` index vs
physical row, so index-based upsert would overwrite a DIFFERENT lead's SĐT. `ws.find`
returns the true physical row.

The read-modify-write is guarded by a per-`channel_user_id` async lock, and the
blocking gspread call runs off the event loop. The worksheet is injected, so tests
drive an in-memory double implementing find/update/append_row/get_all_records.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

COLUMNS = [
    "channel_user_id", "ten", "sdt", "khoa_quan_tam", "nhu_cau", "do_nong",
    "sales_stage", "chat_link", "consent", "consent_at", "updated_at",
]
CHANNEL_USER_ID_COL = 1                 # column A
_LAST_COL_LETTER = "K"                   # 11 columns → A..K


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LeadSheet:
    def __init__(self, worksheet) -> None:
        self._ws = worksheet
        self._locks: dict = {}

    def _lock(self, key: str):
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    @staticmethod
    def _row_values(lead: dict, now: str) -> list:
        merged = {**lead, "updated_at": now}
        return [str(merged.get(col, "") or "") for col in COLUMNS]

    def _upsert_sync(self, lead: dict, now: str) -> str:
        # Locate by value; re-find happens here (immediately before write).
        cell = self._ws.find(lead["channel_user_id"], in_column=CHANNEL_USER_ID_COL)
        values = self._row_values(lead, now)
        if cell:
            self._ws.update(f"A{cell.row}:{_LAST_COL_LETTER}{cell.row}", [values])
            return "updated"
        self._ws.append_row(values)
        return "created"

    async def upsert_lead(self, lead: dict, now: str | None = None) -> str:
        async with self._lock(lead["channel_user_id"]):        # per-user (red-team #9)
            return await asyncio.to_thread(self._upsert_sync, lead, now or _now_iso())

    def _delete_sync(self, channel_user_id: str) -> bool:
        cell = self._ws.find(channel_user_id, in_column=CHANNEL_USER_ID_COL)
        if not cell:
            return False
        self._ws.delete_rows(cell.row)
        return True

    async def delete_lead(self, channel_user_id: str) -> bool:
        async with self._lock(channel_user_id):
            return await asyncio.to_thread(self._delete_sync, channel_user_id)

    def _purge_sync(self, cutoff: datetime) -> int:
        records = self._ws.get_all_records()
        doomed = []
        for idx, rec in enumerate(records, start=2):           # row 1 = header
            ts = rec.get("updated_at")
            if ts and _parse_iso(ts) is not None and _parse_iso(ts) < cutoff:
                doomed.append(idx)
        for row in reversed(doomed):                            # bottom-up (index-safe)
            self._ws.delete_rows(row)
        return len(doomed)

    async def purge_older_than(self, cutoff: datetime) -> int:
        return await asyncio.to_thread(self._purge_sync, cutoff)


def _parse_iso(value: str):
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


_lead_sheet_singleton = None


def get_lead_sheet() -> LeadSheet:
    global _lead_sheet_singleton
    if _lead_sheet_singleton is None:
        from ..config import get_settings
        from .sheets_client import open_worksheet

        settings = get_settings()
        ws = open_worksheet(settings.leads_sheet_id, "Leads")
        _lead_sheet_singleton = LeadSheet(ws)
    return _lead_sheet_singleton


def set_lead_sheet(instance: LeadSheet) -> None:
    global _lead_sheet_singleton
    _lead_sheet_singleton = instance
