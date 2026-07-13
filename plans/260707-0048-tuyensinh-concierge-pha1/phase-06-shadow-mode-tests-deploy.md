# Phase 06 — Shadow Mode, Tests & Deploy

## Context Links
- Plan: [plan.md](plan.md)
- Prev: [phase-05-integrations-handoff.md](phase-05-integrations-handoff.md)
- Decisions: `brainstorm-260707-0012-*.md` §4 (shadow mode), §7 (risks), §8 (metrics)
- Channel deploy ref: `researcher-260707-0012-messenger-zalo-apis.md` §4 (App Review), §5 (gotchas)

## Overview
- **Priority:** P1
- **Status:** completed
- **Effort:** ~1d
- Add shadow-mode toggle (bot drafts, human approves/sends — or test fanpage). Write unit/integration tests (webhook idempotency, debounce, grade fallback, reflect-lite, upsert dedupe). Document public-HTTPS webhook deployment (VPS + reverse proxy/tunnel) + runbook.

## Key Insights
- **App Review is on the CRITICAL PATH (process, HIGH).** Before Advanced Access, a Messenger app can only message users who have a ROLE on the app/page. So the shadow-mode dry run necessarily runs on STAFF-SIMULATED conversations → the ">95% correct" go-live metric CANNOT be computed on real prospect phrasing until after approval. Therefore: submit App Review at the FRONT of the timeline (parallel with Ph01-03), separate an **"engineering-complete"** milestone from a **"launch-ready"** milestone, and require a minimum volume of REAL (post-approval) conversations before flipping `SHADOW_MODE=false`. The 11-eng-day estimate is NOT the calendar-to-launch.
- **Shadow mode = launch safety** (week 1). Two viable modes: (a) draft-to-Telegram-for-approval, or (b) run on a **test fanpage** with real auto-send. Simplest safe path (KISS): `SHADOW_MODE=true` → instead of Send API to user, post the drafted reply to Telegram group for staff to copy/approve. Flip to `false` for full auto.
- Target before going auto: >95% pricing/schedule answers correct **measured on real post-approval conversations (min volume)** + zero invented-price incidents (brainstorm §8).
- Tests focus on the **failure modes**, not happy path: idempotency, debounce coalescing, grade→fallback, reflect-lite catch, upsert dedupe, plus the NEW guards (pricing-guard, single-flight, upsert-after-row-delete, Telegram secret-token, rate-limit, retention purge).
- Single-worker deploy (in-memory dedupe/debounce) — document explicitly. Public HTTPS required for Messenger webhook (VPS + Caddy/nginx TLS, or Cloudflare Tunnel for quick start).

## Requirements
**Functional**
- `SHADOW_MODE` toggle: `true` → drafts go to Telegram (not user); `false` → normal Send API.
- Test suite runnable via `pytest`; all pass; no mocks that hide real behavior on core paths (use real functions with test doubles only for external HTTP/Sheets where unavoidable).
- Deployment doc: VPS setup, TLS reverse proxy, env, single-worker uvicorn, Meta webhook registration, health monitoring.
- Runbook: how to edit KB, read leads, resume handoff, rotate tokens, read logs, flip shadow mode.

**Non-functional**
- Tests deterministic, fast; external calls stubbed at boundary (httpx transport, gspread client), core logic real.
- Deploy reproducible from doc.

## Architecture
```
send path (dispatcher → adapter.send_text) wrapped by shadow gate:
  if SHADOW_MODE: telegram_notify(f"[DRAFT to {user}] {reply}") ; do NOT send to user
  else: adapter.send_text(user, reply)

Deploy:
  Internet → TLS (Caddy/nginx or Cloudflare Tunnel) → uvicorn (1 worker) app
  Postgres (docker-compose, same VPS) ; APScheduler in-process
  Secrets in /etc env or .env (600 perms, not in repo)
```

