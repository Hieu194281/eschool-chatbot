# Tuyển Sinh Concierge — System Architecture (v2)

**Last Updated**: 2026-07-26 (KB v2 + Sales Layer - Phase 2 complete)
**Status**: 323 tests passing (WSL). Shadow mode enabled by default.
**Scope**: Messenger chatbot. LangGraph-based agent with KB v2 split, sales state machine, objection subsystem.

---

## 1. High-Level Architecture

```
┌─ Messenger Webhook ──┐
│  (webhook_messenger) │
└──────┬──────────────┘
       │ HMAC verify → dedupe → debounce
       ↓
┌─────────────────────┐     ┌─ Postgres ─┐
│  LangGraph Invoke   │────→│ Checkpoints │
│  (before_invoke)    │     │ + Leads     │
└──────┬──────────────┘     └─────────────┘
       │ auto-resume check
       ↓
┌─────────────────────────────────────────┐
│  Graph: detect_objection → agent → ...  │
│         → pricing_guard → reflect → END │
└──────┬──────────────────────────────────┘
       │ rate-limit → shadow-gate or send
       ↓
    Telegram (debug) or Messenger (prod)
```

**Layers:**
1. **Channel Adapter** (Messenger webhook + HMAC + ACK)
2. **Buffer & Dedupe** (fragment coalesce, once-per-mid)
3. **Graph Engine** (LangGraph async invoke with checkpoints)
4. **KB + Guard** (in-context catalog + facts lookup)
5. **Dispatch** (rate-limit → shadow-gate → send adapter)

---

## 2. Knowledge Base Layer (v2)

### 2.1 Sheet Schema (3-tab split, replaces v1)

| Tab | Content | Embed? | In-Prompt? |
|-----|---------|--------|-----------|
| **Courses** (15 rows) | course_id + 9 verbatim (pricing, dates, teacher) + 6 prose | No | Yes (Index + Detail) |
| **Center** (~10) | FAQ about center (address, policy, process) | Yes | No |
| **FAQ** (50+) | Vendor FAQs | Yes | No |

### 2.2 Data Flow

**Sheet → KB:**
```
load_kb()
  ├─ cell_sanitizer.py: gates + sanitization (FOLDED text, unaccented patterns)
  │
  ├─ Courses Tab
  │   ├─ course_parser.py: validate (course_id, ten_khoa, hoc_phi required)
  │   ├─ Inject: PROSE → in-prompt block; VERBATIM → facts_map (byte-exact)
  │   └─ Sanitize: is_prose_cell_safe + is_verbatim_cell_safe
  │
  ├─ Center Tab
  │   ├─ center_faq_parser.py: parse row → Document(doc_id, text)
  │   └─ Embed in vector store
  │
  └─ FAQ Tab
      ├─ center_faq_parser.py: parse Q/A → Document (same module as Center)
      └─ Embed in vector store
```

**Assembly:**
- `course_block_builder.py`: Fold 15 courses into **index lines** (25 tok each) + **detail blocks** (440 tok)
- `catalog_assembler.py`: Weave into system prompt (~7K tokens total, fit ≤30 courses)
- `vector_store.py`: Embed Center + FAQ only (Courses not retrieved, in-context via system prompt)

### 2.3 Growth Path (unchanged at any scale)

- ≤30 courses: Full mode (all Index + Detail in prompt)
- 30–80: Index mode (Index in prompt + `get_course_detail(cid)` tool, 0-token)
- >80: Future RAG on descriptions only; facts stay dict lookup

### 2.4 Atomic Snapshot

**Rebuild** (5-min schedule, off event loop):
- Load sheet (gspread)
- Parse all 3 tabs
- Build `facts_map` (course_id → money/pct tokens)
- Embed Center + FAQ
- **1 GIL-held swap:** `_snapshot = (vector_store, facts_map, metadata, version)`

**Reader** (agent/guard):
- Grab `_snapshot` once per turn
- No lock across network I/O
- No half-state visible

**Fail:** Retain last-good snapshot + alert. Never serve stale data after successful rebuild.

---

## 3. Graph Topology (v2 entry + routes)

### 3.1 Entry Point: Detect Objection Node

New in v2. Runs first, resets per-turn counters.

**Input:** Latest user message (HumanMessage)
**Classifier:** Flash-Lite, structured output, fail-OPEN (any error → `none`)
**Output:** `objection_type` ∈ `{none, gia_cao, suy_nghi, hoi_y_nguoi_khac, lich_ban, so_sanh_cho_khac}`

