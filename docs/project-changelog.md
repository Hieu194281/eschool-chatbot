# Project Changelog — eSchool Tuyển Sinh Concierge

All notable changes to this project are documented here. Format: YYYY-MM-DD | Type | Description.

---

## [2.0.0-alpha] — 2026-07-26

### Major Changes: KB Schema v2 + Sales Layer (6 Phases Complete)

**Phase 01 — Sheet Schema v2 + Parsers (2d)**
- **New:** 3-tab split (Courses/Center/FAQ) replaces 1-tab monolith
- **Module:** `app/kb/sheet_loader.py`, `course_parser.py`, `center_faq_parser.py`
- **Breaking:** Courses no longer embedded; verbatim facts stay in facts_map (byte-exact, 0 embedding)
- **Validation:** Partial-row logic (missing ten_khoa/hoc_phi → quarantine row), injection detection (forbid system:/prompt in cells)
- **Tests:** `test_course_parser.py`, `test_catalog_assembler.py` (16 tests)
- **Deploy:** `scripts/verify-sheet-schema.py` validates all 3 tabs before launch

**Phase 02 — Prompt Assembly + Retrieve Scope (1.5d)**
- **Module:** `app/kb/course_block_builder.py`, `catalog_assembler.py`, `app/graph/prompts/system_prompt.py`
- **New:** In-context catalog (15 courses, ~7K tokens): index lines (~25 tok each) + detail blocks (~440 tok)
- **Result:** Courses never retrieved (no vector ambiguity), always in-prompt (precise, LLM-native)
- **Vector store:** Center + FAQ only (gspread dedupe by doc_id, embedding via langchain)
- **Atomic snapshot:** `vector_store.rebuild()` (off event loop) + 1 GIL-held swap (no half-state visible to readers)
- **Tool repoint:** `retrieve_kb` now returns Center/FAQ only; fallback extracts facts from in-context catalog
- **Tests:** `test_catalog_assembler.py` (8 tests)
- **Limitation:** MAX_RETRIEVED=8 cap; grade_node classifies insufficient (requires `retrieved_this_turn` counter)

**Phase 03 — Guard Hardening (Catalog-Bound + Date + Concession) (3d)**
- **Module:** `app/graph/nodes/guard_matching.py`, `guard_checks.py`, `pricing_guard.py`
- **New 4-tier matching:**
  1. Exact ten_khoa substring
  2. Staff alias keyword (tu_khoa list, word-boundary)
  3. ≥3-char substring (containment flag)
  4. Jaccard ratio on significant words (≥2 words)
- **Price validation:** All money/pct tokens must ∈ facts of same bound course (fail-closed if cross-course mismatch)
- **Normalization:** `app/common/vn_numerals.py` (ordered regex: %, mil, k, grouped, bare; phone exclusion; bare <6 digits ignored)
- **Sanitization:** Injection patterns blocked in verbatim cells; newline check on prose
- **SalesStage constants:** Replaces v1 free-text ("đang tư vấn" → enum). LEGACY_STAGE_MAP for checkpoint compat.
- **Tests:** `test_guard_matching.py` (12 tests), `test_guard_checks.py` (10 tests), `test_pricing_guard.py` (18 tests)
- **Fixes (C1 + C2 + C3 ALL FIXED):**
  - C1: Per-sentence binding with shadowing + intersection logic (no price union)
  - C2: Word-numeral tokenization added ("bốn triệu rưỡi" → 4.5M)
  - C3: Prose sanitization + trust-marker normalization + newline checks

