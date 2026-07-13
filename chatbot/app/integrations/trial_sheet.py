"""Trials worksheet — append-only booking rows (Calendar is YAGNI for Pha 1)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

TRIAL_COLUMNS = ["channel_user_id", "sdt", "khoa", "slot", "created_at"]


class TrialSheet:
    def __init__(self, worksheet) -> None:
        self._ws = worksheet

    def _append_sync(self, trial: dict, now: str) -> None:
        merged = {**trial, "created_at": now}
        self._ws.append_row([str(merged.get(col, "") or "") for col in TRIAL_COLUMNS])

    async def append_trial(self, trial: dict, now: str | None = None) -> None:
        now = now or datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(self._append_sync, trial, now)


_trial_sheet_singleton = None


def get_trial_sheet() -> TrialSheet:
    global _trial_sheet_singleton
    if _trial_sheet_singleton is None:
        from ..config import get_settings
        from .sheets_client import open_worksheet

        settings = get_settings()
        ws = open_worksheet(settings.leads_sheet_id, "Trials")
        _trial_sheet_singleton = TrialSheet(ws)
    return _trial_sheet_singleton


def set_trial_sheet(instance) -> None:
    global _trial_sheet_singleton
    _trial_sheet_singleton = instance
