# Algorithms & Implementation Details — Tuyển Sinh Concierge (Pha 2)

> Mọi thuật toán, KB structure, guard logic, sales state machine (Pha 2 v2).
> Đọc để hiểu "cần test cái gì" + "non-obvious behaviors". Grammar-terse.

Stack: FastAPI + LangGraph + Gemini Flash/Flash-Lite + Google Sheets KB + Postgres + Telegram.
Golden rule: **bot không bao giờ tự chế học phí/ưu đãi/cam kết**.
323 tests pass (WSL). Catalog: 15 khóa in-context (phương án C, "full" mode ≤30).

---

## 0. Graph entry-to-exit (2026-07-26 v2 topology)

```
START → detect_objection (entry, reset per-turn counters)
    ↓ no_objection / repeat / escalate
    ├─→ ESCALATE → run_handoff_to_human (DB + Telegram) → END
    ├─→ REPEAT (2nd+ objection) → handle_objection → agent
    │       ↓
    │   agent → tool_exec → grade_chunks
    │       ├→ sufficient → reflect_node → pricing_guard → END
    │       └→ insufficient → fallback → reflect_node → END
    │
    └─→ NO_OBJECTION → agent → tool_exec → ...
```

**Entry node changes (v2):**
- `detect_objection_node` resets per-turn counters: `tool_rounds`, `reflect_count`, `objection_fix_done`, etc.
- Classifies objection type (fail-OPEN). ESCALATE routes to `run_handoff_to_human` (writes handoff_status DB + Telegram notify, not advisory).
- REPEAT routes to `handle_objection` for 1 reframe attempt.

**Defense-in-depth:** Agent (Flash) → tool_exec (retrieve/upsert) → grade (sufficiency) → reflect (promise gate) → pricing_guard (authoritative money gate) = each layer can block before send.

---

## 1. KB v2: 3-tab split + in-context catalog (`app/kb/`)

**Sheet schema (3 tabs):**
- **Courses**: 15 rows (course_id + 6 prose + 9 verbatim). No embed, entirely in-context.
- **Center**: ~10 center FAQs (topic, prose). Embedded in vector store.
- **FAQ**: ~50+ vendor FAQs (question, answer). Embedded in vector store.