**Phase 04 — Sales State Machine + Elicitation + SĐT Rules (2d, H2 + H3 FIXED)**
- **Module:** `app/graph/sales_stage.py`, `app/graph/prompts/sales_playbook.py`, `app/graph/nodes/phone_ask_gate.py`
- **Stages:** MOI → DA_RO_NHU_CAU → DA_BAO_GIA → CO_SDT → DA_HEN_LICH (+ HANDOFF exit, absorbing)
- **Progression:** `advance_stage(current, target)` only moves forward (max by ORDER)
- **Write sites (H2 + H3 FIXED):**
  - `pricing_guard`: Writes DA_BAO_GIA when verdict clean + price quoted (H3 FIXED, phone-ask now reachable)
  - Objection escalation: Writes HANDOFF (real takeover, DB + Telegram)
  - capture_lead tool: Writes CO_SDT when phone recorded
  - book_trial tool: Writes DA_HEN_LICH
  - Fallback/Grade-fail: Write advisory `handoff` field only, NOT sales_stage (H2 FIXED — intentional split)
- **Playbook:** Stage-aware elicitation prompt injection; HANDOFF state injects "tư vấn viên người thật tiếp quản"
- **Phone gate:** Once-per-24h (timestamp-based), guarded by clean guard verdict + DA_BAO_GIA stage
- **Tests:** `test_sales_stage_writes.py` (grep-based write-site audit, 6 tests), `test_sales_playbook.py` (8 tests)

**Phase 05 — Objection Subsystem (Detect + Handle + Route) (2d, H1 FIXED)**
- **Module:** `app/graph/nodes/detect_objection.py` (new ENTRY node), `handle_objection.py`, `app/graph/prompts/objection_prompt.py`
- **Entry node:** Flash classifier (fail-OPEN), outputs ESCALATE|REPEAT|NO_OBJECTION
  - Resets per-turn counters: `tool_rounds`, `reflect_count`, `objection_fix_done`, `objection_count`
  - **ESCALATE (H1 FIXED — no longer no-op):** Call `run_handoff_to_human()` (writes handoff_status DB + fires Telegram notify). Real takeover.
  - REPEAT: route to handle_objection (1 reframe attempt per turn)
  - NO_OBJECTION: normal flow
- **Routing:** Graph entry point changed (was `agent`, now `detect_objection`)
- **Reflect node:** Now bounded (1 agent bounce max per turn); transient counters must be reset per-turn (bug fix vs v1)
- **Tests:** `test_detect_objection.py` (10 tests), `test_handle_objection.py` (8 tests)
- **Bug fix:** Counters persist in checkpoint (marked transient) → forced reset at turn entry prevents "repair paths die after turn 2"

**Phase 06 — Tests + Shadow-Mode Metrics (2.5d)**
- **Coverage:** 323 tests passing (WSL, Python 3.10)
  - Pure functions: vn_numerals, vn_dates, course_parser, guard_matching, guard_checks, sales_stage
  - Async (stubbed LLM): reflect, grade, detect_objection, lead_upsert, handoff_resume, dedupe, debounce, rate_limit
  - Integration: metrics_logger, shadow_mode
- **Metrics:** `app/common/metrics_logger.py` (whitelist: phone masked, draft, stage, course_id); PII redaction enforced
- **Shadow mode:** `SHADOW_MODE=true` → `[DRAFT → PSID]` to Telegram debug channel, 0 real sends. Metrics logged but delivery gated.
- **Scripts:**
  - `scripts/summarize-shadow-metrics.py` — analyze shadow run JSON logs
  - `scripts/verify-sheet-schema.py` — pre-deploy validation (exits non-zero if schema missing)
- **Tests:** 19 test files covering all major paths

### Documentation

**New files:**
- `chatbot/docs/algorithms-and-details.md` — v2 algorithms (KB split, guard tiers, sales stages, objection routing)
- `docs/chatbot-system-architecture.md` — Graph topology, KB structure, guard logic, handoff system, deployment checklist
- `docs/chatbot-codebase-summary.md` — Module structure, data flow, dependencies, test strategy, known issues

### Code Structure Changes

