# Chatbot Codebase Summary (v2)

**Last Updated**: 2026-07-26  
**Version**: 2.0.0-alpha (KB v2 + Sales Layer)  
**Test Coverage**: 323 tests passing (WSL, Python 3.10)  
**Status**: Shadow mode enabled, ready for field testing

---

## Project Structure

```
chatbot/
├── app/
│   ├── graph/
│   │   ├── nodes/              # 11 node implementations
│   │   │   ├── detect_objection.py        # Entry: classifies user objection
│   │   │   ├── agent_node.py              # Flash agent, system prompt injection
│   │   │   ├── tool_exec_node.py          # Execute tools, write state mutations
│   │   │   ├── grade_node.py              # Flash-Lite: context sufficient?
│   │   │   ├── fallback_node.py           # Honest admission on fail
│   │   │   ├── handle_objection.py        # Reframe objection (1 attempt)
│   │   │   ├── reflect_node.py            # Promise gate + repair loop
│   │   │   ├── pricing_guard.py           # Authoritative money/course gate
│   │   │   ├── guard_matching.py          # 4-tier course binding
│   │   │   ├── guard_checks.py            # Money token validation
│   │   │   └── phone_ask_gate.py          # 24h phone suppression
│   │   │
│   │   ├── prompts/
│   │   │   ├── system_prompt.py           # In-context catalog assembly
│   │   │   ├── sales_playbook.py          # Turn-by-turn elicitation
│   │   │   ├── objection_prompt.py        # Objection reframing
│   │   │   └── reflect_prompt.py          # Promise blocklist
│   │   │
│   │   ├── sales_stage.py                 # Stage machine (6 canonical stages)
│   │   ├── graph_builder.py               # LangGraph StateGraph construction
│   │   └── state.py                       # ConvState TypedDict schema
│   │
│   ├── kb/                                 # NEW: Knowledge base layer
│   │   ├── sheet_loader.py                # Load 3 Sheet tabs (replaces v1)
│   │   ├── course_parser.py               # Validate + split PROSE/VERBATIM
│   │   ├── course_block_builder.py        # Fold courses into index+detail
│   │   ├── center_faq_parser.py           # Parse Center tab → docs
│   │   ├── catalog_assembler.py           # Weave into system prompt
│   │   ├── vector_store.py                # Embed Center+FAQ, atomic snapshot
│   │   └── sync_scheduler.py              # 5-min rebuild schedule
│   │
│   ├── common/
│   │   ├── vn_numerals.py                 # Money normalization
│   │   ├── vn_dates.py                    # Date/schedule guard
│   │   ├── metrics_logger.py              # Whitelist logging + PII redaction
│   │   └── guard_types.py                 # Violation enum + verdict types
│   │
│   ├── channel/
│   │   ├── dedupe_store.py                # Message dedupe (TTL + LRU)
│   │   ├── debounce_buffer.py             # Fragment coalesce per user
│   │   ├── shadow_gate.py                 # Shadow mode (test harness)
│   │   └── message_dispatcher.py          # Single-flight dispatch
│   │
│   ├── api/
│   │   ├── webhook_messenger.py           # Messenger webhook handler
│   │   ├── webhook_telegram.py            # Telegram webhook + /resume
│   │   └── routes.py                      # FastAPI routes
│   │
│   ├── handoff/
│   │   ├── handoff_manager.py             # Handoff status CRUD
│   │   └── db/
│   │       └── handoff_status_table.py    # Postgres gate (authoritative)
│   │
│   ├── tools/
│   │   ├── lead_tools.py                  # capture_lead, book_trial
│   │   └── kb_tools.py                    # retrieve_kb
│   │
│   ├── db/
│   │   ├── retention_purge.py             # Daily PII purge (async task)
│   │   ├── lead_sheet.py                  # Google Sheets integration
│   │   └── log_redaction_filter.py        # Phone masking for logs
│   │
│   ├── llm/
│   │   └── retry.py                       # Gemini retry + backoff jitter
│   │
│   ├── main.py                            # FastAPI app, graph builder, scheduler
│   ├── config.py                          # Env var loading, validation
│   └── bootstrap.py                       # Logging setup, handlers
│
├── tests/                                  # 323 tests (pure + async + integration)
│   ├── test_vn_numerals.py
│   ├── test_vn_dates.py
│   ├── test_course_parser.py
│   ├── test_catalog_assembler.py
│   ├── test_pricing_guard.py
│   ├── test_guard_matching.py
│   ├── test_guard_checks.py
│   ├── test_reflect_node.py
│   ├── test_grade_node.py
│   ├── test_detect_objection.py
│   ├── test_handle_objection.py
│   ├── test_sales_stage_writes.py
│   ├── test_sales_playbook.py
│   ├── test_lead_upsert.py
│   ├── test_handoff_resume.py
│   ├── test_dedupe_store.py
│   ├── test_debounce_buffer.py
│   ├── test_metrics_logger.py
│   ├── test_shadow_mode.py
│   └── ... (19 more)
│
├── scripts/
│   ├── summarize-shadow-metrics.py        # Analyze shadow mode logs
│   └── verify-sheet-schema.py             # Pre-deploy sheet validation
│
├── .env.example                           # All required env vars (secrets redacted)
├── requirements.txt                       # Python 3.10+
├── pytest.ini
└── README.md
```

