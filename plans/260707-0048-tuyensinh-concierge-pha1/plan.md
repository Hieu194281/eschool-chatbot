---
title: "Tuyển Sinh Concierge — Pha 1 (Messenger Sales Chatbot)"
description: "Standalone Python/LangGraph Corrective-RAG sales chatbot on Messenger: KB from Google Sheet, lead capture, handoff, shadow-mode launch."
status: completed
priority: P1
effort: 11d
branch: master
tags: [chatbot, langgraph, rag, backend, python]
blockedBy: []
blocks: []
created: 2026-07-07
---

# Tuyển Sinh Concierge — Pha 1

> Standalone enrollment-consulting sales chatbot. Messenger FIRST (Zalo scaffolded, later).
> Source of truth: `plans/reports/brainstorm-260707-0012-tuyensinh-concierge-pha1.md` (locked decisions).
> Stack/API refs: `plans/reports/researcher-260707-0012-*.md`. Product framing: `2026-07-06-tuyensinh-concierge-brainstorm.md`.

**Goal:** 24/7 bot answers khóa/học phí/lịch from center KB (never invents pricing), captures structured leads → Google Sheet, books trials, hands off to humans via Telegram. Launch in shadow mode.

> **Calendar ≠ 11 eng-days.** Meta App Review (Advanced Access) is on the CRITICAL PATH and takes multiple weeks. Submit at the FRONT (parallel with Ph01-03). "Engineering-complete" (~11 eng-days) and "launch-ready" (App Review granted + real-conversation metric gate) are SEPARATE milestones — see Phase 06.

**Architecture:** `Messenger webhook → ACK 200 → dedupe mid → debounce 5-8s → LangGraph StateGraph (agent ⇄ tools, Corrective-RAG, reflect-lite) → Send API`. KB synced from Google Sheet every ~5 min into InMemoryVectorStore; tuition/promo injected VERBATIM from structured columns (never chunked). State persisted via AsyncPostgresSaver (`thread_id={channel}:{user_id}`).

## Implementation status (2026-07-13)

**Engineering-complete.** All 6 phases implemented as standalone service in `chatbot/`
(all 17 red-team fixes applied). Verified: `python -m compileall` clean on every file +
**68 pytest tests green** on Python 3.10 (deterministic guards, concurrency, integration;
LLM/Sheets/DB stubbed at boundaries). NOT yet run end-to-end with live Gemini/Postgres/
Sheets (dev host has no Python — used WSL for verification). See
`chatbot/docs/algorithms-and-details.md` for every algorithm + what to test with live deps.
Remaining = **launch-ready** milestone (App Review + real-conversation metric gate).

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 01 | [Project setup & infra](phase-01-project-setup-infra.md) | completed |
| 02 | [KB layer — Sheet sync + vector store](phase-02-kb-layer-sheet-sync-vectorstore.md) | completed |
| 03 | [LangGraph brain — graph, tools, reflect-lite](phase-03-langgraph-brain.md) | completed |
| 04 | [Messenger channel adapter](phase-04-messenger-channel-adapter.md) | completed |
| 05 | [Integrations & handoff](phase-05-integrations-handoff.md) | completed |
| 06 | [Shadow mode, tests & deploy](phase-06-shadow-mode-tests-deploy.md) | completed |

## Dependencies

```
01 (setup) ──> 02 (KB) ──┐
             └> 03 (brain) ──> 04 (adapter) ──> 05 (integrations) ──> 06 (shadow/tests/deploy)
02 ──> 03 (brain needs retrieve_kb + pricing injector)
03 ──> 05 (handoff tool + lead upsert wired via brain tools)
```
- 02 & 03 can partly overlap after 01 (different file owners: `kb/*` vs `graph/*`).
- 04 depends on 03 (needs compiled graph to invoke).
- 05 depends on 03+04 (tools call Sheet/Telegram; handoff gating sits in adapter dispatch).
- 06 depends on all.

## Red Team Review

### Session — 2026-07-07
**Findings:** 17 applied (4 Critical, 11 High, 2 process)

