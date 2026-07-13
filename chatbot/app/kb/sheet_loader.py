"""Fetch raw course rows from the Google Sheet KB (single batch API call/sync)."""

from ..config import get_settings
from ..integrations.sheets_client import open_worksheet

COURSES_WORKSHEET = "Courses"


def load_courses() -> list[dict]:
    """Return all rows of the 'Courses' worksheet as list[dict] (header-keyed).

    One `get_all_records()` call per sync — stays well under the gspread quota;
    the shared client's BackOffHTTPClient auto-retries transient errors.
    """
    settings = get_settings()
    worksheet = open_worksheet(settings.kb_sheet_id, COURSES_WORKSHEET)
    return worksheet.get_all_records()