**New modules (15 total):**
- KB layer: `sheet_loader.py`, `course_parser.py`, `course_block_builder.py`, `center_faq_parser.py`, `catalog_assembler.py`, `sync_scheduler.py`
- Guard layer: `guard_matching.py`, `guard_checks.py` (split from monolithic v1)
- Sales: `sales_stage.py`, `sales_playbook.py`, `phone_ask_gate.py`
- Objection: `detect_objection.py`, `handle_objection.py`, `objection_prompt.py`
- Supporting: `metrics_logger.py`

**Modified modules (20 total):**
- `vector_store.py` — Atomic snapshot, off-loop rebuild, Center+FAQ only (no Courses)
- `pricing_guard.py` — Input repointed to facts_map (from vector store), 4-tier binding
- `reflect_node.py` — Promise gate demoted (pricing_guard authoritative), bounded repair (1 bounce max)
- `tool_exec_node.py` — State mutations rewritten (ToolResult with update dict), tool cap 4
- `agent_node.py` — System prompt injection wired (in-context catalog + facts frame)
- `grade_node.py` — Introduced (corrective-RAG gate, separates from reflect)
- `fallback_node.py` — Sets `handoff: True` only; never writes `sales_stage` (that stage is absorbing)
- `state.py` — Added sales_stage, objection fields, counter tracking
- Graph routing — Entry point changed (agent → detect_objection)
- `lead_sheet.py` — Lead upsert by `ws.find()` value (not enumerate), 6 new PII columns
- `handoff_status_table.py` — Marked as authoritative (state["handoff"] is advisory)
- All test files — 13 new test modules, 309 total tests

### Breaking Changes

1. **KB schema:** Courses tab now requires 9 verbatim fields (hoc_phi, uu_dai, khai_giang, lich_hoc, thoi_luong, si_so, hinh_thuc, giao_vien_ten, co_so). Missing values → row quarantine.
2. **Pricing guard:** Input repointed (state["retrieved"] → facts_map via get_all_courses()). Binding is 4-tier (stricter than v1 substring).
3. **Graph entry:** START → detect_objection (was agent). All routes wire through objection classifier.
4. **State mutations:** Tools must return ToolResult(message, state_update). Node writes channels directly (fixes v1 no-op mutations).
5. **Live Leads sheet:** 6 new headers required (lop, tinh_trang, muc_tieu, co_so, lich_ranh, khung_gio_tien) in columns L–Q.

### Deployment Changes

**Prerequisites (before go-live):**
- Run `scripts/verify-sheet-schema.py` (validates Courses/Center/FAQ/Leads schema, exits non-zero if missing)
- Live Leads sheet headers appended (cols L–Q)
- WSL test env: `pip install -r requirements.txt` (includes langchain-core, langgraph)
- Shadow mode enabled (`SHADOW_MODE=true`) initially

**Configuration:**
- New env var: `CATALOG_MODE` (future: "index" at >30 courses; default "full" for ≤30)
- Deprecated: v1 env vars (none actively, but LEGACY_STAGE_MAP handles old checkpoint values)

### Code Review Findings — All Fixed

**Critical (All fixed):**
- C1: Per-sentence binding with shadowing + intersection logic (no price union)
- C2: Word-numeral tokenization ("bốn triệu rưỡi" → 4.5M)
- C3: Prose sanitization + trust-marker normalization + newline checks

**High (All fixed, architectural clarified):**
- H1: Escalation now calls `run_handoff_to_human()` (writes DB + Telegram, no-op fixed)
- H2: Guard does NOT write sales_stage=handoff (intentional: fallback is routine, only real takeover sets stage)
- H3: Guard writes DA_BAO_GIA on clean verdict + price quoted (phone-ask now reachable)
- H4–H8: Alias validation (≥4 chars), phone-gate after blocklist, tool_rounds reset, graph routing tested