| # | Finding | Severity | Applied To |
|---|---------|----------|------------|
| 1 | Deterministic pricing-guard (price↔course_id binding, VN-numeral normalize, forbid computed discounts, fail-closed); reflect-lite demoted to promise/tone + regex blocklist | Critical | Phase 03 |
| 2 | State-mutating tools must return `Command(update=…)` / post-tool node — plain `str` can't flip `handoff`/`sales_stage` (silent no-op) | Critical | Phase 03 |
| 3 | `AsyncPostgresSaver.from_conn_string` is an async ctx mgr — keep open for app lifetime, else pool closes and every invoke fails | High | Phase 03 |
| 4 | LLM retry/backoff w/ jitter on 429/5xx/timeout; no dangling HumanMessage on give-up | High | Phase 03 |
| 5 | Per-thread `asyncio.Lock` single-flight — debounce (6s) < turn (15s) → concurrent same-thread ainvoke clobbers checkpoint | Critical | Phase 04 |
| 6 | Per-PSID rate limit + global concurrency cap + bounded LRU dedupe/debounce maps + Gemini spend alert | High | Phase 04 |
| 7 | Post-ACK loss: use `BackgroundTasks` (drained on shutdown) not bare `create_task`; document residual crash window | High | Phase 04 |
| 8 | Telegram `/resume` webhook: authenticate via `X-Telegram-Bot-Api-Secret-Token` (constant-time); body `chat_id` advisory only | Critical | Phase 05 |
| 9 | Lead upsert by `ws.find` value (not enumerate index) → no wrong-lead SĐT overwrite after staff row-delete; per-user lock | High | Phase 05 |
| 10 | Auto-resume clock: touch `last_user_ts` on every inbound BEFORE early return; add `last_human_ts` | High | Phase 05 |
| 11 | Handoff TOCTOU + dual source of truth: `handoff_status` table authoritative, ConvState advisory; re-check atomically before send | High | Phase 05 |
| 12 | PII consent/retention (PDPD Decree 13/2023): consent line, retention purge, delete-by-PSID, enforced log-redaction filter, cross-border basis | High | Phase 05 |
| 13 | Partial-row validation: empty/whitespace `hoc_phi` → skip/exclude + alert (not served as official data) | High | Phase 02 |
| 14 | Prompt injection via Sheet: wrap chunks as UNTRUSTED-DATA; sanitize pricing cells (reject newline/trust-marker/instruction) | High | Phase 02 |
| 15 | Vector-store concurrency: build off event loop, swap single immutable `(store,pricing,version)` snapshot via atomic rebind; `BackgroundScheduler` | High | Phase 02 |
| 16 | App Review multi-week critical path hidden by 11d estimate: submit FRONT; eng-complete vs launch-ready milestones; min real-conversation volume before go-live | process (High) | Phase 06 / plan.md |
| 17 | Add tests for new guards: pricing-guard, single-flight, upsert-after-row-delete, Telegram secret-token, rate-limit, retention purge | process (High) | Phase 06 |

## External (non-code, parallel — business team)
- Submit Zalo OA business verification NOW (weeks-long).
- Request Messenger `pages_messaging` Advanced Access after internal test.
- Populate Google Sheet KB (<20 khóa) per template in Phase 02.
- Create Telegram tư-vấn-viên group + bot token.
- Provision public-HTTPS VPS for webhook.

## Out of scope (Pha 2)
`handle_objection`, `score_lead`, full multi-pass reflection loop, `web_research` (CUT permanently), Zalo OA live channel (interface scaffolded only), admin dashboard, in-bot payment. Adding these = new nodes/tools, no spine change.

## Naming convention (AUTHORITATIVE — read before creating files)
Phase docs show `.py` paths in **kebab-case** for readability, but Python cannot import hyphenated modules (`import app.kb.sheet-loader` = SyntaxError) and pytest won't collect `test-*.py`. Therefore:
- **Python source + test files → snake_case** (importability). Map every `.py` path in the phase docs by replacing `-`→`_`: e.g. `agent-node.py`→`agent_node.py`, `graph-builder.py`→`graph_builder.py`, `lead-tools.py`→`lead_tools.py`, `test-dedupe-store.py`→`test_dedupe_store.py`.
- **Non-Python files → kebab-case** as written: `docker-compose.yml`, `.env.example`, docs `*.md`, `*.sql`.
- Package dirs (`kb/`, `graph/`, `channel/`, `integrations/`, `handoff/`, `api/`, `db/`, `llm/`, `tests/`) each get `__init__.py`. Keep every `.py` < 200 LOC.

## Rollback (shared — greenfield standalone service)
No existing data/users to migrate (new service, own DB). Per-phase revert is uniform: `git revert` the phase commit + redeploy previous image; KB/vector store rebuilds from Sheet on boot (stateless); Postgres checkpoints restore via `pg_dump` backup (runbook, Phase 06). Phase 06 send-path changes are gated by `SHADOW_MODE` — flip to `true` to instantly stop user-facing sends without a deploy. No phase writes irreversible external state except Sheet rows (append/upsert — manually editable).

## Version caveat
Do NOT hard-pin researcher-reported versions. Install latest stable; verify at setup: model IDs `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-embedding-001`; packages `langgraph`, `langgraph-checkpoint-postgres`, `langchain-google-genai`.
