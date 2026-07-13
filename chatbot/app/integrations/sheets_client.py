"""Shared gspread client (DRY — used by KB sync in Phase 02 and leads/trials in
Phase 05). Auth from the service-account JSON path in settings, with gspread's
`BackOffHTTPClient` so transient 429/5xx are auto-retried.
"""

from functools import lru_cache

from ..config import get_settings


@lru_cache
def get_gspread_client():
    """Cached authorized gspread client (least-privilege service account)."""
    import gspread
    from gspread.http_client import BackOffHTTPClient

    settings = get_settings()
    return gspread.service_account(
        filename=settings.google_sa_json_path,
        http_client=BackOffHTTPClient,
    )


def open_worksheet(sheet_id: str, title: str):
    """Open a worksheet by spreadsheet id + tab title."""
    return get_gspread_client().open_by_key(sheet_id).worksheet(title)