**Routes** (`route_after_detect`):
- `none` → `agent` (normal flow)
- `gia_cao` / `suy_nghi` / `hoi_y_nguoi_khac` / `lich_ban` → `handle_objection`
- `so_sanh_cho_khac`, OR the same group a 2nd time → `fallback`, and the node calls
  `run_handoff_to_human` (handoff table + Telegram). Never generates a reply about a competitor.

Classification is biased toward `none`: a false positive turns an ordinary question into a
defensive reply, which is worse than a miss (the normal branch answers correctly anyway).

**Key behavior:** `turn_reset()` clears `tool_rounds`, `reflect_count`, `objection_fix_done`,
`fix_hint`, `route_hint`, `retrieved_this_turn` on every user message — they are checkpointed,
so without this the caps apply to the whole CONVERSATION. `objection_count` is deliberately
NOT reset; it is the repeat detector.

### 3.2 Agent Node

**Input:** User query, optionally kb.retrieve() call from tool
**Model:** Gemini Flash
**Tools bound:** `retrieve_kb`, `capture_lead`, `book_trial`

**System prompt injection** (2 ephemeral messages):
1. Catalog: In-context 15-course index + detail blocks
2. Frame: "Use facts block as [SỐ LIỆU CHÍNH THỨC]"

**Output:** AIMessage with optional tool_calls

### 3.3 Tool Exec Node

**Tool implementations:**
- `retrieve_kb`: Search vector store (Center + FAQ only); returns {text, source, doc_id, course_id}. `pricing_context` was DELETED in Ph02 — facts are always-on in the prompt
- `capture_lead`: Upsert lead to Leads sheet + update sales_stage
- `book_trial`: Log trial lesson date + set sales_stage=DA_HEN_LICH

**State mutations:** Tools return `ToolResult(message, state_update)`. Node **writes channels directly** (not dangling updates).

**Tool cap:** `tool_rounds` ≤4 per turn. If exceeded → fallback.

### 3.4 Grade Node (post-tool)

**Classifier:** Flash-Lite, `{sufficient: bool, reason}`
**Evaluates:** Retrieved chunks + user query
**Sufficient=false:** Route to fallback
**Sufficient=true:** Route to reflect

### 3.5 Fallback Node

Inserts the honest admission line and sets `handoff: True`. It does **NOT** touch `sales_stage`: a corrective-RAG miss is routine, and that stage is absorbing, so writing it would permanently kill elicitation while the bot keeps answering.

### 3.6 Reflect Node (promise/tone gate)

**Step 1:** Deterministic blocklist (regex: "bao đậu", "cam kết đậu", etc.)
**Step 2:** Flash-Lite paraphrase if blocklist miss
**Step 3:** Bounded repair (1 agent bounce max per turn)
**Fail:** HONEST_FALLBACK + handoff: True (sales_stage untouched)

**Non-obvious:** Counters `reflect_count`, `objection_fix_done` must be **reset at turn entry** or repairs die after turn 2.

### 3.7 Pricing Guard (authoritative gate)

**Input:** Draft + the WHOLE catalog (`knowledge_base.get_all_courses()` — dict walk, 0 token, so the guard sees every course at any catalog size or mode)
**Process (per SENTENCE, not per draft):**
1. Bind the sentence to a course — tiers 1-3 (course_id / ten_khoa / alias) are unioned, then span-aware shadow-drop; tier 4 (word overlap ≥0.8, money+date spans stripped first) fires only if 1-3 are empty and exactly one course qualifies
2. Sentence naming ≥2 courses + money → block (un-attributable). Naming none → inherit the draft-level binding only if that is exactly one unambiguous course
3. Money/pct extraction (VN numerals incl. word forms) → membership test against THAT course's facts
4. `check_schedule` only where the sentence names the course itself — an inherited binding may be centre hours, a trial slot or a call-back window
5. Concession check across the whole draft
6. Fail-closed: any violation → HONEST_FALLBACK + `handoff: True` + `phone_asked_at` stamped

**Key — two different handoff signals:**
- `handoff_status` **table** = authoritative gate for FUTURE turns (written by `run_handoff_to_human` and by objection escalation).
- `state["handoff"]` = read once per turn by `message_dispatcher` to tell "the graph escalated itself this turn" from "a human took over mid-invoke".

