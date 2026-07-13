# Phase 03 — LangGraph Brain (Graph, Tools, Reflect-Lite)

## Context Links
- Plan: [plan.md](plan.md)
- Prev: [phase-02-kb-layer-sheet-sync-vectorstore.md](phase-02-kb-layer-sheet-sync-vectorstore.md)
- Stack ref: `researcher-260707-0012-langgraph-gemini-stack.md` §1 (StateGraph, AsyncPostgresSaver), §2 (Gemini)
- Decisions: `brainstorm-260707-0012-*.md` §3.1, §3.2, §4, §6
- State/tools/prompt: `2026-07-06-tuyensinh-concierge-brainstorm.md` §5, §6, §7 (golden rule)

## Overview
- **Priority:** P1
- **Status:** completed
- **Effort:** ~3d
- Build the single LangGraph StateGraph: agent node (Gemini 2.5 Flash + bind_tools loop), Corrective-RAG (retrieve_kb → grade_chunks Flash-Lite → honest fallback), reflect-lite (1 pass), tools (capture_lead/book_trial/handoff_to_human), AsyncPostgresSaver checkpointer. System prompt enforces golden rule (never invent pricing/commitments).

## Key Insights
- **One brain, channel-agnostic.** Graph receives normalized `{user_id, channel, text}`; adapters (Ph04) call `graph.ainvoke` with `thread_id={channel}:{user_id}`.
- Checkpointer persists ENTIRE state (messages + lead_profile + handoff). No custom load_memory/save_history nodes (deleted from original design).
- **Corrective-RAG, not full reflection:** grade decides sufficient vs fallback. Insufficient → honest fallback line + set handoff. `web_research` CUT permanently.
- **Deterministic pricing-guard (authoritative price gate):** LLM prompt + reflect-lite are advisory only — the ENFORCED golden rule is a deterministic `pricing-guard` node that runs before send. It regex-extracts every number/currency token in the draft, normalizes VN numerals, and verifies each is a member of the pricing string of the SPECIFIC course named (price bound to `course_id`, not "present anywhere in k=3 context"). Number not in matched course's pricing → fail closed.
- **Reflect-lite DEMOTED = 1 pass, Flash-Lite, fuzzy promise/tone ONLY.** Numeric enforcement moved to deterministic pricing-guard. Reflect-lite catches paraphrased forbidden-promises/tone; a deterministic regex blocklist is first-line for known promise phrases. Fail → fix once → send. Not a loop.
- Pricing arrives from KB layer as verbatim structured string — agent must quote, never compute/alter. **Model FORBIDDEN from computing discounted prices** (e.g. 5tr−10%): only prices pre-computed in the Sheet are stateable.
- Pha 2 nodes (handle_objection, score_lead, full reflect) are NOT built — graph shape leaves room (linear, easy to insert).

## Requirements
**Functional**
- `ConvState` + `LeadProfile` TypedDicts hold all persisted fields.
- Agent node loops tool-calls until final text (bounded max iterations).
- `retrieve_kb(query)` tool → KB layer; returns chunks + verbatim pricing block.
- `grade_chunks` (Flash-Lite) classifies retrieved context sufficient/insufficient for the question.
- Insufficient → honest fallback reply ("để em nhờ tư vấn viên phản hồi") + `handoff=True`.
- `capture_lead`, `book_trial`, `handoff_to_human` tools callable by agent (impl detail in Ph05; here define signatures + wire). **State-mutating tools (handoff/capture) MUST actually write state channels** — a plain `-> str` return CANNOT set `handoff`/`sales_stage`, so use `Command(update={...})` or a post-tool node (fix below).
- `pricing_guard` node (deterministic) runs on final draft before send: every price token must belong to the named course's pricing; else strip number / force honest-fallback + handoff. FORBIDS model-computed discounts.
- `reflect_lite` node validates final draft for forbidden-promise/tone ONLY (fuzzy, paraphrase); one fix attempt on fail. Deterministic regex blocklist runs first.
- Compiled graph uses `AsyncPostgresSaver`; `thread_id` from config.

**Non-functional**
- Files <200 LOC; split state / graph / nodes / tools / prompts.
- Bounded latency: agent loop cap (e.g. 4 tool rounds), Flash-Lite for grade+reflect.
- Deterministic-ish: low temp for grade/reflect (0), moderate for agent.
- **LLM retry/backoff:** each turn issues 2-4 Gemini calls; wrap each Gemini call (or the whole invoke) in bounded retry with jitter on 429/5xx/timeout. A failed turn MUST NOT leave the user's HumanMessage dangling/unanswered in the checkpoint — roll back or re-queue on give-up.