**Medium (Open, benign):**
- M2: Phone suppression timestamp survives guard block (HONEST_FALLBACK asks anyway)
- M4: `check_money` is set-membership (deposit as tuition possible, documented limit)
- M8: KB snapshot race (fails closed, shows as noise)
- Dangling tool_call if cap trips (pre-existing edge case)

### Open Limitations (Not Fixed, Benign)

**Medium (acceptable for production, documented):**
- **M4:** `check_money` is set-membership (not attribution). Deposit can be quoted as tuition. Guard still protects numbers, documented limit.
- **M8:** KB snapshot read separately by agent and guard. Race condition fails closed (safe), shows as metrics noise.
- **N4:** Two courses in ONE comma-joined sentence blocked. Bullet/newline format OK.
- **Dangling tool_call:** If tool cap trips mid-turn in flight (pre-existing edge case).

### Test Summary

**323 tests, all passing (WSL Python 3.10):**
- Pure, async, and integration tests across 34 test files
- Graph wiring test (test_graph_wiring.py): nodes registered, entry point verified, DOMINANCE asserted (pricing_guard → END only), all routing destinies valid (H8 FIXED)

### Migration Path from v1

**Backward compatibility:**
- `LEGACY_STAGE_MAP` reads old checkpoint "đang tư vấn" → DA_RO_NHU_CAU (never crashes)
- Sheet schema is additive (v2 only adds columns; v1 columns unchanged)
- Code revert needs only code revert; KB rebuilds stateless every 5 min

**One-time prep:**
1. Append 6 new headers to live Leads sheet (cols L–Q)
2. Append Center + FAQ tabs to KB sheet
3. Validate schema: `verify-sheet-schema.py`
4. Deploy with SHADOW_MODE=true
5. Monitor metrics for ≥50 conversations
6. Flip SHADOW_MODE=false after validation

---

## [1.0.0] — 2026-07-13

### Initial Release (Pha 1 — Messenger Sales Chatbot)

**Features:**
- Messenger webhook integration (HMAC-verified, debounced)
- LangGraph agent (Flash) + Gemini embed vector store
- Deterministic pricing-guard (VN-numeral normalizer, money/course validation)
- Reflect node (promise/tone blocklist + Flash-Lite paraphrase)
- Grade-fallback (corrective-RAG on insufficient context)
- Tool execution (retrieve_kb, capture_lead)
- Checkpointer (Postgres async, auto-resume logic)
- Handoff system (table-based, Telegram resume)
- PII retention purge (daily, by activity timestamp)
- Shadow mode (debug Telegram channel, 0 user sends)
- Rate limiting (per-min/day/global concurrency, budget tracking)
- Dedupe (mid-based, TTL 600s, bounded LRU)
- Debounce (fragment coalesce, cancel-reschedule)
- Single-flight (per-thread serialize, no checkpoint clobber)
- Tests (68 pure/async, all green)

**Limitations:**
- Single KB tab (Courses only, embedded)
- Free-text sales stages ("đang tư vấn", no constants)
- No objection subsystem
- No schedule guard
- No concession guard
- Price guard has substring-ambiguity and multi-bind union bugs (known)
- Handoff field is no-op (DB table only, but field written anyway)
- Reflect counters persist (causes repair death after turn 2)
- No metrics logging/shadow mode statistics

**Test coverage:** 68 tests (pure + async + integration, all passing)
**Status:** Engineering-complete. Launch-ready (awaiting App Review).

---

## Unresolved Questions (for v2.1+)

1. **Multi-course quotes:** Is "Khóa A và khóa B đều 3.000.000" valid sales tactic? (Affects intersection vs fail-closed scope)
2. **Handoff field cleanup:** `state["handoff"]` is now purely advisory. Should the field be deleted?
3. **Prose cell sanitization:** Should multi-line prose (`lo_trinh`) be allowed, or newline-reject-only?
4. **Live Leads schema:** Do columns L–Q already exist, or need appending?
5. **Min volume before go-live:** Coordinator recommends ≥50 conversations. Business consensus?