The guard does **not** write `sales_stage`. That stage is absorbing, and a blocked draft (expected a few % of the time) would otherwise permanently disable elicitation. On a CLEAN verdict that quoted a verified price it writes `sales_stage=da_bao_gia`, which is what unlocks the ask-for-phone rung.

### 3.8 End (send)

TOCTOU re-check via `before_send`: is `handoff_status` still active? If yes mid-turn → drop the reply — **unless** the graph raised `state["handoff"]` itself, in which case the reply is delivered. Escalation writes the table during the invoke, so without that exception paging a human would also swallow the bot's own goodbye and the customer would get silence. Otherwise send (via shadow-gate or adapter).

---

## 4. Sales State Machine

**Canonical stages** (no free-text, constants in `sales_stage.py`):
```
MOI (new) → DA_RO_NHU_CAU (know class + need) → DA_BAO_GIA (quoted price)
  → CO_SDT (have phone) → DA_HEN_LICH (scheduled) → terminal
                            ↘ HANDOFF (exit, absorbing)
```

**Progression:** `advance_stage(current, target)` → max by ORDER (only moves forward or stays). HANDOFF is terminal.

**Write sites (H2 + H3 Fixed):**
- `pricing_guard`: Writes DA_BAO_GIA when verdict is clean AND draft quoted verified price for bound course (H3 FIXED)
- `capture_lead` tool: Writes CO_SDT (when phone recorded)
- `book_trial` tool: Writes DA_HEN_LICH
- Objection escalation (`run_handoff_to_human`): Writes HANDOFF (real takeover, DB table + Telegram)
- Fallback / Grade-fail: Write advisory `handoff: True` field, **do NOT write sales_stage** (intentional, see §5.4)

**Playbook injection** (`sales_playbook.py`):
- Renders turn-specific elicitation prompt based on current stage
- If HANDOFF: "tư vấn viên người thật đang tiếp quản"
- If DA_BAO_GIA + no phone yet: can ask (guarded by 24h timestamp)

**v1 Compat:** `LEGACY_STAGE_MAP` reads old checkpoints ("đang tư vấn" → DA_RO_NHU_CAU). Never crashes on upgrade.

---

## 5. Pricing Guard Detail

### 5.1 Per-Sentence Binding (C1 Fixed)

Draft split on sentence boundaries (lookaround preserves "1.800.000"). **Each sentence bound separately** to courses it explicitly names.

- Multi-course + money in same sentence → blocked as ambiguous (_MULTI_COURSE violation, kind=AMBIGUOUS)
- Single-course sentence can inherit draft-level context only if draft is exactly 1 unambiguous course
- `_drop_shadowed` removes course whose name is substring of another matched (avoids shadowing)

### 5.2 4-Tier Matching Per-Sentence (C3 Fixed Aliases)

| Tier | Method | Example |
|------|--------|---------|
| 1 | exact `ten_khoa` substring | "Toán 9" → bind |
| 2 | staff alias (≥4 chars, word-boundary, FIXED) | tu_khoa=["math"] → bind |
| 3 | ≥3-char substring | "Toa" might match "Toán" |
| 4 | Jaccard (strip money/date FIXED, ≥2 name words FIXED) | draft words overlap course name |

### 5.3 Money/Pct Extraction (`vn_numerals.py`, C2 Fixed)

**Ordered patterns** (first match wins):
1. `\d+%` → percent
2. **Spelled-out millions (C2 FIXED):** "bốn triệu rưỡi" → 4.5M via word-digit regex groups
3. Numeric millions: `X triệu [rưỡi|Y]` → millions ± half ± fraction
4. `X nghìn|X ngàn|X k` → thousands
5. `1.500.000` or `1,500,000` → grouped
6. `\d{6,}` bare (≥100k, exclude phone)

**False-positive guard:** Bare <6 digits without unit → ignored (safe).

### 5.3 Membership Check (`guard_checks.py`)

```
for each token T in draft money/pct:
  for each bound course C:
    if T not in facts_map[C]:
      violation(kind="cross_course_price")
      → return ok=False
```

**Special cases:**
- Computed discount (5M−10%=4.5M) not in facts → reject
- Free-claim without facts support → reject
- No course named + money present → reject (no_course)

### 5.4 Fail-Closed Behavior (H2 Fixed)