**Parsing pipeline:**
1. `sheet_loader.load_kb()` reads all 3 tabs (replaces v1's `load_courses()`)
2. `cell_sanitizer.py` (NEW, split from course_parser.py for reuse): Trust gates + cell collectors
   - **Sanitization (C3 FIXED):** Patterns match against FOLDED text (accents removed). Injection-gate checks for imperative forms only (so "Chính sách & quy tắc lớp học" is ordinary, not quarantined).
   - `is_prose_cell_safe()` (allows newlines; forbids trust-marker/instructions) + `is_verbatim_cell_safe()` (no newlines) applied to all cells landing in prompt
3. `course_parser.py`: Per-course validation (re-exports sanitizers)
   - PROSE_FIELDS → in-context block
   - VERBATIM_FIELDS → `facts_map` (byte-identical)
   - Rows failing sanitization → quarantine + alert
3. `course_block_builder.py`: Fold into **index line** (25 tok) + **detail block** (440 tok, prose + marked facts)
4. `center_faq_parser.py`: Parse Center + FAQ → Document (doc_id, text)
5. `catalog_assembler.py`: Weave Index + Details into **system prompt** (~7K tokens for 15 courses)
6. `vector_store.py`: Embed Center + FAQ only. Build `facts_map` (course_id → all money/pct values)

**Atomic snapshot:**
`rebuild()` (5-min schedule, OFF event loop) reads sheet, parses, embeds Center+FAQ, then **1 GIL-held swap** of `_snapshot=(store, facts_map, metadata)`. Reader grabs snapshot once per turn → no half-state, no lock across network. Rebuild fail → retain last-good + alert.

**Growth path (unchanged at any scale):**
- ≤30: Full (Index + Detail in prompt)
- 30–80: Index mode (Index in prompt + `get_course_detail(cid)` tool, 0-token)
- >80: Future RAG on description; facts stay dict lookup (0 token, unaffected)

---

## 2. VN-numeral normalizer (`app/common/vn_numerals.py`, C2 FIXED)

**Goal:** All VN price formats → int VND for consistent matching (draft ↔ facts).

**Parsing order** (finditer, first match wins):
1. Percent: `\d+%`
2. Spelled-out millions (C2 FIXED): `bốn triệu rưỡi` → 4.5M via `milw` regex group + _WORD_DIGITS dict
3. Numeric millions: `X triệu [rưỡi|Y]` → `X*1e6 ± (0.5M if rưỡi) ± Y-fraction`
4. Thousands: `X nghìn|X ngàn|X k`
5. Grouped: `1.500.000`, `1,500,000` → strip separator
6. Bare: `\d{6,}` (≥100k). **Exclude** phone `^0\d{8,10}$`.

**False-positive guard:** Bare <6 digits without unit → ignored ("lớp 6", "2 buổi", "15/8" safe).

**Test:** `test_vn_numerals.py` (4tr5, bốn triệu rưỡi, phone skip, %).

---

## 3. Pricing Guard — fail-CLOSED deterministic gate (`app/graph/nodes/pricing_guard.py` + `guard_matching.py` + `guard_checks.py`)

**Input:** draft text + full course catalog (facts_map).
**Output:** `GuardVerdict(ok, violations, named_course_ids, quoted_price)`.

**Per-sentence binding (C1 FIXED):**
- Draft split on sentence boundaries (`_SEGMENT_SPLIT_RE` with lookaround to preserve "1.800.000")
- **Each sentence bound separately** to courses it names
- Multi-course in one sentence + money → blocked as ambiguous (_MULTI_COURSE, kind=AMBIGUOUS)
- Single-course sentence can inherit draft-level context binding only if draft-level is exactly 1 unambiguous course
- `_drop_shadowed` removes course whose ten_khoa is substring of another matched name (avoids shadowing)

**4-tier matching per-sentence:**
1. **Exact ten_khoa substring** → bind
2. **Alias keyword** (tu_khoa list, ≥4 chars, word-boundary, non-stopword FIXED) → bind
3. **≥3-char substring** → maybe (containment flag)
4. **Jaccard ratio** (after stripping money/date spans FIXED, need ≥2 name words FIXED)

**Pricing check:**
- Extract money/pct via `vn_numerals` (includes word-numerals: "mười lăm triệu", "một triệu tám", C2 FIXED)
- `check_money` runs on every bound sentence; `check_schedule` runs only if sentence NAMES the course (not inherited binding, to avoid blocking centre hours/trial slots)
- All tokens must ∈ that course's facts
- Multi-course + money → violation (no attribution)
- No course + money → violation (NO_COURSE)
- Computed discount not in facts → violation
- Free-claim without facts → violation

**Fail-closed:** Any violation → HONEST_FALLBACK + `handoff: True` (advisory) + NO changes to sales_stage (key diff from v1).

**DA_BAO_GIA write (H3 FIXED):** When verdict is OK and draft quoted a verified price for a bound course, `advance_stage()` to DA_BAO_GIA (via GuardVerdict.quoted_price). This enables phone-ask step next turn.

**Key architectural:** `state["handoff"]` is NOW READ by `message_dispatcher._invoke_graph` to distinguish "bot escalated itself this turn" (state["handoff"]=true) from "human owns thread for future turns" (handoff_status table). Authoritative gate for LATER turns: `handoff_status` table (set by real takeover). Guard does NOT write sales_stage (only real takeover does).

**Tests:** `test_guard_matching.py`, `test_guard_checks.py`, `test_pricing_guard.py`.

---

## 4. Reflect node — promise/tone gate + bounded repair (`app/graph/nodes/reflect_node.py`)

**Step 1 — blocklist:** Scan for forbidden clichés ("bao đậu", "cam kết đậu", "miễn phí 100%").

**Step 2 — LLM paraphrase (Flash-Lite):** If blocklist miss → structured `{ok, issues, fixed_reply}`.

**Step 3 — repair bounded (H6 FIXED, M2 FIXED):**
- If `fixed_reply` → apply + re-route to pricing_guard
- Else → bounce agent **once** (reflect_count ≤1) with ephemeral `fix_hint`
- After 1 repair, any violation → HONEST_FALLBACK + stamp `phone_asked_at` (M2 FIXED: phone-gate checks timestamp immediately after, so suppression timestamp doesn't survive the block)

**Per-turn reset (FIXED):** `reflect_count` + `objection_fix_done` reset by detect_objection_node on every inbound. Without this, repair paths die after turn 2.

**Test:** `test_reflect_node.py`.

---

## 5. Grade node + fallback (`app/graph/nodes/grade_node.py`, `fallback_node.py`)

`grade_chunks(retrieved, query) → {sufficient: bool, reason}` (Flash-Lite structured).

**Sufficient = false →** Fallback appends honest ("Cách em biết không đủ..."), sets `handoff: True` (advisory only), **does NOT change sales_stage** (that's reserved for real takeover). Flows to reflect for tone check.

**Sufficient = true →** Continue to reflect.

**Tests:** `test_grade_node.py`, `test_fallback_node.py`.

---

## 6. Sales stage machine (`app/graph/sales_stage.py`, `sales_playbook.py`)

**Canonical stages (v1 was free-text):**
```
MOI → DA_RO_NHU_CAU → DA_BAO_GIA → CO_SDT → DA_HEN_LICH → (terminal)
                                        ↘ HANDOFF (exit, absorbing)
```

**Progression:** `advance_stage(current, target)` = max by ORDER. HANDOFF is terminal (once set, stays).

**Write sites (H2 FIXED):**
- `pricing_guard`: Writes DA_BAO_GIA when verdict OK + price quoted (H3 FIXED)
- `capture_lead` tool: Writes CO_SDT when phone recorded
- `book_trial` tool: Writes DA_HEN_LICH
- Objection escalation (`run_handoff_to_human`): Writes HANDOFF (real takeover)
- NOT written by fallback or guard on block (intentional; see H2 below)

**Stage semantics (H2 clarified):**
- Corrective-RAG miss is routine (one per conversation expected). Setting stage=HANDOFF would kill elicitation permanently while bot still answers = confusing.
- Only real takeover (objection escalation / human resume) writes HANDOFF stage.
- Fallback/guard write advisory `handoff: True` field (not the stage).

**Playbook injection (sales_playbook.py):**
- Turn-specific elicitation based on current stage
- If HANDOFF stage → injects "tư vấn viên người thật tiếp quản"
- If DA_BAO_GIA → can ask for phone (guarded by 24h timestamp + absence of violation this turn)

**v1 compat:** `LEGACY_STAGE_MAP` reads old checkpoints ("đang tư vấn" → DA_RO_NHU_CAU). Never crashes on upgrade.

**Tests:** `test_sales_stage_writes.py`, `test_sales_playbook.py`.

---

## 7. Objection subsystem (`app/graph/nodes/detect_objection.py`, `handle_objection.py`, `prompts/objection_prompt.py`)

**Detect (entry node):** Flash-Lite classifier, fail-OPEN. Outputs: `{type: ESCALATE|REPEAT|NO_OBJECTION, confidence}`.

- SO_SANH_CHO_KHAC (competitor question) → ESCALATE always
- Same objection group 2nd time → ESCALATE (prevent bot arguing in circles)
- Else → REPEAT (attempt reframe) or NO_OBJECTION

**Route logic (H1 FIXED — no-op fixed):**
- ESCALATE → `run_handoff_to_human()` (writes handoff_status DB + Telegram notify). Real, not advisory.
- REPEAT → `handle_objection` node (1 reframe attempt via Flash + objection_prompt)
- NO_OBJECTION → normal flow

**Handle:** Reframe objection (1 attempt per turn). Fail → fallback.

**Per-turn reset (FIXED):** Detects resets ALL counters (tool_rounds, reflect_count, objection_fix_done, objection_count) on every inbound. Prevents "repair death after turn 2" (v1 bug).

**Tests:** `test_detect_objection.py`, `test_handle_objection.py`.

---

## 8. Tool execution + state mutation (`app/graph/nodes/tool_exec_node.py`, `tools/lead_tools.py`)

Tools return `ToolResult(message, state_update)`. Node wraps in ToolMessage, writes channels directly. No dangling ToolMessages (each tool_call gets a reply).

**Retrieval tool:** kb.retrieve (Center+FAQ) → route grade_chunks. `pricing_context` bị XÓA ở Ph02 (facts always-on trong prompt, không ghép theo hit).

**Capture_lead:** Upsert lead to Leads sheet, write CO_SDT stage (if phone recorded), route agent.

**Confirm_schedule:** Log date, write DA_HEN_LICH stage, route agent.

**Tool cap:** `tool_rounds` ≤4 per turn (reset by entry node). Exceed → fallback.

**Tests:** `test_tool_exec_node.py`.

---

## 9. Handoff system (H1 FIXED — escalation is real) (`app/handoff/`, `handoff_status_table.py`)

**Authoritative = `handoff_status` table,** not `state["handoff"]` field (advisory, no consumers).

**Columns:** psid, active, owner_id, last_user_ts, last_human_ts, reason_code.

**Atomic touch-before-check:** `before_invoke` calls `touch_user_and_get()` (upsert `last_user_ts=now()`, return prev values). If `active=true` AND silence gap >24h → auto-resume.

**TOCTOU re-check:** `before_send` re-reads `is_active` just before dispatch. Handoff flipped mid-turn → drop reply.

**Escalation write (H1 FIXED):** `run_handoff_to_human()` (called by objection escalation) writes handoff_status table + fires Telegram. No-op fixed.

**Resume:** Telegram `/resume messenger:PSID` clears row.

**Tests:** `test_handoff_resume.py`.

---

## 10. Metrics & shadow mode (`app/common/metrics_logger.py`, shadow_gate.py)

**Shadow mode:** `SHADOW_MODE=true` → `[DRAFT → PSID]` to Telegram debug channel, 0 real sends.

**Whitelist:** Phone (masked 0xxx***yy), draft, stage, course_id, etc. PII redaction enforced.

**Tests:** `test_metrics_logger.py`, `test_shadow_mode.py`.

---

## 11. Graph routing (H8 FIXED — now tested) (`tests/test_graph_wiring.py`)

`test_graph_wiring.py` compiles real graph, asserts every node registered, entry is detect_objection, every router destination is real, every reply-producing branch reaches pricing_guard.

**Langgraph installed in test env.** Routing maps verified at build time.

---

## 12. Test coverage

323 tests passing (WSL, Python 3.10):
- Pure functions: vn_numerals, vn_dates, course_parser, guard_matching, guard_checks, sales_stage
- Async (stubbed LLM): reflect, grade, detect_objection, lead_upsert, handoff_resume, dedupe, debounce, rate_limit
- Integration: metrics_logger, shadow_mode
- Graph wiring: test_graph_wiring (routes, nodes, entry, destinies)

---

## 13. Known open limitations (M-items, benign)

**M4:** `check_money` is set-membership. Deposit quoted as tuition possible (documented limit, guard still protects numbers).

**M8:** KB snapshot race (agent reads snapshot A, sync lands, guard reads snapshot B). Fails closed (safe), shows up as block-rate noise in metrics.

**N4:** Two courses quoted in ONE comma-joined sentence are blocked. Bullet/newline format is OK.

**Dangling tool_call:** If tool cap trips mid-turn and tool is in flight, no ToolMessage reply (pre-existing edge case).

---

## Unresolved questions

1. Multi-course quotes: Is "Khóa A và khóa B đều 3.000.000" valid sales tactic? Affects intersection vs fail-closed.
2. Prose cell sanitization: Should multi-line prose (`lo_trinh`) be allowed, or newline-reject-only?
3. Handoff field cleanup: `state["handoff"]` is now purely advisory (DB table is authoritative). Should the field be deleted?
4. Live Leads schema: Do columns L–Q already exist, or need appending?
5. Min volume before go-live: Coordinator recommends ≥50 conversations. Business consensus?
