# Phase 04 — Messenger Channel Adapter

## Context Links
- Plan: [plan.md](plan.md)
- Prev: [phase-03-langgraph-brain.md](phase-03-langgraph-brain.md)
- Channel API ref: `researcher-260707-0012-messenger-zalo-apis.md` §1 (webhook, signature, Send API), §4 (Ph1 recs)
- Decisions: `brainstorm-260707-0012-*.md` §4 (ACK/dedupe/debounce), §5.1-5.2

## Overview
- **Priority:** P1
- **Status:** completed
- **Effort:** ~2d
- FastAPI Messenger webhook: GET verify (hub.challenge), POST handler (X-Hub-Signature-256 verify → **immediate 200 ACK** → async process), dedupe by `message.mid`, **debounce 5-8s/user** (in-process buffer, no Redis), normalize to unified message, invoke graph, send reply via Send API (typing indicator). Adapter interface abstraction so Zalo drops in later.

## Key Insights
- **Messenger needs 200 within ~5s** → verify signature synchronously, enqueue async task, return 200 immediately. Never block on graph/LLM.
- **Dedupe by `mid`**: Meta resends unacked events → must ignore duplicates. In-process TTL set keyed by `mid`.
- **Debounce 5-8s/user**: VN users send 3-5 fragment messages → buffer per user, coalesce, run graph once on the joined text. Cancel/restart timer on each new fragment.
- **No Redis** (KISS): in-process dict + asyncio tasks. Single-process deploy assumption for Pha 1 (document it — multi-worker breaks in-memory dedupe/debounce; run 1 uvicorn worker).
- **Per-thread turn serialization (CRITICAL):** debounce only guards the pre-flush window (6s) but a graph turn runs up to ~15s. A message arriving mid-turn would launch a 2nd concurrent `ainvoke` on the SAME `thread_id` → checkpoint clobber / lost turn. MUST hold a per-`user_id`/`thread_id` `asyncio.Lock` (single-flight) around flush→invoke→send; fragments arriving while a turn is in flight buffer into the NEXT debounce batch, never a parallel run.
- **Abuse/cost controls (HIGH):** per-PSID sliding-window rate limit + global concurrency cap + bounded (LRU/maxsize) dedupe & debounce maps + Gemini spend/quota alert — an unbounded webhook is a memory-growth + API-spend DoS vector.
- **Post-ACK durability (HIGH):** after the 200 ACK, Meta never redelivers; a crash before flush drops the buffered message (often the SĐT). Use FastAPI `BackgroundTasks` (awaited on graceful shutdown), NOT bare `asyncio.create_task`; residual crash-loss window documented; durable inbound queue = Pha-2.
- **Adapter interface** = abstract `ChannelAdapter` (parse_inbound, verify_signature, send_text, send_typing). Messenger implements now; Zalo later without touching graph/dispatch.
- PSID is page-scoped; use as `user_id`. `thread_id = "messenger:{psid}"`.

## Requirements
**Functional**
- `GET /webhook/messenger`: validate `hub.verify_token`==VERIFY_TOKEN, return `hub.challenge` raw.
- `POST /webhook/messenger`: verify HMAC-SHA256(body, APP_SECRET)==`X-Hub-Signature-256`; reject (403) if missing/invalid; else 200 immediately + schedule async.
- Dedupe: skip already-seen `mid` (TTL ~10min).
- Debounce: per-PSID buffer; after `DEBOUNCE_SECONDS` idle, flush joined text → graph.
- Normalize inbound to `InboundMessage{channel, user_id, text, mid, timestamp}`.
- **Single-flight per thread:** a per-`thread_id` `asyncio.Lock` serializes flush→invoke→send; only one graph turn per thread at a time. Fragments during an in-flight turn go into the next debounce batch.
- **Rate limit:** per-PSID sliding-window (msgs/min + msgs/day) checked before graph invoke; over-limit → canned "em nhận nhiều tin quá, thử lại sau" instead of invoking (no spend).
- **Global concurrency cap** on concurrent graph invocations (semaphore); over-cap requests wait or shed with canned line.
- **Bounded maps:** dedupe + debounce dicts have hard maxsize / LRU eviction (no unbounded growth).
- **Gemini budget/quota alert:** config-driven daily budget; on breach → Telegram alert + degrade to canned replies (config).
- Send reply: `typing_on` → send text (`messaging_type=RESPONSE`) → (implicit typing_off).
- Skip non-text events (attachments/postbacks) gracefully in Pha 1 (log; optional canned "em chỉ nhận tin nhắn văn bản").