Any violation → replace AIMessage with HONEST_FALLBACK + **set handoff: True** (advisory field) + **do NOT change sales_stage** (key architectural difference).

Why not write sales_stage=handoff on guard block? Guard block is routine (incorrect phrasing, minor mismatch). Setting the terminal stage would kill elicitation forever while bot keeps answering = confusing. Only real takeover (objection escalation / human resume) writes HANDOFF stage. See §4 Sales State Machine.

---

## 6. Objection Subsystem

### 6.1 Detect (Entry Node, H1 Fixed)

**Classifier:** Flash-Lite, fail-OPEN. Outputs `ObjectionResult(type, confidence)`; `type` is one of
`none | gia_cao | suy_nghi | hoi_y_nguoi_khac | lich_ban | so_sanh_cho_khac`.

**Cases (escalation is now real, not advisory):**
- `so_sanh_cho_khac`, or the same group a 2nd time (`objection_count[type] >= 1`) → `run_handoff_to_human()`
  (writes the handoff_status row + fires Telegram) then routes to `fallback`. Real takeover, no generated reply.
  The customer still receives the honest line — the dispatcher skips its TOCTOU drop when the graph itself
  raised `state["handoff"]`.
- Any of the four handled groups, first occurrence → `handle_objection`.
- `none` → `agent`, normal flow.

### 6.2 Handle

**Flow:** `handle_objection` builds the system prompt (catalog + centre + sales playbook) plus the group's
DO/DON'T block from `objection_prompt.OBJECTION_PLAYBOOK`, calls Flash with **no tools bound** (the catalog
is already in context), and exits through `reflect_lite → pricing_guard` like any other draft. `gia_cao`
may quote `Center["Trả góp"]` verbatim; it may never invent a discount — `guard_checks.check_concession`
enforces that deterministically.

**Bounded:** 1 fix per turn (governed by `objection_fix_done` counter, reset by detect_objection).

### 6.3 State Counters

**Reset per-turn by detect_objection_node:**
- `tool_rounds` (tool call cap)
- `reflect_count` (promise-gate repairs)
- `objection_fix_done` (objection reframe attempts)
- `objection_count` (duplicate tracker)

This prevents "repair paths die after turn 2" bug from v1.

---

## 7. Handoff System (Authoritative DB Gate)

### 7.1 Table: `handoff_status`

**Columns:** `psid, active, owner_id, last_user_ts, last_human_ts, reason_code`

**Authoritative for future turns:** This table is the gate for whether bot answers on LATER turns. `ConvState.handoff` is NOW READ by dispatcher to distinguish "bot escalated itself THIS TURN" (state["handoff"]=true) from "human owns thread GOING FORWARD" (handoff_status table).

### 7.2 Atomic Touch Before Check

`before_invoke` calls `touch_user_and_get()`:
- Atomic SQL CTE: upsert `last_user_ts = now()`
- Return prev values
- Check: if `active=true` AND silence gap >24h (no recent `last_human_ts`) → auto-resume

### 7.3 TOCTOU Re-Check Before Send

`before_send` re-reads `is_active` just before dispatch. Handoff flipped mid-turn → drop reply.

### 7.4 Resume

Telegram `/resume messenger:PSID` command clears the row.

**Non-obvious:** Fallback/guard writing `sales_stage=handoff` does NOT write `handoff_status` table. That's a separate, deliberate mismatch: stage signals "degraded this turn"; table says "human owns thread now". Different semantics, intentional separation.

---

## 8. Metrics & Shadow Mode

### 8.1 Shadow Mode

`SHADOW_MODE=true` → All user-facing messages:
1. HTML-escaped `[DRAFT → PSID]` → Telegram debug channel
2. **Zero real sends** to end user

**Metrics still logged** (JSON), but delivery gated off.

### 8.2 Whitelist Logging

Whitelist in `metrics_logger.py`. PII redaction:
- Phone: `0xxx***yy`
- User ID: hashed
- Keep: stage transitions, course selection, draft content

---

## 9. Channel Adapter (Messenger)

### 9.1 Webhook Lifecycle

1. **Verify:** HMAC-SHA256 constant-time check of `X-Hub-Signature`
2. **ACK:** Sync respond 200 (before processing)
3. **Async Process:** FastAPI `BackgroundTasks` (drained on shutdown, not bare `create_task`)
4. **Dedupe:** OrderedDict + TTL (600s) + bounded LRU (maxsize evict oldest)
5. **Debounce:** Coalesce fragments per user (DEBOUNCE_SECONDS timer, cancel-reschedule)
6. **Single-flight:** `asyncio.Lock[thread_id]` wraps invoke → serialize same-thread

