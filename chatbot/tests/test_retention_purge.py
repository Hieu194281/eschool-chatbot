"""PII retention at the Sheet layer: purge rows past window + delete-by-user.

(The Postgres checkpoint purge is exercised against a real DB in integration; here
we verify the lead-row side, which is the user-visible PII.)
"""

from datetime import datetime, timedelta, timezone

from app.integrations.lead_sheet import LeadSheet


async def test_purge_older_than_removes_expired_rows(fake_worksheet):
    ls = LeadSheet(fake_worksheet)
    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    new = datetime.now(timezone.utc).isoformat()
    await ls.upsert_lead({"channel_user_id": "messenger:old", "sdt": "0900000001"}, now=old)
    await ls.upsert_lead({"channel_user_id": "messenger:new", "sdt": "0900000002"}, now=new)

    removed = await ls.purge_older_than(datetime.now(timezone.utc) - timedelta(days=180))
    assert removed == 1
    remaining = {r["channel_user_id"] for r in fake_worksheet.get_all_records()}
    assert remaining == {"messenger:new"}


async def test_delete_lead_erases_user(fake_worksheet):
    ls = LeadSheet(fake_worksheet)
    await ls.upsert_lead({"channel_user_id": "messenger:1", "sdt": "0900000001"})
    assert await ls.delete_lead("messenger:1") is True
    assert fake_worksheet.get_all_records() == []
    assert await ls.delete_lead("messenger:1") is False    # already gone
