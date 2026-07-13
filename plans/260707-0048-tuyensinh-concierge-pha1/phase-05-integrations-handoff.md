# Phase 05 — Integrations & Handoff

## Context Links
- Plan: [plan.md](plan.md)
- Prev: [phase-04-messenger-channel-adapter.md](phase-04-messenger-channel-adapter.md)
- Stack ref: `researcher-260707-0012-langgraph-gemini-stack.md` §4 (gspread upsert), §5 (Telegram)
- Decisions: `brainstorm-260707-0012-*.md` §3.2, §4 (upsert, /resume, auto-resume), §5.5-5.6

## Overview
- **Priority:** P1
- **Status:** completed
- **Effort:** ~2d
- Fill real bodies of the graph tools: `capture_lead` (upsert Google Sheet by `channel_user_id`, no dup rows), `book_trial` (write Sheet), `handoff_to_human` (set flag + Telegram notify with summary + Sheet link). Implement handoff gating (bot stops replying), `/resume <user>` command + 24h auto-resume.

## Key Insights
- **Upsert by key** `channel_user_id` (e.g. `messenger:PSID`) → one row/lead, updated in place. No append duplicates. **Look up target row by VALUE (`ws.find`), never by an enumerate index** (staff row-deletes desync index → overwrites the wrong lead's SĐT).
- **Handoff authoritative source = Postgres `handoff_status` table** (O(1) gate). Tools update it; `ConvState.handoff` is advisory (bot's own awareness) only — single source of truth avoids desync. Gate is RE-CHECKED atomically immediately before send.
- **Resume**: staff types `/resume <user_id>` in Telegram group → clears flag. OR auto-resume after `HANDOFF_AUTO_RESUME_HOURS` (24h) of user silence. **Resume webhook MUST authenticate via Telegram secret-token header** (body `chat_id` is spoofable).
- **Auto-resume clock:** `last_user_ts` MUST be touched on EVERY inbound BEFORE the auto-resume check — touching it after the handoff early-return freezes the clock at handoff start and the bot barges into a live human chat ~24h later.
- **PII (Vietnam PDPD Decree 13/2023):** explicit consent + privacy notice before persisting a phone number; defined retention window + automated purge; deletion-by-PSID procedure; enforced log redaction; documented cross-border transfer basis (Sheets/Telegram US-hosted).
- **Nurture reality** (brainstorm §5.3): 24h/48h messaging windows mean free proactive follow-up not viable → real nurture = capture SĐT early, human calls. Bot doesn't schedule outbound.
- Telegram = raw HTTPS POST (no lib), summary + Sheet link on handoff or hot lead.
- Lead sheet write is the KB layer's error-alert sink too (reuse Telegram notifier).

## Requirements
**Functional**
- `capture_lead(...)`: upsert row in Leads worksheet keyed by `channel_user_id`; columns: `channel_user_id, ten, sdt, khoa_quan_tam, nhu_cau, do_nong, sales_stage, chat_link, updated_at`. Update if key exists else append. Notify Telegram if `do_nong=="nóng"`.
- `book_trial(...)`: write trial row (Sheet "Trials": channel_user_id, sdt, khoa, slot, created_at). (Calendar optional/YAGNI Pha 1 — Sheet is enough.)
- `handoff_to_human(reason)`: write `handoff_status.set_active` (authoritative) + advisory `handoff=True` in state, Telegram notify with conversation summary + lead + Sheet link.
- Handoff gate: dispatcher reads `handoff_status` (authoritative) before bot reply; if active → skip. **RE-CHECK `handoff_status.is_active` atomically immediately before the send/deliver call** — drop the reply if handoff became active during the multi-second invoke (TOCTOU close).
- `/resume <user_id>` via Telegram webhook clears handoff. **Reject any request whose `X-Telegram-Bot-Api-Secret-Token` header ≠ configured `TELEGRAM_WEBHOOK_SECRET`** (constant-time compare); body `chat_id` is advisory only.
- Auto-resume: touch `last_user_ts` on EVERY inbound BEFORE the auto-resume/handoff check; if handoff active and `now - last_user_ts > 24h` AND no recent `last_human_ts`, clear flag (lazy on inbound) OR scheduled sweep. (Or make silent auto-resume opt-in, require explicit `/resume`.)
- Lead upsert: locate the target row by VALUE (`ws.find(channel_user_id)`) → use its returned row number; re-find immediately before write; guard the read-modify-write with the same per-user lock as the dispatcher single-flight.
- PII consent: capture an explicit consent line + short privacy notice before persisting a phone number; record consent state on the lead row.

**Non-functional**
- Files <200 LOC; split lead-sheet / trial-sheet / telegram-notify / handoff-manager / resume-command.
- gspread BackOffHTTPClient; batch where possible.
- Idempotent upsert (re-running same lead = update, never dup); row located by value not index.
- Retention: automated purge of old checkpoints + lead rows past the retention window; deletion-by-PSID procedure; log redaction enforced by a logging Filter (not a convention).

## Architecture
```
Graph tools (Ph03 signatures) → real bodies here:
  capture_lead ──> integrations/lead-sheet.py  (upsert by channel_user_id)
                     └─ if nóng ─> integrations/telegram-notify.py
  book_trial   ──> integrations/trial-sheet.py
  handoff_to_human ─> handoff/handoff-manager.py (set flag path) + telegram-notify (summary+link)

Handoff gating:
  dispatcher.on_flush → handoff-manager.is_active(thread_id)?
      active → skip bot (human handles) ; also run auto-resume check
      inactive → run graph

Resume:
  Telegram group "/resume <user>" → webhook-telegram.py → handoff-manager.clear(thread_id)
  Auto: handoff-manager stores last_activity; inbound after 24h → clear
```

### Handoff state source of truth (FIX — single authority)
- **Authoritative = Postgres `handoff_status(thread_id, active, reason, since, last_user_ts, last_human_ts)` table.** O(1) gate checks + resume sweeps. `handoff_to_human`/`/resume` write it. `ConvState.handoff` is **advisory** (bot's own awareness) only — NOT dual source of truth (previous design had it in both → desync). If they diverge, `handoff_status` wins.
- **TOCTOU close:** dispatcher checks `is_active` before invoke AND **re-checks atomically immediately before the send/deliver call**; if it flipped active during the ~multi-second invoke, DROP the reply (human already engaged). The prior "gate just before send" claim didn't match a check that ran before the whole invoke — this makes it literally true.

### Lead upsert (integrations/lead-sheet.py) — FIX: locate by value, not enumerate index
```python
async def upsert_lead(lead: dict):
    async with per_user_lock(lead["channel_user_id"]):   # same lock as dispatcher single-flight
        cell = ws.find(lead["channel_user_id"], in_column=CHANNEL_USER_ID_COL)  # by VALUE
        if cell:                                   # re-find right before write; use returned row
            ws.update(f"A{cell.row}:K{cell.row}", [row_values(lead)]); return "updated"
        ws.append_row(row_values(lead)); return "created"
```
- **Why:** `enumerate(rows, start=2)` assumes row N in `get_all_records()` == physical row N+2. A staff mid-sheet row-delete desyncs that → old code overwrites a DIFFERENT lead's SĐT. `ws.find` returns the true physical row.
- Columns now include a consent flag: `channel_user_id, ten, sdt, khoa_quan_tam, nhu_cau, do_nong, sales_stage, chat_link, consent, consent_at, updated_at` (range widened to K).
- `chat_link` = deep link to Messenger conversation (page inbox URL or note PSID). `updated_at` = now.

### Telegram notify (integrations/telegram-notify.py)
```python
async def notify(text_html):
    POST https://api.telegram.org/bot{TOKEN}/sendMessage
    {chat_id: TELEGRAM_CHAT_ID, text, parse_mode:"HTML"}
```
Handoff message: reason + lead summary (tên/SĐT/khóa/độ nóng) + Sheet link + last few turns. Hot-lead message: similar, lighter.

### Resume (handoff/resume-command.py + api/webhook-telegram.py)
- **AUTH (CRITICAL):** set a secret via Telegram `setWebhook(secret_token=TELEGRAM_WEBHOOK_SECRET)`. Reject any request whose `X-Telegram-Bot-Api-Secret-Token` header ≠ configured value (constant-time compare) BEFORE parsing. Body `chat_id` is spoofable → advisory only, never the auth boundary. (Prior "only accept from configured TELEGRAM_CHAT_ID" is insufficient — the body is attacker-controlled.)
- Telegram webhook receives group messages; parse `/resume <user_id>` (or `/resume messenger:PSID`) → `handoff-manager.clear`.
- Auto-resume: on EVERY inbound in dispatcher, `touch(last_user_ts=now)` FIRST, THEN if handoff active and `now - last_user_ts_prev > 24h` and no recent `last_human_ts` → clear before processing. (Touch-before-check ordering is load-bearing — see fix below.)

## Related Code Files
**Create**
- `chatbot/app/integrations/lead-sheet.py` — gspread Leads upsert by channel_user_id
- `chatbot/app/integrations/trial-sheet.py` — Trials append
- `chatbot/app/integrations/telegram-notify.py` — raw httpx Telegram POST (summary/link)
- `chatbot/app/handoff/handoff-manager.py` — set/clear/is_active + `handoff_status` table access + auto-resume check
- `chatbot/app/handoff/resume-command.py` — parse/execute `/resume`
- `chatbot/app/api/webhook-telegram.py` — Telegram webhook route; secret-token header auth (constant-time)
- `chatbot/app/db/handoff-status-table.py` — table create/CRUD incl `last_human_ts` (or migration snippet)
- `chatbot/app/db/retention-purge.py` — scheduled purge of old checkpoints + lead rows; `delete_by_psid(psid)` deletion procedure
- `chatbot/app/log-redaction-filter.py` — logging Filter redacting phone patterns (enforced, not convention)

**Modify**
- `chatbot/app/graph/tools/lead-tools.py` — replace Ph03 stubs with real calls (capture_lead→lead-sheet+notify; book_trial→trial-sheet; handoff_to_human→handoff-manager+notify)
- `chatbot/app/channel/message-dispatcher.py` — implement handoff gate + auto-resume check at the Ph04 seam
- `chatbot/app/kb/sync-scheduler.py` — wire error callback → telegram-notify
- `chatbot/app/main.py` — create `handoff_status` table on startup; mount Telegram webhook

## Implementation Steps
1. `db/handoff-status-table.py`: table `handoff_status(thread_id PK, active bool, reason text, since timestamptz, last_user_ts timestamptz, last_human_ts timestamptz)`; create on startup. This table is the AUTHORITATIVE handoff gate (ConvState.handoff advisory).
2. `handoff-manager.py`: `set_active(thread_id,reason)`, `clear(thread_id)`, `is_active(thread_id)->bool` (authoritative), `touch(thread_id, ts)`, `touch_human(thread_id, ts)`, `should_auto_resume(thread_id, now)` (uses last_user_ts AND last_human_ts).
3. `integrations/telegram-notify.py`: async POST; HTML escape; helper `format_handoff(lead, reason, link, turns)` + `format_hot_lead(lead)`.
4. `integrations/lead-sheet.py`: gspread client (reuse Ph02 auth pattern / shared helper); `upsert_lead` — **locate row by `ws.find(channel_user_id)` (by value), re-find right before write, guard with per-user lock**; return created/updated. Persist `consent`/`consent_at`. Add DRY `sheets-client.py` if auth duplicated with Ph02 (extract shared).
5. `integrations/trial-sheet.py`: `append_trial`.
6. Fill `lead-tools.py` bodies: `capture_lead`→(record consent) upsert + hot-lead notify; `book_trial`→append_trial; `handoff_to_human`→`set_active` + `format_handoff` notify. Tools return `Command(update={...})` (Ph03 fix) so `sales_stage`/advisory `handoff` persist; `handoff_status` table is the authoritative gate.
7. `message-dispatcher.py`: on EVERY inbound `touch(last_user_ts=now)` FIRST; THEN `if handoff_manager.is_active(thread_id): if should_auto_resume: clear else: return (skip bot)`. **Re-check `handoff_manager.is_active` atomically immediately before deliver/send; drop reply if it went active during invoke** (TOCTOU). (Fix #10: touch must precede the early return, else clock freezes at handoff start.)
8. `resume-command.py` + `webhook-telegram.py`: **verify `X-Telegram-Bot-Api-Secret-Token` == `TELEGRAM_WEBHOOK_SECRET` (constant-time) before parsing; reject otherwise.** Register via `setWebhook(secret_token=...)`. Parse `/resume <user>`; `handoff_manager.clear`; reply to group. Body `chat_id` advisory only.
8b. **PII/PDPD:** consent line + privacy notice emitted before persisting SĐT (record `consent` on lead row); `db/retention-purge.py` scheduled job purges checkpoints + lead rows past retention window; `delete_by_psid(psid)` procedure (clears checkpoint thread + lead row + handoff_status); install a logging `Filter` that redacts phone patterns everywhere (not a convention); document cross-border basis (Sheets/Telegram US-hosted) in runbook.
9. `sync-scheduler.py`: pass `telegram_notify` as the error callback for KB sync failures/bad rows.
10. `main.py`: create table; mount Telegram webhook (or start polling task).
11. Test: capture same lead twice → 1 row updated; hot lead → Telegram ping; handoff → flag set + notify + bot silent; `/resume` → bot resumes; simulate 24h gap → auto-resume.

## Todo List
- [ ] `handoff_status` table (incl `last_human_ts`) + CRUD — authoritative gate
- [ ] `handoff-manager.py` set/clear/is_active/touch/touch_human/auto-resume
- [ ] `telegram-notify.py` POST + handoff/hot-lead formatters
- [ ] `lead-sheet.py` upsert by `ws.find` value (not index), re-find before write, per-user lock, consent columns
- [ ] `trial-sheet.py` append
- [ ] Shared `sheets-client.py` if auth duplicated (DRY)
- [ ] `lead-tools.py` real bodies returning Command (capture/book/handoff); handoff writes authoritative table
- [ ] Dispatcher: touch last_user_ts BEFORE gate/return; re-check is_active atomically before send (TOCTOU)
- [ ] `/resume` via Telegram webhook: `X-Telegram-Bot-Api-Secret-Token` constant-time auth
- [ ] `retention-purge.py` scheduled purge + `delete_by_psid`; consent capture; `log-redaction-filter.py`
- [ ] KB sync error callback → Telegram
- [ ] Tests: upsert dedupe, upsert after middle-row deletion (wrong-row guard), hot-lead notify, gate silence, resume, auto-resume, Telegram secret-token rejection, retention purge

## Success Criteria
- Same `channel_user_id` captured twice → exactly one Leads row, updated (no dup).
- **Deleting a middle Leads row then upserting an existing lead updates the CORRECT row** (found by value, not desynced index) — no wrong-lead SĐT overwrite.
- Hot lead (`do_nong=nóng`) → Telegram group receives summary + Sheet link.
- `handoff_to_human` → authoritative `handoff_status.active=true`, Telegram notified, bot stops replying; a reply drafted before handoff but not yet sent is DROPPED (re-check before send).
- `/resume <user>` with correct secret-token header → resumes; **a forged POST with wrong/missing `X-Telegram-Bot-Api-Secret-Token` is rejected** (cannot clear anyone's handoff).
- No user message for 24h during handoff → next inbound auto-resumes; a handoff that started <24h ago does NOT auto-resume (clock touched on every inbound, not frozen).
- Retention purge removes checkpoints + lead rows past window; `delete_by_psid` erases a user's data on request; phone numbers redacted in logs.
- KB sync error → Telegram alert (bad rows named).

## Risk Assessment
| Risk | L×I | Mitigation |
|---|---|---|
| Upsert overwrites WRONG lead's SĐT after staff row-delete | Med×High | Locate row by `ws.find` value (not enumerate index); re-find before write; per-user lock; test deletes middle row then upserts |
| `/resume` forged (spoofed body chat_id clears anyone's handoff) | Critical (Med×High) | `X-Telegram-Bot-Api-Secret-Token` constant-time auth via `setWebhook(secret_token=…)`; body chat_id advisory only |
| Auto-resume clock frozen → bot barges into live human chat | Med×High | Touch `last_user_ts` on every inbound BEFORE the handoff early-return; add `last_human_ts`; or require explicit `/resume` |
| Handoff TOCTOU + dual source-of-truth desync | Med×High | `handoff_status` table authoritative (O(1)); ConvState.handoff advisory; re-check `is_active` atomically just before send |
| PII (SĐT) stored without consent / no retention (PDPD Decree 13/2023) | Med×High | Consent line + notice before persist; retention window + automated purge; delete-by-PSID; enforced log-redaction filter; document cross-border basis |
| Duplicate lead rows | Med×Med | Upsert by channel_user_id (by value); unit test twice-capture |
| Telegram down → lost alert | Low×Med | Log + retry once; non-fatal (Sheet still has lead) |
| gspread quota under load | Low×Med | BackOffHTTPClient; upsert reads once per call (acceptable low volume Pha 1) |
| Stuck handoff (human forgets /resume) | Med×Low | 24h auto-resume backstop; periodic sweep optional |

## Security Considerations
- **PII (SĐT) — Vietnam PDPD Decree 13/2023:** explicit consent line + short privacy notice BEFORE persisting a phone number; record consent state (`consent`/`consent_at`) on the lead row. Defined retention window + automated purge of old checkpoints + lead rows; `delete_by_PSID` deletion-on-request procedure. **Log redaction enforced by a logging Filter** (code, not convention). Document cross-border transfer basis (Google Sheets / Telegram US-hosted). Least-privilege SA; restrict Sheet sharing.
- **Telegram webhook auth:** verify `X-Telegram-Bot-Api-Secret-Token` (constant-time) — the request BODY (`chat_id`) is attacker-controlled and MUST NOT be the auth boundary. `TELEGRAM_WEBHOOK_SECRET` + `TELEGRAM_BOT_TOKEN` via env.
- Telegram messages contain PII (SĐT) + Sheet link → group membership must be controlled (business responsibility; note in runbook).
- No secrets in Sheet or Telegram payloads beyond necessary lead data.

## Next Steps
- Unblocks Phase 06: full end-to-end path exists; shadow-mode toggle wraps the send step; tests target upsert/gate/resume.