### 9.2 Rate Limiting

**Sliding window per PSID:**
- Per-minute cap
- Per-day cap
- Global concurrency `Semaphore`
- Spend counter (proxy ~2000 tok/turn)

**Exceed:** Alert + degrade (don't send, log only).

### 9.3 Send

- Typing indicator on
- Split >1800 chars
- 429 backoff (exponential jitter)

---

## 10. Database Layer

### 10.1 Postgres

**Purpose:** Checkpoint (LangGraph AsyncPostgresSaver) + Handoff table + optional Leads mirror (redundant with Sheets, for fast queries).

**Lifecycle:** `async with AsyncPostgresSaver.from_conn_string(dsn) as saver: await saver.setup(); set_graph(build_graph(saver))`. Context stays open lifetime of app.

**Safety:** No dangling pool closes. `LANGGRAPH_STRICT_MSGPACK=true`.

### 10.2 Leads Sheet Integration

**Source:** Google Sheets (multiple tabs). Upserted by `capture_lead` tool.

**Columns:** user_id, name, phone, class, status, goal, center, availability, time-window + 6 new (lop, tinh_trang, muc_tieu, co_so, lich_ranh, khung_gio_tien).

**Locate:** `ws.find(value)` (not enumerate) → staff can delete mid-sheet without clobbering.

**Lock:** Per-user lock before upsert.

**PII retention:** Purged daily by `retention_purge.py` (uses `handoff_status.last_user_ts` as activity clock).

---

## 11. Deployment Prerequisites

- [ ] Live Leads sheet has 6 new headers (cols L–Q)
- [ ] Run `scripts/verify-sheet-schema.py` (exits non-zero if schema missing)
- [ ] WSL test env: `pip install -r requirements.txt` (includes langchain-core, langgraph)
- [ ] Shadow mode enabled (`SHADOW_MODE=true`)
- [ ] Flip to false only after ≥50 conversations

---

## 12. Code Review Findings — Status

**Critical (All FIXED):**
- **C1:** Per-sentence binding + shadowing check + intersection logic (see §5.1)
- **C2:** Word-numeral tokenization added (bốn triệu rưỡi) (see §5.3)
- **C3:** Prose sanitization + trust-marker normalization (see §1 KB)

**High (All FIXED except architectural clarifications):**
- **H1:** Escalation now calls `run_handoff_to_human()` (writes DB + Telegram, not advisory anymore)
- **H2:** Guard does NOT write sales_stage=handoff (see §5.4 rationale)
- **H3:** Guard writes DA_BAO_GIA on clean verdict + price quoted (see §4 Sales Stage)
- **H4–H7:** Alias length/boundary + phone-gate placement + tool_rounds reset all fixed
- **H8:** Graph routing now tested in `test_graph_wiring.py` (langgraph installed in test env)

**Medium (Open, benign):**
- **M4:** `check_money` is set-membership. Deposit quoted as tuition possible (documented limit)
- **M8:** KB snapshot race (fails closed, shows as metrics noise)
- **N4:** Two courses in ONE comma-joined sentence blocked (bullet/newline format OK)
- **Dangling tool_call:** If tool cap trips mid-turn (pre-existing edge case)

---

## 13. Test Coverage

**323 tests passing (WSL Python 3.10)**

**Graph routing tested:** `test_graph_wiring.py` asserts DOMINANCE (pricing_guard is only predecessor of END), plus node registration, entry point, and routing destinations (H8 FIXED)

**No gaps:** End-to-end requires live Gemini/Postgres/Sheets (not on Windows host)

---

## Unresolved Questions

1. Multi-course quotes: Is "Khóa A và khóa B đều 3.000.000" valid sales tactic? (Affects intersection vs fail-closed scope)
2. Handoff field cleanup: `state["handoff"]` is now purely advisory (DB table authoritative). Should the field be deleted?
3. Prose cell sanitization: Should multi-line prose (`lo_trinh`) be allowed, or newline-reject-only?
4. Live Leads schema: Do columns L–Q already exist, or need appending?
5. Min volume before go-live: Coordinator recommends ≥50 conversations. Business consensus?
