# Red-Team Review - Tuyen Sinh Concierge Pha 1

**Date:** 2026-07-07 | **Type:** adversarial review | **Reviewer stance:** hostile
**Target:** plans/260707-0048-tuyensinh-concierge-pha1/ (plan.md + 6 phases)
**Mandate:** find what blows up in implementation/production. No praise.

Counts: **3 CRITICAL, 6 HIGH, 12 MEDIUM, 3 LOW.**

---

## CRITICAL

### C1 - No per-user serialization of graph invocations; checkpointer race + overlapping replies
**What breaks:** Debounce (Ph04) uses cancel-and-reschedule per user. But _flush reads parts, clears buffer, then awaits on_flush (graph.ainvoke, 5-15s). New fragments arriving DURING that await create a fresh buffer + fresh timer, so a SECOND graph.ainvoke fires on the SAME thread_id while the first is still running. AsyncPostgresSaver is not built for concurrent writes to one thread_id.
**Scenario:** User sends greeting, 6s flush, turn A starts (retrieval+reflect, 12s). At t+8s user sends a pricing question, new 6s window, turn B starts at t+14s while A still finishing. Both write checkpoints for messenger:PSID: lost-update, interleaved history, two replies out of order. Root cause of double lead capture (H9), handoff-gate bypass (H6), out-of-order sends.
**Phase:** phase-04 (debounce-buffer, message-dispatcher), phase-03 (checkpointer).
**Fix direction:** per-user asyncio.Lock (or serial queue) around the whole flush-graph-send; a new flush for a user waits for the prior to finish (or re-buffers into it).

### C2 - Pricing anti-hallucination guard is an LLM and fails OPEN
**What breaks:** Golden rule (never invent pricing) is enforced by reflect-lite, a Flash-Lite LLM emitting {ok, issues, fixed_reply}. A probabilistic checker guarding a probabilistic generator: it can hallucinate ok:true on a wrong number (miss). On repeat failure the guard sends the safest option (fixed_reply or strip offending claim), which can still emit a possibly-wrong number. No deterministic assertion that every currency figure in the reply is a literal substring of pricing_context.
**Scenario:** Agent renders 5.500.000d (typo of 5.000.000). Flash-Lite reflect passes it (LLMs are bad at digit-diffing). Wrong price sent to a paying customer is the exact disaster the architecture exists to prevent. Or reflect flags it, the fix rewrites to another wrong value, reflect_count>=1, fail-open, sent anyway.
**Phase:** phase-03 (reflect-node).
**Fix direction:** add a DETERMINISTIC code check: regex-extract all numeric/currency tokens from the draft, normalize, assert each appears in pricing_context/retrieved; on any miss fail-CLOSED, replace with honest-fallback + handoff. Use the LLM reflect only for tone/promises.

### C3 - RAG mis-retrieval injects WRONG-course pricing as official, reflect passes it
**What breaks:** retrieve_kb appends get_pricing(course_id) for whatever course the vector search hit, flagged official/immutable. grade_chunks checks sufficiency, not identity. If the semantic hit is the wrong course (easy with near-duplicate names), the wrong tuition is injected verbatim. The reflect-lite number check sees the figure IS present in the (wrong) context, so it passes. Confident, verbatim, wrong price.
**Scenario:** User asks about IELTS 6.5; retriever returns the IELTS 5.0 chunk (closest embedding); bot quotes IELTS 5.0 tuition as official for 6.5. Every safety layer greenlights it because the number is technically in context.
**Phase:** phase-02 (retrieve/get_pricing), phase-03 (grade, reflect).
**Fix direction:** inject pricing only when the target course is disambiguated (confirmed course_id / exact-name match), not top-k similarity; grade must verify retrieved course == asked course. Direct consequence of RAG-over-in-context for a tiny KB (see H8).

---

## HIGH