**Non-functional**
- Files <200 LOC; split webhook routes / signature / dedupe / debounce / send-client / adapter-interface / normalizer / rate-limiter.
- Async throughout (httpx.AsyncClient reused).
- **Post-ACK processing via `BackgroundTasks`** (awaited on shutdown), not bare `asyncio.create_task` → graceful shutdown flushes in-flight work; residual crash-loss window documented.
- Handoff gating hook: before sending bot reply, check `handoff` flag (full gating logic Ph05) — adapter exposes the seam.

## Architecture
```
Meta → POST /webhook/messenger
  1. read raw body
  2. verify_signature(body, header, APP_SECRET)  → 403 if bad
  3. schedule via FastAPI BackgroundTasks (NOT bare create_task) then return 200  ← FAST + drained on shutdown
  4. background: for each messaging event:
       rate_limiter.allow(psid)? → else canned "thử lại sau", skip (no spend)
       mid seen? → drop (dedupe, bounded LRU)
       normalize → InboundMessage
       debounce_buffer.add(user_id, text)  (reset timer, bounded LRU)
         └─ on flush(user_id, joined_text):
              async with per_thread_lock[thread_id]:      ← SINGLE-FLIGHT (no concurrent ainvoke on same thread)
                if a turn already in flight → re-buffer into next batch (don't run parallel)
                if handoff active (Ph05 gate) → skip bot   ← seam
                async with global_concurrency_sem:
                  graph.ainvoke(joined_text, thread_id=messenger:psid)
                send_client.typing_on(psid)
                send_client.send_text(psid, reply)
```

### Adapter interface (channel/adapter-interface.py)
```python
class ChannelAdapter(ABC):
    channel: str
    def verify_signature(self, body: bytes, headers) -> bool: ...
    def parse_inbound(self, payload: dict) -> list[InboundMessage]: ...
    async def send_text(self, user_id: str, text: str) -> None: ...
    async def send_typing(self, user_id: str, on: bool) -> None: ...
```
`InboundMessage` (pydantic): `channel, user_id, text, mid, timestamp`.
Messenger implements; a future `ZaloAdapter` implements same ABC → dispatch code unchanged.

### Debounce (channel/debounce-buffer.py)
```python
# per user_id: {"parts":[str], "task": asyncio.Task}
def add(user_id, text, on_flush):
    buf.setdefault(user_id, {"parts":[]})["parts"].append(text)
    cancel existing task; schedule flush after DEBOUNCE_SECONDS
async def _flush(user_id, on_flush):
    joined = " ".join(parts); clear buffer; await on_flush(user_id, joined)
```
KISS: asyncio timer per user, cancel-and-reschedule on each fragment.
**Single-flight (CRITICAL):** flush ≠ safe to run concurrently. The dispatcher wraps `on_flush` in a per-`thread_id` `asyncio.Lock`; while a turn holds the lock, a new fragment appends to a fresh buffer that flushes AFTER the lock releases (next batch) — never a 2nd `ainvoke` on the same thread. Bound the buffer dict (maxsize/LRU) so idle users don't leak memory.

### Rate limiter (channel/rate-limiter.py)
Per-PSID sliding window: `allow(psid)` checks msgs/min + msgs/day against configured caps; over → False (caller sends canned line, skips graph). In-memory deque/counter per PSID, bounded (LRU-evict idle PSIDs). Plus a global concurrency semaphore for in-flight graph turns, and a daily Gemini-spend counter that trips a Telegram alert + canned-reply degrade when the configured budget is exceeded.

### Dedupe (channel/dedupe-store.py)
In-process `dict[mid → expiry]`; `seen(mid)` returns bool + records; periodic prune or lazy prune on access. TTL ~600s. **Bounded:** hard maxsize with LRU eviction so a flood of distinct mids can't grow the map without bound.