### Test matrix
| Area | Type | What | Boundary stub |
|---|---|---|---|
| signature-verify | unit | valid/invalid/missing sig | none (pure) |
| dedupe-store | unit | same mid processed once, TTL prune | none |
| debounce-buffer | unit/async | N fragments → 1 flush; timer reset | fake on_flush |
| webhook idempotency | integration | resent event → single graph call | stub graph invoke |
| grade→fallback | integration | insufficient chunks → fallback + handoff=True | stub KB retrieve (empty) + real grade or stub lite LLM |
| reflect-lite | unit/integration | forbidden-promise (regex + paraphrase) flagged; loop guard | stub lite LLM structured output |
| **pricing-guard** | unit | promo-derived number (5tr−10%→"4tr5") rejected; Course-A price for Course-B rejected; "miễn phí" no-basis rejected; VN-numeral normalize | none (pure/deterministic) |
| **single-flight** | integration/async | concurrent same-thread message mid-turn → serialized, one ainvoke, no checkpoint clobber | stub graph invoke w/ delay |
| **rate-limit** | unit | per-PSID over cap → canned line, graph not invoked; maps bounded | none |
| lead upsert dedupe | integration | capture twice → 1 row updated | fake gspread worksheet (in-mem) |
| **lead upsert after middle-row delete** | integration | delete a middle row then upsert existing → correct row updated, no wrong-lead overwrite | in-mem gspread w/ find() |
| handoff gate | integration | active flag → bot skips send; re-check drops reply if flipped mid-invoke | in-mem handoff table |
| **Telegram secret-token** | unit | resume POST w/ wrong/missing `X-Telegram-Bot-Api-Secret-Token` → rejected | none |
| **PII retention purge** | unit/integration | rows/checkpoints past window purged; delete_by_psid erases user data | in-mem store |
| resume | unit | /resume clears; 24h auto-resume; <24h no auto-resume (clock touched) | in-mem |
| shadow mode | integration | SHADOW_MODE → Telegram draft, no user send | stub telegram + send clients |

### Metrics (shadow-mode measurement, brainstorm §8)
- % học phí/lịch answers correct vs KB (manual review of drafts) — target >95% **measured on real post-approval conversations (min volume, not staff-simulated)** before auto.
- Min volume of REAL prospect conversations logged post-App-Review before `SHADOW_MODE=false` (define threshold, e.g. ≥N convos / ≥M priced questions).
- Leads/week + % with SĐT.
- Response time <15s/message.
- % conversations needing handoff.
- Zero invented-price/commitment incidents.

### Milestones (decouple engineering from launch)
- **Engineering-complete:** all phases coded, `pytest` green, shadow dry-run passes on staff-simulated convos (~11 eng-days).
- **Launch-ready:** App Review Advanced Access granted + min real-conversation volume met + go-live metric gate passed → flip `SHADOW_MODE=false`. Calendar date gated by App Review (weeks), NOT by eng-days.

## Related Code Files
**Create**
- `chatbot/app/channel/shadow-gate.py` — wraps send: draft-to-Telegram vs real send
- `chatbot/tests/test-signature-verify.py`
- `chatbot/tests/test-dedupe-store.py`
- `chatbot/tests/test-debounce-buffer.py`
- `chatbot/tests/test-webhook-idempotency.py`
- `chatbot/tests/test-grade-fallback.py`
- `chatbot/tests/test-reflect-lite.py`
- `chatbot/tests/test-pricing-guard.py` — promo-derived / wrong-course / `miễn phí` rejection; VN-numeral normalize
- `chatbot/tests/test-single-flight.py` — concurrent same-thread serialization
- `chatbot/tests/test-rate-limit.py` — per-PSID cap, bounded maps
- `chatbot/tests/test-lead-upsert.py` — incl middle-row-delete correctness
- `chatbot/tests/test-telegram-secret-token.py` — resume auth rejection
- `chatbot/tests/test-retention-purge.py` — purge + delete_by_psid
- `chatbot/tests/test-handoff-resume.py`
- `chatbot/tests/test-shadow-mode.py`
- `chatbot/tests/conftest.py` — fixtures: in-mem gspread double, stub LLMs, test settings
- `chatbot/docs/deployment-guide.md` — VPS + TLS + webhook registration
- `chatbot/docs/runbook.md` — ops procedures

**Modify**
- `chatbot/app/channel/message-dispatcher.py` — route send through `shadow-gate`
- `chatbot/README.md` — link deployment guide + runbook + test command

## Implementation Steps
1. `shadow-gate.py`: `async def deliver(adapter, user_id, reply)`: if `settings.SHADOW_MODE` → `telegram_notify(f"[DRAFT → {user_id}]\n{reply}")`; else `await adapter.send_text(user_id, reply)`. Dispatcher calls `deliver` instead of send_text directly.
2. `conftest.py`: test Settings (env overrides), in-memory gspread worksheet double (list-of-dicts with get_all_records/update/append_row), stub lite/main LLMs returning canned structured outputs, httpx MockTransport for Send API/Telegram.
3. Write unit tests (signature, dedupe, debounce, reflect-lite) — pure/fast.
4. Write integration tests (idempotency, grade-fallback, upsert, handoff/resume, shadow) using doubles at external boundaries only; core graph/dispatch logic real.
5. Run `pytest`; fix until green (do NOT weaken assertions to pass).
6. `deployment-guide.md`: provision VPS (Ubuntu), install docker + python, clone, `.env` (600), `docker compose up -d` postgres, run uvicorn (1 worker) under systemd; TLS via Caddy (auto-HTTPS) or Cloudflare Tunnel; register Messenger webhook (callback URL + VERIFY_TOKEN), subscribe `messages` field. **App Review is on the critical path — submit at the FRONT (parallel with Ph01-03), not after internal test.** State explicitly: pre-approval the app only messages users with a role on the app/page (shadow dry-run = staff-simulated only); real-prospect metrics require Advanced Access. Document engineering-complete vs launch-ready milestones and the min real-conversation volume gate before `SHADOW_MODE=false`. Note App Review multi-week lead time.
7. `runbook.md`: edit KB Sheet, read Leads Sheet, `/resume`, flip SHADOW_MODE, rotate PAGE_ACCESS_TOKEN/APP_SECRET, view logs, restart, single-worker constraint, backup Postgres.
8. Shadow-mode dry run: point test fanpage at webhook, converse, review drafts in Telegram, measure metrics. Pre-approval this is STAFF-SIMULATED only. Flip `SHADOW_MODE=false` ONLY after: Advanced Access granted + min volume of REAL prospect conversations logged + >95% correct + zero price incidents.