## Architecture
```
ConvState (persisted by checkpointer)
  messages[], user_id, channel, retrieved[], lead_profile, sales_stage,
  reflect_count, handoff, pricing_context (verbatim, per-turn)

Graph:
  START → agent
  agent ──(tool_call: retrieve_kb)──> retrieve_kb → grade_chunks
                                          │ sufficient → agent (with chunks+pricing)
                                          │ insufficient → fallback (set handoff, canned line) → reflect_lite
  agent ──(tool_call: capture_lead/book_trial/handoff_to_human)──> tool_exec → post_tool(writes state channels) → agent
  agent ──(final text)──> reflect_lite → pricing_guard → END
  reflect_lite: pass → pricing_guard ; fail(once) → agent(fix hint) → reflect_lite
  pricing_guard: all prices ∈ named-course pricing → END
                 offending number → strip / honest-fallback + handoff → END   (deterministic, fail-closed)
```
Order rationale: reflect_lite (fuzzy promise/tone) THEN pricing_guard (deterministic, authoritative) as the last gate before send — nothing reaches Send API unchecked.

### State (state.py)
```python
class LeadProfile(TypedDict):
    ten: str | None
    sdt: str | None
    khoa_quan_tam: str | None
    nhu_cau: str | None
    do_nong: str            # "lạnh"|"ấm"|"nóng"  (set heuristically Ph1, scored Ph2)

class ConvState(TypedDict):
    messages: Annotated[list, add_messages]
    user_id: str
    channel: str            # "messenger" (|"zalo" later)
    retrieved: list         # [{text, course_id, pricing}]
    pricing_context: str    # verbatim block for current turn
    lead_profile: LeadProfile
    sales_stage: str        # mới|đang tư vấn|đã xin SĐT|đã chốt|cần người
    reflect_count: int
    handoff: bool
```

### Nodes
- **agent** (`nodes/agent-node.py`): `ChatGoogleGenerativeAI(GEMINI_MODEL_MAIN).bind_tools([...])`; system prompt (golden rule) + messages + injected `pricing_context`. If tool_calls → route to tool; else → reflect_lite.
- **retrieve_kb** wrapped as tool; on result, node builds `pricing_context` from hits' verbatim pricing.
- **grade_chunks** (`nodes/grade-node.py`): Flash-Lite structured output `{sufficient: bool, reason: str}`; input = user question + retrieved text. sufficient→back to agent; else→fallback.
- **fallback** (`nodes/fallback-node.py`): append canned honest line, `handoff=True`, `sales_stage="cần người"` → reflect_lite (still reflects the canned line for tone; cheap).
- **reflect_lite** (`nodes/reflect-node.py`): Flash-Lite structured output `{ok: bool, issues: [str], fixed_reply: str|None}`. **Scope DEMOTED to forbidden-promise/tone ONLY** (number checking moved to pricing_guard). First-line = deterministic regex blocklist of promise phrases ("đảm bảo đậu","cam kết giỏi","chắc chắn","miễn phí 100%",...); Flash-Lite catches paraphrases the regex misses. `ok`→pricing_guard. Not ok & `reflect_count==0`→increment, feed `issues` to agent for one fix. `reflect_count>=1`→send safest (use `fixed_reply` or strip offending claim) to avoid infinite loop.
- **pricing_guard** (`nodes/pricing-guard.py`) — DETERMINISTIC, authoritative price gate, runs last before END:
  1. Regex-extract every currency/number token from the draft reply.
  2. Normalize VN numerals on BOTH draft and pricing context first: `triệu`/`tr`/`củ`→×1e6, `k`/`nghìn`→×1e3, `"4tr5"`→4,500,000, etc.
  3. Identify the course named in the draft → its `course_id` → its verbatim pricing string. Verify each price token is a member of THAT course's pricing (price bound to course_id — NOT merely "appears somewhere in k=3 context"; that lets right-number-wrong-course slip through).
  4. Reject model-computed discounts (a number derivable from a KB price ± % that is not itself a literal Sheet value → fail).
  5. Any offending number → fail closed: strip the number OR replace draft with honest-fallback line + `handoff=True`. Never send an unverified price.