### Send API client (channel/messenger-send-client.py)
- `POST https://graph.facebook.com/{API_VERSION}/me/messages?access_token=PAGE_ACCESS_TOKEN`
- typing: `{"recipient":{"id":psid},"sender_action":"typing_on"}`
- text: `{"recipient":{"id":psid},"messaging_type":"RESPONSE","message":{"text":...}}`
- Split messages >~2000 chars into multiple sends (Messenger ~4096 limit; keep chunks small for readability).
- Reuse one `httpx.AsyncClient`; handle 429 (log + brief backoff).

### Signature (channel/signature-verify.py)
`hmac.new(APP_SECRET, body, sha256).hexdigest()` compared (constant-time `hmac.compare_digest`) to header `sha256=<hex>`. Missing header → reject.

## Related Code Files
**Create**
- `chatbot/app/channel/adapter-interface.py` — `ChannelAdapter` ABC + `InboundMessage` model
- `chatbot/app/channel/messenger-adapter.py` — implements ABC (verify, parse, send)
- `chatbot/app/channel/messenger-send-client.py` — Send API httpx client
- `chatbot/app/channel/signature-verify.py` — HMAC verify helper
- `chatbot/app/channel/dedupe-store.py` — in-process mid dedupe TTL set, bounded (LRU/maxsize)
- `chatbot/app/channel/debounce-buffer.py` — per-user coalescing buffer, bounded
- `chatbot/app/channel/rate-limiter.py` — per-PSID sliding-window limit + global concurrency semaphore + Gemini spend counter/alert
- `chatbot/app/channel/message-dispatcher.py` — flush→per-thread lock (single-flight)→(handoff gate seam)→concurrency-sem→graph→send
- `chatbot/app/api/webhook-messenger.py` — GET verify + POST handler (ACK fast)

**Modify**
- `chatbot/app/main.py` — include webhook router; instantiate MessengerAdapter + shared httpx client on startup/shutdown