---

## Core Modules (v2 New)

### KB Layer (`app/kb/`)

| Module | Purpose | Dependencies |
|--------|---------|--------------|
| `cell_sanitizer.py` | Trust gates + sanitization (FOLDED text, unaccented patterns) | (pure) |
| `sheet_loader.py` | Read Courses/Center/FAQ tabs | gspread |
| `course_parser.py` | Validate rows, split PROSE/VERBATIM, re-exports sanitizers | (pure) |
| `course_block_builder.py` | Fold into index+detail blocks | (pure) |
| `center_faq_parser.py` | Parse Center/FAQ → Document | (pure) |
| `catalog_assembler.py` | Weave into system prompt | (pure) |
| `vector_store.py` | Embed Center+FAQ, atomic snapshot | langchain, async |
| `sync_scheduler.py` | 5-min background rebuild | apscheduler |

**Golden rule:** VERBATIM fields (hoc_phi, uu_dai, khai_giang, lich_hoc, thoi_luong, si_so, hinh_thuc, giao_vien_ten, co_so) → facts_map (byte-exact). PROSE fields (doi_tuong, muc_tieu, lo_trinh, chinh_sach, giao_vien_gioi_thieu, ghi_chu) → in-prompt (paraphrasable).

### Guard Layer (`app/graph/nodes/`)

| Module | Purpose | Tests |
|--------|---------|-------|
| `guard_matching.py` | 4-tier course name binding | `test_guard_matching.py` |
| `guard_checks.py` | Money/pct validation | `test_guard_checks.py` |
| `pricing_guard.py` | Orchestrate matching + checks | `test_pricing_guard.py` |

**Key:** `evaluate_draft(draft, courses) → GuardVerdict` is **pure** (no imports of langchain/tools). Node (`pricing_guard_node`) only imports lazily, wraps, handles failure.

### Sales Layer (`app/graph/`, `sales_stage.py`, `prompts/sales_playbook.py`)

| Module | Purpose |
|--------|---------|
| `sales_stage.py` | 6 canonical stage constants + `advance_stage()` |
| `prompts/sales_playbook.py` | Stage → elicitation prompt + actions |
| `nodes/phone_ask_gate.py` | 24h suppression + LLM ask decision |

**Stages:** MOI → DA_RO_NHU_CAU → DA_BAO_GIA → CO_SDT → DA_HEN_LICH (+ HANDOFF exit).

### Objection Subsystem (new, entry node)

| Module | Purpose |
|--------|---------|
| `nodes/detect_objection.py` | Entry node: classify + reset counters |
| `nodes/handle_objection.py` | Reframe objection (1 attempt per turn) |
| `prompts/objection_prompt.py` | Reframing template |

---

## Data Flow

### 1. Inbound Message

```
Messenger Webhook
  ↓ (webhook_messenger.py)
Verify HMAC, ACK 200 (sync)
  ↓ (BackgroundTasks, not bare create_task)
Process async:
  - Dedupe by mid (dedupe_store.py)
  - Coalesce fragments (debounce_buffer.py, cancel-reschedule timer)
  - Single-flight lock per thread_id
  ↓
LangGraph Invoke
  ↓
Graph (detect_objection → ... → pricing_guard → END)
```

