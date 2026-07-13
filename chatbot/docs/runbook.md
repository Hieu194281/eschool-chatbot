# Runbook — Tuyển Sinh Concierge (Pha 1)

Operational procedures for non-authors.

## Edit the KB (courses / pricing)

- Open the KB Google Sheet → worksheet **"Courses"**. One row per khóa.
- Columns: `course_id, ten_khoa, doi_tuong, muc_tieu, lo_trinh, lich_khai_giang,
  giao_vien, faq, chinh_sach, hoc_phi, uu_dai`.
- `hoc_phi` / `uu_dai` are the ONLY pricing fields; they are injected verbatim.
  Write them cleanly — **no newlines inside a pricing cell**, and never paste the
  phrase "SỐ LIỆU CHÍNH THỨC" or instruction-like text (the row is quarantined).
- A row with `course_id` but empty `hoc_phi` is treated as half-edited → excluded
  from serving + a Telegram alert names it. Fill `hoc_phi` to re-enable.
- Changes take effect within one sync interval (`KB_SYNC_INTERVAL_SEC`, default 5 min).
- **KB Sheet edit access must be locked-down + audited** (business responsibility) —
  cells are untrusted input to the LLM.

## Read leads / trials

- Open the Leads Google Sheet. Worksheet **"Leads"** (one row per user, upserted by
  `channel_user_id`), worksheet **"Trials"** (trial bookings, append-only).
- Hot leads (`do_nong=nóng`) also ping the Telegram group in real time.
- **Do not manually delete a middle Leads row while the bot is writing** — upsert is
  by value (`ws.find`) so it is safe, but avoid concurrent manual edits during peaks.

## Resume a handed-off conversation

- In the tư-vấn-viên Telegram group, send: `/resume messenger:<PSID>`
  (or `/resume <PSID>` — defaults to messenger).
- The bot resumes replying to that user. Only the Telegram webhook (with the correct
  secret token) can resume — a forged request is rejected.
- Auto-resume: if a handed-off user is silent ≥ `HANDOFF_AUTO_RESUME_HOURS` (24h),
  the next inbound auto-resumes the bot.

## Flip shadow mode

- `SHADOW_MODE=true` → drafts go to Telegram (`[DRAFT → PSID]`), NOTHING sent to
  users. `false` → normal auto-send.
- Change `.env`, then `sudo systemctl restart tuyensinh`.
- Flip to `false` ONLY after the go-live gate (see deployment-guide §9).

## Rotate tokens

- `PAGE_ACCESS_TOKEN` / `APP_SECRET`: rotate in Meta App settings → update `.env` →
  `systemctl restart`. Re-verify the webhook if `APP_SECRET` changed (signatures).
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_WEBHOOK_SECRET`: update `.env`, re-run `setWebhook`
  with the new `secret_token`, restart.
- On suspected leak: revoke immediately, rotate, restart.

## Logs

- `journalctl -u tuyensinh -f`. Phone numbers are auto-redacted (`012***45`) by an
  enforced logging filter. Do not add logging that bypasses it.

## PII — retention & deletion (PDPD Decree 13/2023)

- Retention window = `PII_RETENTION_DAYS` (default 180). A daily job purges
  checkpoints + handoff rows + lead rows past the window automatically.
- **Delete-on-request:** run the erase procedure for a user's PSID:
  ```python
  import asyncio
  from app.db import open_pool
  from app.db.retention_purge import delete_by_psid
  from app.config import get_settings
  async def go():
      await open_pool(get_settings().postgres_dsn)
      await delete_by_psid("<PSID>")
  asyncio.run(go())
  ```
  This erases the checkpoint thread + handoff_status row + Leads row.
- Consent: the bot gives a short privacy notice before asking for a phone number;
  consent is recorded on the lead row (`consent`, `consent_at`).
- **Cross-border basis:** Google Sheets + Telegram are US-hosted. The center must
  document the lawful cross-border transfer basis and inform users (business/legal).

## Backup / restore Postgres

```bash
docker exec tuyensinh-postgres pg_dump -U tuyensinh tuyensinh > backup-$(date +%F).sql
# restore:
cat backup-YYYY-MM-DD.sql | docker exec -i tuyensinh-postgres psql -U tuyensinh tuyensinh
```
The KB/vector store is stateless (rebuilds from the Sheet on boot) — no backup needed.

## Constraints / gotchas

- **Single uvicorn worker only** (in-memory dedupe/debounce). Multiple workers →
  duplicate replies.
- Post-ACK crash window: a hard crash between the 200 ACK and the debounce flush
  loses that buffered fragment (Meta won't redeliver). Durable queue = Pha 2.
- Messenger 24h messaging window: the bot does not send proactive follow-ups — real
  nurture = capture SĐT early, human calls.