### H4 - Synchronous blocking calls in single-worker event loop defeat the <5s ACK decoupling
**What breaks:** Single uvicorn worker + async, but the processing path contains SYNC blocking network I/O: gspread (get_all_records, update), similarity_search calling embed_query (Gemini network), embeddings. Any of these on the one event loop blocks ALL concurrent coroutines, including reading/ACKing the next webhook POST. The ACK-then-async decoupling only holds if nothing in processing blocks the loop; it does.
**Scenario:** User A turn embeds a query (1-2s sync) or lead-upsert reads the whole Sheet (1-3s sync). During that block, a second user webhook POST cannot be ACKed within the Meta ~5s window, Meta retries, duplicate event, (empty/lazy dedupe) double processing. Under real concurrency everything serializes.
**Phase:** phase-02 (retrieve), phase-04 (dispatcher/webhook), phase-05 (sheets).
**Fix direction:** wrap all sync calls in asyncio.to_thread/executor, or use async clients; never hold the loop across network I/O. Also do not hold the KB RLock across similarity_search (grab ref, release, then search).

### H5 - No outage observability + no dead-letter/retry, silent lost leads
**What breaks:** ACK 200 fires before processing. Any exception after ACK (graph error, Gemini 429, dispatcher bug) means the message is silently dropped; Meta will not retry a 200ed event. Buffered fragments in the debounce dict are lost on restart/deploy. NO alerting for process-down, KB-sync-fail-after-startup, or dropped inbounds; Telegram alerts cover only KB-sync errors and repeated send failures. Silent lead loss on a live revenue bot.
**Scenario:** A 2pm deploy restarts uvicorn; 4 users mid-debounce, messages vanish, no reply, no trace. Or Gemini throttles 5 min, every inbound throws post-ACK, dozens ignored, nobody notified.
**Phase:** phase-04 (ACK/async), phase-06 (ops).
**Fix direction:** process-up/health alert to Telegram; wrap processing so any failure sends a soft retry line or re-queues; consider a tiny persistent inbound queue. At minimum alert on any dispatcher exception, not just send failures.

### H6 - Handoff dual source of truth desyncs; /resume clears table but not persisted graph state
**What breaks:** Handoff lives in TWO places: the handoff bool in ConvState (checkpointer) AND the handoff_status Postgres side-table. Dispatcher gates on the side-table; the agent reasons on the state flag. /resume and auto-resume call handoff_manager.clear (side-table only). Checkpointed handoff=True is never cleared, so next turn the agent restores handoff=True and behaves as handed off.
**Scenario:** Human resolves, types /resume, side-table cleared, bot un-gated. User asks a new question, graph loads checkpoint (handoff=True), agent keeps saying wait-for-consultant forever. Set/clear across two stores can also partially fail, gate and agent disagree.
**Phase:** phase-05 (handoff-manager, resume-command), phase-03 (state).
**Fix direction:** single source of truth. Gate off checkpoint state, or have clear() also patch graph state. Do not split the flag.

### H7 - No Gemini quota/429/timeout handling, LLM errors drop messages
**What breaks:** Plan handles Send API 429 and gspread backoff, but nothing for Gemini rate-limits/timeouts on agent/grade/reflect/embed. langchain default retry not configured. On quota spike, calls raise, post-ACK exception, silent drop (H5).
**Scenario:** Ad campaign spike; Gemini 429s; every 3rd message throws mid-graph; users get nothing; no alert.
**Phase:** phase-03 (gemini-clients), phase-02 (embeddings).
**Fix direction:** retry-with-backoff on LLM/embedding clients; catch quota errors, honest-fallback + handoff + alert, not a crash.

### H8 - Corrective-RAG + vector store + embeddings + grade is over-engineered for <20 courses that fit in context
**What breaks:** The whole KB is 20-40K tokens, trivially inside the Flash window. The pipeline (Sheet-chunk-embed-InMemoryVectorStore-retrieve-grade) adds an embedding subsystem, a sync/rebuild subsystem, thread-safety concerns, per-message embed+grade latency/cost, and the mis-retrieval-to-wrong-pricing failure class (C3), none of which exist if the whole KB is stuffed into context. Brainstorm 3.1 shows KB-in-context was proposed and the user overrode it; flagged regardless because it is the root cause of C3, half of H4, and much complexity.
**Scenario:** Every path that would be a dict lookup becomes a semantic search that can miss/mis-hit; the grade LLM exists purely to paper over retrieval on a corpus too small to need it.
**Phase:** phase-02, phase-03 (whole design).
**Fix direction:** reconsider KB-in-context for Pha 1 (all courses in context; pricing = structured dict keyed by course_id). Keep RAG only if the KB will soon exceed context. If RAG stays, make pricing a deterministic confirmed-course_id lookup, never a similarity by-product.