### 2. Graph Execution

```
detect_objection_node (ENTRY)
  ↓ Reset per-turn counters
  ├─ none → agent (normal flow)
  ├─ gia_cao|suy_nghi|hoi_y_nguoi_khac|lich_ban → handle_objection (no tools bound)
  └─ so_sanh_cho_khac | same group 2nd time → run_handoff_to_human() + fallback
      ↓
  agent_node (Flash + system_prompt.py injection)
      ├─ tool_calls: retrieve_kb, capture_lead, book_trial
      ↓
  tool_exec_node (execute + state mutations)
      ↓ retrieve_kb path
  grade_node (Flash-Lite: sufficient context?)
      ├─ No → fallback_node (honest admission + handoff: True)
      └─ Yes → reflect_node
              ├─ blocklist match → HONEST_FALLBACK
              └─ no blocklist → Flash-Lite paraphrase
                  └─ fixed → apply + pricing_guard
                  └─ not fixed → agent bounce (1x) or HONEST_FALLBACK
                      ↓
                  pricing_guard (authoritative gate)
                      ├─ Ok → AIMessage
                      └─ Violation → HONEST_FALLBACK + handoff: True
                          ↓
                        END
```

### 3. Outbound Dispatch

```
Message ready (AIMessage or HONEST_FALLBACK)
  ↓
before_send (TOCTOU handoff re-check)
  ├─ handoff_status.is_active=true? → drop
  └─ No → proceed
      ↓
Rate limiter (per-PSID, per-day, global concurrency)
  ├─ Exceed → alert + degrade (no send)
  └─ OK → continue
      ↓
Shadow gate (SHADOW_MODE=true? → Telegram debug, 0 user send)
  ↓
Send adapter (Messenger / Telegram)
  └─ Split >1800 chars, 429 backoff
```

---

## Dependencies

### Production
- **langchain** — LLM orchestration, structured output
- **langgraph** — Graph + async checkpoints (Postgres)
- **google-cloud-vertexai** / **google-genai** — Gemini models
- **gspread** — Google Sheets API
- **python-dotenv** — Env var loading
- **fastapi**, **uvicorn** — Web framework
- **aiohttp**, **httpx** — Async HTTP
- **apscheduler** — Background scheduler (KB rebuild)
- **psycopg** — Postgres async driver

### Test
- **pytest**, **pytest-asyncio** — Test runner
- **pytest-cov** — Coverage
- **freezegun** — Time mocking
- **responses** — HTTP mocking

### Optional (for full end-to-end)
- **docker-compose** — Postgres + Redis
- **redis** — (Pha 2) Multi-worker state sharing

---

## Configuration

### Environment Variables (`.env.example`)