## Implementation Steps
1. `adapter-interface.py`: ABC + `InboundMessage` pydantic model.
2. `signature-verify.py`: constant-time HMAC-SHA256 check; unit-testable pure fn.
3. `messenger-adapter.py`: `parse_inbound` walks `entry[].messaging[]`, extracts sender.id/mid/text/timestamp, skips non-text; `verify_signature` delegates helper; `send_text`/`send_typing` delegate send-client.
4. `messenger-send-client.py`: async POST typing + text; message splitting; 429 handling; shared client.
5. `dedupe-store.py`: `seen(mid)->bool` with TTL prune AND hard maxsize/LRU eviction (bounded).
6. `debounce-buffer.py`: asyncio cancel-reschedule per user; `add(user_id,text,on_flush)`; bounded buffer dict.
6b. `rate-limiter.py`: `allow(psid)->bool` sliding window (msgs/min + msgs/day) from config; global concurrency `asyncio.Semaphore`; daily Gemini-spend counter → Telegram alert + canned-degrade when budget exceeded. LRU-evict idle PSIDs.
7. `message-dispatcher.py`: `on_flush(user_id, joined)` → `async with per_thread_lock[thread_id]` (**single-flight**; if turn already in flight, re-buffer into next batch) → (Ph05 handoff gate check) → `async with global_sem` → `get_graph().ainvoke(...)` → extract reply text → `adapter.send_typing(on)` → `adapter.send_text`. Wrap in try/except; on error alert Telegram (Ph05) + optional soft user message.
8. `webhook-messenger.py`:
   - GET: check mode+token, return challenge (PlainTextResponse) or 403.
   - POST: read `await request.body()`; verify signature → 403 if bad; parse events; rate-limit check per PSID (over → canned line, skip); for each: dedupe→normalize→`debounce.add(...)`; **return 200 immediately** scheduling work via **FastAPI `BackgroundTasks`** (awaited on shutdown), NOT bare `asyncio.create_task` (fix #7 — avoids losing in-flight work on graceful restart). Document the residual crash-before-flush loss window.
9. `main.py`: mount router; create shared httpx client + adapter singletons in lifespan; pass graph handle.
10. Test with Meta webhook test events / ngrok: verify handshake, signature reject on tampered body, dedupe on resent mid, debounce coalescing, reply delivered with typing.

## Todo List
- [ ] `adapter-interface.py` ABC + InboundMessage
- [ ] `signature-verify.py` constant-time HMAC, reject unsigned
- [ ] `messenger-adapter.py` parse/verify/send implementing ABC
- [ ] `messenger-send-client.py` typing + RESPONSE send, splitting, 429
- [ ] `dedupe-store.py` mid TTL dedupe, bounded LRU
- [ ] `debounce-buffer.py` per-user coalesce 5-8s, bounded
- [ ] `rate-limiter.py` per-PSID sliding window + global concurrency sem + Gemini budget alert
- [ ] `message-dispatcher.py` per-thread single-flight lock → gate seam → concurrency-sem → graph → send, error alert
- [ ] `webhook-messenger.py` GET verify + POST fast-ACK via BackgroundTasks (not create_task) + rate-limit gate
- [ ] `main.py` router + shared client/adapter lifecycle
- [ ] Handshake, signature-reject, dedupe, debounce, reply verified via tunnel
- [ ] Concurrent same-thread message mid-turn → serialized (no 2nd parallel ainvoke, no checkpoint clobber)
- [ ] Rate-limit enforced (flood → canned line, no graph spend); maps stay bounded

## Success Criteria
- GET handshake returns challenge only when token matches.
- POST returns 200 in <1s even while graph runs (ACK not blocked).
- Tampered body / missing signature → 403, not processed.
- Same `mid` delivered twice → processed once.
- 4 fragments within debounce window → single graph invocation on joined text.
- A message arriving mid-turn (after flush, during the ~15s invoke) does NOT launch a 2nd concurrent `ainvoke` on the same thread — it serializes into the next batch (no checkpoint clobber / lost turn).
- Per-PSID flood over the rate cap → canned "thử lại sau", graph not invoked (no spend); dedupe/debounce maps stay bounded under load.
- Reply sent via Send API with typing indicator, `messaging_type=RESPONSE`.
- Non-text event handled without crash.

## Risk Assessment
| Risk | L×I | Mitigation |
|---|---|---|
| Concurrent same-thread ainvoke → checkpoint clobber / lost turn | Critical (Med×High) | Per-`thread_id` `asyncio.Lock` single-flight; mid-turn fragments re-buffer into next batch, never a parallel run |
| Unbounded in-memory maps + no rate/spend cap (memory + API-cost DoS) | Med×High | Per-PSID sliding-window rate limit, global concurrency sem, bounded LRU dedupe/debounce, Gemini budget alert + canned degrade |
| Slow ACK → Meta retries → dup replies | Med×High | Verify-then-immediate-200; async processing; dedupe by mid |
| In-memory dedupe/debounce lost on multi-worker | Med×High | Document + run single uvicorn worker Pha 1; Redis deferred (YAGNI) |
| Debounce delays first reply feel slow | Low×Med | 5-8s tuned; typing indicator signals activity |
| Signature bypass / spoofed webhook | Low×High | Mandatory HMAC verify, constant-time compare, reject unsigned |
| Send fails (429/expired token) | Med×Med | Retry/backoff on 429; alert Telegram on repeated failure |
| Process crash loses buffered fragments (post-ACK; Meta won't redeliver) | Med×High | `BackgroundTasks` drained on graceful shutdown (not bare create_task); residual crash-loss window documented; durable inbound queue = Pha-2 |

## Security Considerations
- **X-Hub-Signature-256 mandatory** — reject unsigned/invalid before any processing.
- PAGE_ACCESS_TOKEN, APP_SECRET, VERIFY_TOKEN via env only.
- Do not log full message bodies with PII at INFO; redact SĐT if logged.
- Rate-limit awareness (429) to avoid token abuse flags; per-PSID inbound rate limit + Gemini spend cap guard against cost-DoS.
- **Post-ACK durability:** processing runs in `BackgroundTasks` drained on graceful shutdown; a hard crash between ACK and flush loses the buffered fragment (Meta never redelivers) — documented residual window; durable inbound queue is the Pha-2 upgrade.

## Next Steps
- Unblocks Phase 05: dispatcher's handoff-gate seam + error-alert callback get real implementations; lead/book/handoff tool bodies filled.
- Zalo (Pha 2): implement `ZaloAdapter(ChannelAdapter)` + `webhook-zalo.py`; dispatcher/graph unchanged.