### H9 - Lead upsert read-then-write by row index is a TOCTOU; staff edits corrupt the wrong lead
**What breaks:** upsert_lead does get_all_records() then enumerate(start=2) then ws.update on a computed row range. The row index comes from a stale read. Staff routinely edit the Leads sheet (mark contacted, delete spam). An insert/delete between read and write shifts indices, so the update overwrites a DIFFERENT lead row. Two concurrent captures both read not-found, both append, duplicate rows despite upsert (compounded by C1).
**Scenario:** Two leads processed near-simultaneously, both appended (dup). Or staff deletes row 3 while bot updates row 5 (now row 4), bot overwrites the wrong customer phone number.
**Phase:** phase-05 (lead-sheet).
**Fix direction:** locate the row at write time by key (ws.find / batch match on channel_user_id), not a cached index; serialize upserts per user; or append-only + dedup on read.

---

## MEDIUM

### M10 - Empty/blank hoc_phi not validated, bot presents blank official pricing
Parser only checks course_id non-empty. If staff clears/mid-edits hoc_phi, pricing_map[id] becomes a blank official string that gets injected as fact. Phase-02. Fix: validate hoc_phi non-empty; if blank mark pricing unavailable, force fallback, never quote blank.

### M11 - Empty vector store cold-start floods handoff
Startup rebuild fails only if totally unreadable. If it returns 0 valid docs (wrong worksheet name, all rows malformed), the store is empty but startup succeeds, every question grades insufficient, fallback+handoff, Telegram flood + zero answers, silently. Phase-02. Fix: alarm loudly if doc count is 0 / below a floor; refuse to go live.

### M12 - Debounce/dedupe not persisted; dedupe dict is an unbounded memory leak
In-flight fragments lost on restart (see H5). Dedupe dict[mid-expiry] with lazy prune on access never re-accesses a unique mid, grows forever. Phase-04. Fix: active periodic sweep for dedupe; log/alert on restart with non-empty buffers.

### M13 - APScheduler threading-vs-asyncio decision unmade
Plan says BackgroundScheduler or AsyncIOScheduler (either). AsyncIOScheduler runs the blocking rebuild on the loop, blocks ACKs every 5 min. BackgroundScheduler runs it in a thread, InMemoryVectorStore/embeddings touched cross-thread while async readers hit it. Phase-02. Fix: pick one deliberately: thread executor for the blocking rebuild + async-safe swap, retrieve off the loop (H4).

### M14 - AsyncPostgresSaver context-manager lifecycle in lifespan
from_conn_string(...) is an async context manager owning a pool. If entered/exited within lifespan startup (the common async-with-as-saver mistake), the pool closes before requests run, pool-closed errors on ainvoke. Phase-03. Fix: enter at startup, store saver, exit only on shutdown; pin pool config.

### M15 - Latency budget likely exceeds the 15s target on retrieval+reflect turns
A typical message is ~3 Flash + 2 Flash-Lite + 1 embed sequentially; a reflect retry adds 2 more. At 1-2s/call that is 8-15s, blowing <15s on any reflect retry, worse under H4 serialization. Phase-03/06. Fix: parallelize where possible, cap turns, budget-test; skip reflect on chit-chat with no numbers.

### M16 - No inbound rate-limit / cost cap, spam blows the Gemini bill
Debounce only coalesces bursts within 6s. Sustained one-message-every-7s spam is full multi-LLM cost each, unbounded. No per-user throttle, no daily budget alarm. Phase-04/06. Fix: per-user rate cap + daily spend/volume alert.