| Var | Purpose | Secret? |
|-----|---------|---------|
| `GOOGLE_SA_JSON_PATH` | Path to service account JSON | Yes |
| `GEMINI_API_KEY` | API key (or via gcloud auth) | Yes |
| `POSTGRES_DSN` | Async postgres:// | Yes |
| `SHEETS_KB_ID`, `SHEETS_LEADS_ID` | Sheet IDs | No |
| `MESSENGER_VERIFY_TOKEN` | Webhook verify token | Yes |
| `MESSENGER_APP_SECRET` | HMAC secret | Yes |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` | Debug channel | Yes |
| `SHADOW_MODE` | true (test) or false (prod) | No |
| `LANGGRAPH_STRICT_MSGPACK` | Always true | No |
| `LOG_LEVEL` | DEBUG/INFO/WARNING | No |

---

## Critical Files

### Gate Logic (Load-Bearing)
- `app/graph/nodes/pricing_guard.py` — Core authorization
- `app/kb/course_parser.py` — Injection defense (sanitize)
- `app/common/vn_numerals.py` — Consistent normalization

### State Machine
- `app/graph/sales_stage.py` — Stage progression
- `app/graph/state.py` — ConvState schema (MUST stay in sync with all readers)

### Persistence
- `app/handoff/db/handoff_status_table.py` — Authoritative handoff gate
- `app/db/lead_sheet.py` — Leads upsert (per-user lock, ws.find value-based)

### Channel Adapter
- `app/channel/message_dispatcher.py` — Single-flight lock (prevents concurrent checkpoint clobber)
- `app/api/webhook_messenger.py` — HMAC verify (constant-time)

---

## Test Strategy

### Pure Functions (no external deps)
- `test_vn_numerals.py` — Money normalization
- `test_vn_dates.py` — Date parsing
- `test_course_parser.py` — KB split, injection detection
- `test_guard_matching.py` — Course binding logic
- `test_guard_checks.py` — Money validation
- `test_sales_stage_writes.py` — Grep-based audit (validates write-sites exist)

### Async (no real Gemini/Postgres)
- `test_reflect_node.py` — Stub Flash-Lite → route
- `test_grade_node.py` — Stub Flash-Lite → verdict
- `test_detect_objection.py` — Stub classifier
- `test_dedupe_store.py`, `test_debounce_buffer.py` — Buffer logic
- `test_single_flight.py` — Lock behavior
- `test_handoff_resume.py` — Pure state machine + gate logic

### Integration (mocked LLM/DB)
- `test_lead_upsert.py` — Sheet operations (real ws.find, mocked gspread)
- `test_sales_playbook.py` — Playbook rendering

### NOT tested (no langgraph in CI)
- `app/graph/graph_builder.py` — Routing maps. Code review H8: add compile smoke test.

---

## Performance Characteristics

| Operation | Token Cost | Latency |
|-----------|-----------|---------|
| agent (Flash) | ~2000 tok/turn (proxy) | ~1s |
| grade (Flash-Lite) | ~500 tok | ~0.5s |
| reflect (Flash-Lite) | ~300 tok | ~0.5s |
| pricing_guard (pure) | 0 | <10ms |
| vn_numerals (pure) | 0 | <1ms |
| KB retrieve (vector store) | 0 (in-context, no retrieve needed) | <50ms |
| facts lookup (dict) | 0 | <1ms |

**Rate limit:** ~2000 tok/turn × 150 users/day ÷ 8h = ~20 concurrent, budget ~300K tok/day (adjust per pricing).

---

## Growth Path (Unchanged at any scale)

- ≤30: Full mode (15 courses index + detail in prompt, ~7K tok)
- 30–80: Index mode (add `get_course_detail(cid)` tool, still 0 token)
- >80: Reserve (future RAG on description; facts stay dict)

Facts lookup via `get_all_courses()` (O(n) memory, 0 token) always works, unaffected by scale.

---

## Code Review Findings — Status

**Critical (All FIXED):**
- C1: Per-sentence binding, shadowing check, intersection logic
- C2: Word-numeral tokenization (bốn triệu rưỡi now supported)
- C3: Prose sanitization + trust-marker normalization + newline checks

**High (All FIXED):**
- H1: Escalation now calls `run_handoff_to_human()` (writes DB + Telegram)
- H2: Guard does NOT write sales_stage=handoff (intentional architectural split)
- H3: Guard writes DA_BAO_GIA on clean verdict + price quoted
- H4–H8: Alias validation, phone-gate placement, tool_rounds reset, graph routing test all fixed
- M2 (NEW): Pricing guard stamps `phone_asked_at` when substituting HONEST_FALLBACK; reflect routes through phone gate (FIXED)

**Medium (Open, benign):**
- M4: `check_money` is set-membership (deposit quoted as tuition possible, documented limit)
- M8: KB snapshot race (fails closed, shows as metrics noise)
- N4: Two courses in ONE comma-joined sentence blocked (bullet/newline format OK)
- Dangling tool_call: If tool cap trips mid-turn (pre-existing edge case)

---

## Deployment

**Prerequisites:**
- [ ] Postgres running (docker-compose up -d)
- [ ] Live Leads sheet schema migrated (6 new cols L–Q)
- [ ] `verify-sheet-schema.py` passes
- [ ] WSL env: `pip install -r requirements.txt`

**Launch:**
```bash
SHADOW_MODE=true python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Monitoring:**
- Shadow metrics: `python scripts/summarize-shadow-metrics.py log.json`
- Logs (redacted): `tail -f app.log | grep -v PHONE`

---

## Unresolved Questions

1. Multi-course quotes: valid product or fail-closed only?
2. DA_BAO_GIA write site: where intended?
3. `state["handoff"]` vs table: should field be deleted?
4. Live Leads cols L–Q: added manually or auto-sync needed?
5. Prose cell sanitization: full or newline-only?
