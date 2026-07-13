"""Lead upsert dedupe + the red-team #9 middle-row-delete correctness."""

from app.integrations.lead_sheet import LeadSheet


async def test_capture_twice_updates_one_row(fake_worksheet):
    ls = LeadSheet(fake_worksheet)
    assert await ls.upsert_lead({"channel_user_id": "messenger:1", "ten": "A", "sdt": "0900000001"}) == "created"
    assert await ls.upsert_lead({"channel_user_id": "messenger:1", "ten": "A2", "sdt": "0900000002"}) == "updated"
    records = fake_worksheet.get_all_records()
    assert len(records) == 1
    assert records[0]["sdt"] == "0900000002"


async def test_upsert_after_middle_row_delete_updates_correct_row(fake_worksheet):
    ls = LeadSheet(fake_worksheet)
    await ls.upsert_lead({"channel_user_id": "messenger:1", "sdt": "0900000001"})
    await ls.upsert_lead({"channel_user_id": "messenger:2", "sdt": "0900000002"})
    await ls.upsert_lead({"channel_user_id": "messenger:3", "sdt": "0900000003"})

    # Staff deletes the MIDDLE physical row (messenger:2 at row 3) → index desync.
    fake_worksheet.delete_rows(3)

    # Upsert an EXISTING lead: located by VALUE (ws.find), so the right row updates.
    await ls.upsert_lead({"channel_user_id": "messenger:3", "sdt": "0900000099"})

    by_id = {r["channel_user_id"]: r for r in fake_worksheet.get_all_records()}
    assert by_id["messenger:3"]["sdt"] == "0900000099"   # correct row updated
    assert by_id["messenger:1"]["sdt"] == "0900000001"   # NOT overwritten (no wrong-lead)