### M17 - Telegram webhook unauthenticated, spoofable /resume
/resume is restricted to configured TELEGRAM_CHAT_ID, but nothing verifies the POST actually came from Telegram (no secret_token header check). Anyone who learns the URL can POST a fake update with the right chat_id and resume/hijack any conversation. Phase-05. Fix: set the Telegram secret_token, verify the header; validate chat_id in payload.

### M18 - Postback / Get-Started / non-text events ignored, poor first impression, silent drops
Skipping postbacks means the Get-Started button does nothing (no greeting for new users). Stickers/images (very common in VN) silently ignored (canned line only optional). For a first-touch sales bot this reads as broken/ignoring. Phase-04. Fix: handle the Get-Started postback with a greeting; send a brief text-only notice on non-text.

### M19 - book_trial writes an unvalidated slot, bot books non-existent times
The agent extracts slot from free text and writes it to the Trials sheet with no availability check. Bot can confirm a trial at a closed time/full class. Phase-05. Fix: treat book_trial as a request, not a confirmation; require human confirmation or validate against an availability list.

### M20 - Price-format mismatch breaks number verification
Context has 5.000.000d but the agent may say 5 trieu / 5tr / 5,000,000. A deterministic substring check false-negatives; the LLM check may false-positive. Verification is unreliable without normalization. Phase-03. Fix: normalize numerals (strip separators, expand trieu/tr to digits) before comparing.

### M21 - Legit post-discount arithmetic collides with number-must-be-in-context
User asks the price after a 20% discount, the correct answer contains a computed figure NOT literally in context, reflect flags/strips it. Bot either cannot answer common discount questions or the guard misfires. Phase-03. Fix: decide policy: forbid arithmetic (state base + promo) OR allow a whitelisted computation with its own check.

---

## LOW

### L22 - PII retention / PDPD gap
SDT persists plaintext in Postgres checkpoints, the Leads Sheet, and the Telegram group indefinitely; no purge/retention (Nghi dinh 13/2023). Flagged as business responsibility but no deletion path exists. Phase-05/06. Fix: note retention policy + delete-by-thread procedure in runbook.

### L23 - reflect-lite runs on every turn incl. chit-chat / canned fallback
The fallback node routes its canned honest line back through reflect-lite (cheap), and chit-chat with no numbers still pays a Flash-Lite call. Wasteful, not harmful. Phase-03. Fix: skip reflect when the draft has no numeric/promise tokens.

### L24 - Crash-after-process-before-ACK, double reply
If the worker crashes after sending a reply but before returning 200, Meta retries; the restarted process has an empty in-memory dedupe, reprocesses, double reply (auto mode only). Rare. Phase-04. Fix: persist dedupe (small TTL table) if double-send proves real.

---

## Verdict

**NOT safe to implement as-is for auto (SHADOW_MODE=false).** Shadow mode (drafts to Telegram, human sends) masks most of these and is a reasonable week-1 posture, but the plan treats shadow mode as the safety net while several defects stay silent even in shadow (lost inbounds H5, handoff desync H6, wrong-course pricing C3 appears in the DRAFTS a human might trust).

MUST change before writing code:
1. C1: per-user serialization around graph invocation (also fixes the checkpointer race, cascades into H9/H6/ordering).
2. C2: replace the LLM-only pricing guard with a deterministic numeric-containment check that fails CLOSED.
3. H4: get all sync I/O (gspread, embeddings, similarity_search) off the single event loop.
4. H5: outage alerting + a no-silent-drop path for post-ACK failures.

STRONGLY reconsider before building: H8/C3, for <20 courses, KB-in-context removes an entire subsystem and the wrong-price-from-wrong-course failure class. If RAG stays, pricing must be a confirmed-course_id lookup, never a similarity by-product.

Everything else (M-tier) is fixable during implementation but should be logged as explicit tasks, not discovered in production.

## Unresolved questions
- Is single-worker truly acceptable given H4? Even one worker serializes badly without to_thread; confirm expected concurrent-conversation volume.
- Who owns the Gemini billing alarm / quota tier? (H7/M16 cost exposure.)
- Shadow-mode operational reality: how does staff actually SEND an approved draft (manual copy into FB inbox)? The approval-to-send loop is undefined.
