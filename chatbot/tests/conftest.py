"""Shared test fixtures: in-memory gspread double, in-memory handoff store, and a
test-settings environment. External boundaries (Sheets/DB/HTTP) are doubled; core
logic runs for real.
"""

import os
import re
from collections import namedtuple

import pytest

# Test env BEFORE any get_settings() call (lru_cached).
os.environ.setdefault("PAGE_ACCESS_TOKEN", "test-page-token")
os.environ.setdefault("APP_SECRET", "test-app-secret")
os.environ.setdefault("VERIFY_TOKEN", "test-verify-token")
os.environ.setdefault("GOOGLE_API_KEY", "test-google-key")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-bot-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "123456")
os.environ.setdefault("SHADOW_MODE", "true")

Cell = namedtuple("Cell", ["row", "col"])


class FakeWorksheet:
    """Minimal in-memory gspread worksheet: find/update/append_row/get_all_records/
    delete_rows. `find` matches by VALUE in a column and returns the PHYSICAL row."""

    def __init__(self, header, rows=None):
        self.header = list(header)
        self.rows = [list(r) for r in (rows or [])]

    def find(self, query, in_column=1):
        col = in_column - 1
        for i, row in enumerate(self.rows):
            if col < len(row) and str(row[col]) == str(query):
                return Cell(row=i + 2, col=in_column)     # header occupies row 1
        return None

    def update(self, rng, values):
        start_row = int(re.search(r"[A-Z]+(\d+)", rng).group(1))
        self.rows[start_row - 2] = list(values[0])

    def append_row(self, values):
        self.rows.append(list(values))

    def get_all_records(self):
        return [dict(zip(self.header, row)) for row in self.rows]

    def delete_rows(self, row):
        del self.rows[row - 2]

    def row_values(self, row):
        return self.rows[row - 2]


class FakeHandoffStore:
    """In-memory handoff store matching PostgresHandoffStore's async surface."""

    def __init__(self):
        self.rows = {}       # thread_id -> {active, reason, last_user_ts, last_human_ts}

    async def touch_user_and_get(self, thread_id):
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        prev = self.rows.get(thread_id, {})
        result = {
            "prev_active": prev.get("active", False),
            "prev_user_ts": prev.get("last_user_ts"),
            "prev_human_ts": prev.get("last_human_ts"),
            "now_ts": now,
        }
        row = dict(prev)
        row["last_user_ts"] = now
        row.setdefault("active", False)
        self.rows[thread_id] = row
        return result

    async def is_active(self, thread_id):
        return bool(self.rows.get(thread_id, {}).get("active"))

    async def set_active(self, thread_id, reason):
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        row = self.rows.setdefault(thread_id, {})
        row.update({"active": True, "reason": reason, "last_human_ts": now, "since": now})

    async def clear(self, thread_id):
        if thread_id in self.rows:
            self.rows[thread_id]["active"] = False


@pytest.fixture
def fake_worksheet():
    from app.integrations.lead_sheet import COLUMNS

    return FakeWorksheet(COLUMNS)


@pytest.fixture
def fake_handoff_store():
    return FakeHandoffStore()