## Todo List
- [ ] `shadow-gate.py` draft-vs-send toggle wired into dispatcher
- [ ] `conftest.py` fixtures (gspread double, stub LLMs, mock transport)
- [ ] Unit: signature, dedupe, debounce, reflect-lite, pricing-guard, rate-limit, Telegram secret-token
- [ ] Integration: idempotency, grade-fallback, single-flight serialization, upsert dedupe, upsert-after-middle-row-delete, handoff/resume, retention purge, shadow
- [ ] `pytest` all green (no weakened assertions)
- [ ] `deployment-guide.md` (VPS + TLS + webhook registration + **App Review submitted FRONT/critical-path** + eng-complete vs launch-ready milestones)
- [ ] `runbook.md` (KB/leads/resume/shadow/token-rotation/logs/backup + PII deletion/retention + cross-border basis)
- [ ] App Review submitted early (parallel Ph01-03); Advanced Access tracked
- [ ] Shadow dry-run; metrics captured; min REAL-conversation volume met before flip; go/no-go recorded

## Success Criteria
- `pytest` green covering all failure-mode tests in matrix (incl pricing-guard, single-flight, upsert-after-row-delete, Telegram secret-token, rate-limit, retention purge).
- `SHADOW_MODE=true` sends zero messages to real users; drafts land in Telegram.
- Deployment guide reproduces a working public-HTTPS webhook (handshake passes from Meta).
- Runbook lets non-author operate: edit KB, read leads, resume, flip shadow, rotate tokens, run PII deletion/retention.
- **App Review on critical path documented; engineering-complete and launch-ready are separate milestones.**
- Go-live gate documented: Advanced Access + min REAL-conversation volume + >95% correct + zero invented-price before `SHADOW_MODE=false`.

## Risk Assessment
| Risk | L×I | Mitigation |
|---|---|---|
| Tests pass but bot bad in prod | Med×High | Shadow mode week 1 + metric gate before auto |
| Multi-worker breaks dedupe/debounce | Med×High | systemd runs single worker; documented; Redis deferred |
| Webhook not reachable (TLS/cert) | Med×High | Caddy auto-HTTPS or CF Tunnel; verify handshake in guide |
| App Review delay blocks launch (multi-week critical path hidden by 11-eng-day estimate) | Med×High | Submit App Review at FRONT (parallel Ph01-03); separate eng-complete vs launch-ready milestones; shadow with team accounts (Standard) meanwhile; calendar ≠ eng-days |
| Go-live metric computed on staff-simulated (not real) phrasing pre-approval | Med×High | Require min volume of REAL post-approval conversations before flipping `SHADOW_MODE=false` |
| Token expiry/rotation downtime | Low×Med | Runbook rotation steps; monitor 401/expired; alert |
| Postgres data loss | Low×High | docker volume + documented backup (pg_dump) in runbook |
| Flaky external stubs make tests brittle | Low×Low | Stub only at HTTP/Sheets boundary; keep core logic real |

## Security Considerations
- Shadow-mode drafts to Telegram contain PII → controlled group only.
- `.env` file perms 600 on VPS; never in repo; SA JSON outside webroot.
- TLS mandatory for webhook (Meta requires HTTPS).
- Token rotation procedure documented; revoke on suspected leak.
- Single-worker note prevents silent dedupe bypass (dup replies) — a correctness+trust issue.
- Postgres not exposed publicly (bind 127.0.0.1 / docker network only).

## Next Steps
- After go-live gate passes → `SHADOW_MODE=false` full auto on real fanpage.
- Feed collected conversations into Pha 2 (handle_objection, score_lead, full reflection).
- When Zalo OA verified → implement `ZaloAdapter` + webhook (spine unchanged).
- Revisit Redis for dedupe/debounce only if scaling beyond single worker (YAGNI until then).