### Tools (tools/*.py — signatures here, impl Ph05)
```python
@tool retrieve_kb(query: str) -> list      # read-only → knowledge_base.retrieve; str/list OK
# STATE-MUTATING tools MUST write ConvState channels, not just return a string:
@tool capture_lead(...) -> Command         # Command(update={"lead_profile":..,"sales_stage":..})
@tool book_trial(sdt, slot, khoa) -> Command
@tool handoff_to_human(reason: str) -> Command  # Command(update={"handoff": True, "sales_stage":"cần người"})
```
- **CRITICAL FIX:** a tool returning plain `str` CANNOT mutate `ConvState` → `handoff`/`sales_stage` never flip → handoff becomes a silent no-op (bot keeps replying). Use LangGraph tools returning `Command(update={...})` (current LangGraph API) to write state channels. If the installed version's tool→Command path is unavailable, use a dedicated **post_tool node** that inspects tool results/messages and writes `handoff`/`sales_stage` into state. **Verify the exact state-mutation API at setup** (Command-from-tool vs post-tool node) and pick one.
- read-only tools (`retrieve_kb`) still return values the agent relays; only state-mutating tools need the Command/post-tool path.

### System prompt (prompts/system-prompt.py) — golden rule (first-class)
- Persona: nữ tư vấn viên tuyển sinh, thân thiện, tiếng Việt.
- **Nguyên tắc vàng (bắt buộc):** CHỈ nói học phí/ưu đãi/lịch từ dữ liệu KB được cung cấp trong `pricing_context`/retrieved. TUYỆT ĐỐI không tự chế số liệu. Không có trong KB → dùng câu honest-fallback + để handoff.
- **TUYỆT ĐỐI KHÔNG tự tính giá sau giảm** (vd 5tr−10%). Chỉ nêu con số đã có sẵn trong Sheet; muốn giá ưu đãi thì đọc đúng ô `uu_dai`. (Prompt-level only; enforced deterministically by pricing_guard.)
- Con số học phí phải thuộc ĐÚNG khóa đang nói tới — không lấy giá khóa A gán cho khóa B.
- CẤM cam kết "đảm bảo đậu/giỏi/điểm cao".
- Xin SĐT tự nhiên trong mạch tư vấn (lý do: gửi lịch/ưu đãi), rồi gọi `capture_lead`.
- Gọi `handoff_to_human` khi: khách đòi gặp người, khiếu nại, hỏi ngoài KB, lead nóng cần chốt tay.
- Trả lời ngắn gọn, hợp Messenger (tránh tường chữ).

### Checkpointer (graph-builder.py)
- **LIFECYCLE FIX (HIGH):** `AsyncPostgresSaver.from_conn_string(...)` is an **async context manager**. Storing its result and reusing it across the app lifetime closes the underlying pool on `__aexit__` → every later `ainvoke` fails on the first real message. Do NOT `from_conn_string(...)` then drop the context.
  - **Option A (preferred):** enter the context manager inside FastAPI lifespan and keep it open for the whole app lifetime: `async with AsyncPostgresSaver.from_conn_string(dsn) as saver: await saver.setup(); app.state.graph = build(saver); yield` (pool stays open until shutdown).
  - **Option B:** construct the saver from an explicitly-managed long-lived `AsyncConnectionPool` you open at startup and `close()` on shutdown; pass that pool to the saver.
- `await saver.setup()` once at startup; `graph = builder.compile(checkpointer=saver)`.
- Invoke: `await graph.ainvoke({"messages":[HumanMessage(text)], "user_id":..,"channel":..}, config={"configurable":{"thread_id": f"{channel}:{user_id}"}})`.
- Set env `LANGGRAPH_STRICT_MSGPACK=true` (deser hardening).

## Related Code Files
**Create**
- `chatbot/app/graph/state.py` — ConvState + LeadProfile TypedDicts
- `chatbot/app/graph/graph-builder.py` — StateGraph wiring, edges, compile, checkpointer, `get_graph()`
- `chatbot/app/graph/nodes/agent-node.py`
- `chatbot/app/graph/nodes/grade-node.py`
- `chatbot/app/graph/nodes/fallback-node.py`
- `chatbot/app/graph/nodes/reflect-node.py` (demoted: promise/tone only)
- `chatbot/app/graph/nodes/pricing-guard.py` — deterministic price-token gate (VN-numeral normalize, price↔course_id binding, fail-closed)
- `chatbot/app/graph/nodes/post-tool-node.py` — writes state channels from tool results IF Command-from-tool path not used (fix #2)
- `chatbot/app/graph/tools/retrieve-kb-tool.py`
- `chatbot/app/graph/tools/lead-tools.py` (capture_lead, book_trial, handoff_to_human — impl in Ph05, stub returning confirmation now)
- `chatbot/app/graph/prompts/system-prompt.py`
- `chatbot/app/graph/prompts/grade-prompt.py`, `reflect-prompt.py`
- `chatbot/app/llm/gemini-clients.py` — cached `main_llm()`, `lite_llm()` factories

**Modify**
- `chatbot/app/main.py` — lifespan: `await saver.setup()`, build+hold compiled graph

## Implementation Steps
1. `gemini-clients.py`: cached `ChatGoogleGenerativeAI` for main (temp ~0.6) and lite (temp 0).
2. `state.py`: define TypedDicts with `add_messages` reducer on `messages`.
3. `retrieve-kb-tool.py`: `@tool` → `knowledge_base.retrieve(query,k=3)`; return list incl verbatim pricing per hit.
4. `agent-node.py`: bind tools; build message list = [system prompt] + state messages + (pricing_context as system/human context if present); return updated messages; expose routing condition (has tool_calls?).
5. `grade-node.py` + `grade-prompt.py`: Flash-Lite `.with_structured_output(GradeResult)`; input question+chunks; return `{sufficient}`; conditional edge sufficient→agent, else→fallback.
6. `fallback-node.py`: append canned Vietnamese honest line, `handoff=True`, stage="cần người".
7. `reflect-node.py` + `reflect-prompt.py`: Flash-Lite structured `ReflectResult{ok, issues, fixed_reply}`; **forbidden-promise/tone ONLY** (deterministic regex blocklist first, LLM for paraphrase); loop guard via `reflect_count`. (Number checking removed — now in pricing_guard.)
7b. `pricing-guard.py`: deterministic. Build VN-numeral normalizer (util, shared with parser if handy). Extract number/currency tokens from draft; resolve course named in draft → `course_id` → verbatim pricing; normalize both sides; assert each token ∈ that course's pricing set; reject computed discounts. On any miss → strip number or swap to honest-fallback + set `handoff=True`. Pure/deterministic → heavily unit-tested (Ph06).
8. `lead-tools.py`: define `@tool` signatures returning **`Command(update={...})`** for state-mutating tools (capture_lead/book_trial/handoff_to_human) so `handoff`/`sales_stage`/`lead_profile` actually persist; `retrieve_kb` stays read-only. Ph01/Ph03 stub bodies still return a Command with a confirmation message; Ph05 fills real Sheet/Telegram/Calendar logic (same file). **At setup, verify the Command-from-tool API**; if unavailable, add `post-tool-node.py` to write channels from tool results instead.
9. `graph-builder.py`: assemble nodes+edges per diagram (agent → reflect_lite → pricing_guard → END; tool path via post_tool if used); compile with checkpointer; `get_graph()` singleton. Wrap each Gemini call (agent/grade/reflect) in bounded retry-with-jitter on 429/5xx/timeout; on final give-up, ensure the turn does not leave a dangling unanswered HumanMessage (roll back / re-queue / emit soft-fail line).
10. `main.py` lifespan: enter `AsyncPostgresSaver.from_conn_string(...)` as an `async with` (or open a long-lived `AsyncConnectionPool`), `await saver.setup()`, construct graph, `yield`, close pool on shutdown (fix #3 — do NOT drop the context manager after construction).
11. Local harness: invoke graph with fake message via a script; verify tool loop, grade fallback path, reflect-lite fix path, **pricing_guard rejects wrong-course/promo-derived/`miễn phí` numbers**, **handoff_to_human actually flips `ConvState.handoff`**, checkpoint persistence across two calls (same thread_id remembers), and a simulated 429 retries instead of losing the turn.

## Todo List
- [ ] `gemini-clients.py` cached main/lite LLMs; model IDs from config
- [ ] `state.py` ConvState + LeadProfile
- [ ] `retrieve-kb-tool.py` → KB retrieve incl verbatim pricing
- [ ] `agent-node.py` bind_tools loop + routing + pricing injection
- [ ] `grade-node.py` Flash-Lite sufficiency classifier
- [ ] `fallback-node.py` honest line + handoff flag
- [ ] `reflect-node.py` promise/tone ONLY: deterministic regex blocklist + LLM paraphrase, loop guard
- [ ] `pricing-guard.py` deterministic: VN-numeral normalize, price↔course_id binding, reject computed discounts, fail-closed
- [ ] `system-prompt.py` golden rule persona + no-compute-discount + right-course-only
- [ ] `lead-tools.py` state-mutating tools return `Command(update=…)` (verify API); `post-tool-node.py` fallback if needed
- [ ] LLM retry-with-jitter around Gemini calls (429/5xx/timeout); no dangling HumanMessage on give-up
- [ ] `graph-builder.py` compile + reflect_lite→pricing_guard edge + strict msgpack
- [ ] `main.py` lifespan: `async with` AsyncPostgresSaver (pool kept open, closed on shutdown)
- [ ] Harness verifies: tool loop, fallback, reflect fix, pricing_guard rejects (wrong-course/promo/`miễn phí`), handoff flips state, cross-turn memory, 429 retry

## Success Criteria
- Same `thread_id` remembers prior turn (checkpointer works) without custom memory nodes.
- Question with KB coverage → answer quotes verbatim pricing exactly; no invented numbers.
- Question outside KB → honest fallback + `handoff=True` (no hallucinated answer).
- Draft containing a number absent from the named course's pricing → pricing_guard strips/replaces before send (deterministic).
- **Promo-derived price** (e.g. 5tr−10% → "4tr5" not literally in Sheet) → pricing_guard rejects.
- **Course A's price quoted for Course B** → pricing_guard rejects (price bound to course_id).
- **"miễn phí" with no KB basis** → rejected (regex blocklist + pricing_guard).
- Draft with "đảm bảo đậu" (or a paraphrase) → reflect-lite rejects → fixed.
- **After `handoff_to_human`, `ConvState.handoff` is `True`** (Command/post-tool wrote the channel) and the Ph04 dispatcher gate sees it (no silent no-op).
- Agent loop cannot exceed max rounds (no infinite tool loop).
- A Gemini 429/5xx/timeout mid-turn is retried; on final failure the user's message is not left dangling/unanswered.

## Risk Assessment
| Risk | L×I | Mitigation |
|---|---|---|
| Agent invents pricing despite prompt | Med×High | Deterministic pricing_guard (fail-closed, price↔course_id) as authoritative gate + verbatim pricing_context + shadow mode (Ph06). Prompt/reflect are advisory only |
| Right-number-wrong-course price slips through | Med×High | pricing_guard binds each price token to the named course's `course_id`, not "anywhere in k=3 context" |
| Model computes discounted price (5tr−10%) | Med×High | Prompt forbids; pricing_guard rejects any number not literally in the course's Sheet pricing |
| State-mutating tool no-ops (handoff never flips) | Med×High | Tools return `Command(update=…)` or post-tool node writes channels; verify API at setup; success-criteria test asserts `handoff==True` |
| AsyncPostgresSaver context-manager closed → all invokes fail | Med×High | Keep `from_conn_string` context open for app lifetime (`async with … yield`) or long-lived pool closed on shutdown |
| Gemini 429/5xx/timeout loses turn + dangling HumanMessage | Med×High | Bounded retry-with-jitter per call; roll back / re-queue on give-up |
| Reflect-lite infinite loop | Low×High | `reflect_count` guard: max 1 fix, then send safest |
| Agent tool-call loop runaway | Low×Med | Max iteration cap in agent routing |
| grade false-negative (says insufficient when KB has it) | Med×Med | Tune grade prompt; log grade decisions; shadow mode review |
| Model ID / structured-output API drift | Med×Med | Model IDs in config; verify `.with_structured_output` + Command-from-tool at setup |

## Security Considerations
- Golden rule = first-class requirement, ENFORCED by the deterministic pricing_guard (authoritative, fail-closed); prompt + reflect-lite are advisory defense-in-depth, not the guarantee.
- No secrets in prompts. GOOGLE_API_KEY via env only.
- `LANGGRAPH_STRICT_MSGPACK=true` to restrict checkpoint deserialization.
- PII (SĐT) enters `lead_profile` only when user provides it; persisted in checkpoint (Postgres) — Postgres access controlled (Ph01/Ph06).

## Next Steps
- Unblocks Phase 04 (adapter invokes `get_graph().ainvoke`).
- Phase 05 fills real bodies of capture_lead/book_trial/handoff_to_human in `lead-tools.py`.
- Pha 2: insert handle_objection/score_lead/full-reflect as new nodes — spine unchanged.
