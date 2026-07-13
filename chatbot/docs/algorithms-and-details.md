# Algorithms & Implementation Details — Tuyển Sinh Concierge (Pha 1)

> Mọi thuật toán / cơ chế bảo vệ đã dùng, kèm cách kiểm thử. Đọc file này để biết
> "cần test cái gì". Grammar-terse per project convention.

Stack: FastAPI + LangGraph StateGraph + Gemini 2.5 Flash/Flash-Lite + Google Sheets
KB + Postgres (AsyncPostgresSaver checkpoints + `handoff_status`) + Telegram.
Golden rule: **bot không bao giờ tự chế học phí/ưu đãi/cam kết**.

---

## 0. Graph shape (bộ não)

```
START → agent
agent   ──tool_calls──> tool_exec ──retrieved──> grade_chunks ──sufficient──> agent
        └──final text──> reflect_lite                        └─insufficient──> fallback → reflect_lite
tool_exec ──no retrieve──> agent      (loop cap → fallback)
reflect_lite ──ok/safest──> pricing_guard ──> END
             └──1 fix────> agent
```
- `agent`: Gemini Flash + `bind_tools`. Inject retrieved chunks as **UNTRUSTED DATA**,
  pricing as **SỐ LIỆU CHÍNH THỨC** (2 system messages, ephemeral — không lưu vào history).
- Order rationale: `reflect_lite` (fuzzy promise/tone) THEN `pricing_guard`
  (deterministic, authoritative) = last gate before send.

---

## 1. VN-numeral normalizer (`app/common/vn_numerals.py`)

Mục tiêu: canonical-hoá mọi cách viết tiền VN về **int VND** để so khớp.
Property quan trọng nhất = **consistency** (cùng input → cùng output ở cả draft và KB).

Regex alternation (ordered, `finditer` consume — không đếm trùng):
1. `pct`: `\d+%` → giữ giá trị %.
2. `mil`: `X triệu|tr|củ [rưỡi|Y]` → `X*1e6` (+ `1e6/2` nếu "rưỡi"; + `int(Y)*10^(6-len(Y))` cho "4tr5"→+500k, "4tr500"→+500k, "4tr05"→+50k). `tr(?![a-zà-ỹ])` tránh nuốt "trăm/trung".
3. `k`: `X nghìn|ngàn|k` → `X*1e3`.
4. `grouped`: `1.500.000` / `1,500,000` → bỏ separator → int.
5. `bare`: `\d{6,}` (≥100k) → int. Bỏ số điện thoại (`^0\d{8,10}$`).

False-positive guard: số không có đơn vị tiền + < 6 chữ số bị bỏ → "lớp 6", "2 buổi",
"15/8", "năm 2026" KHÔNG bị coi là tiền. Ambiguous forms fail-closed (an toàn).

**API:** `money_values(text)->set[int]`, `percent_values(text)->set[int]`.
**Test:** `tests/test_vn_numerals.py` (10 cases: `4tr5`==`4.500.000`, phone bỏ, %…).

---

## 2. Pricing-guard — DETERMINISTIC, AUTHORITATIVE (`app/graph/nodes/pricing_guard.py`)

`evaluate_draft(draft, retrieved) -> GuardVerdict(ok, violations, named_course_ids)`:

1. **Resolve named course(s):** course nào có `ten_khoa` xuất hiện trong draft (exact
   substring HOẶC ≥60% từ ≥3 ký tự khớp). Nếu không match và chỉ có 1 course retrieved →
   bind vào course đó (single-candidate). Nếu 0 match & nhiều course → named=∅.
2. **Allowed set:** union `money_values` + `percent_values` của pricing string CỦA
   RIÊNG named courses (giá gắn với `course_id`, KHÔNG phải "xuất hiện đâu đó trong k=3").
3. **Membership:** mọi money/pct token trong draft phải ∈ allowed set.
   - Discount tự tính (5tr−10%→"4tr5" không có literal trong Sheet) → không ∈ allowed → **reject** (tự động, không cần tính %).
   - Giá khóa A gán cho khóa B → allowed của B không chứa → **reject**.
4. **Free-claim:** "miễn phí/free" trong draft chỉ hợp lệ nếu pricing của named course cũng có "miễn phí".
5. **Fail-closed:** bất kỳ violation → node thay draft bằng **HONEST_FALLBACK** + set
   `handoff=True`, `sales_stage="cần người"` (replace AIMessage theo cùng `id`).

Node `pricing_guard_node` chỉ import langchain lazily; `evaluate_draft` là **pure**.
**Test:** `tests/test_pricing_guard.py` (10 cases: exact pass, computed-discount reject,
wrong-course reject, free-claim reject, %-binding, no-course fail-closed).

---

## 3. Reflect-lite — promise/tone ONLY (`app/graph/nodes/reflect_node.py`)

Số đã chuyển hết sang pricing_guard. Reflect chỉ bắt hứa hẹn cấm + giọng điệu:
1. **Deterministic blocklist first** (`reflect_prompt.py`): regex các cụm
   "đảm bảo đậu/giỏi/điểm", "cam kết…", "chắc chắn…", "miễn phí 100%", "bao đậu"…
2. Nếu blocklist không bắt → **Flash-Lite** `with_structured_output(ReflectResult{ok,issues,fixed_reply})`
   bắt paraphrase.
3. Bounded fix: có `fixed_reply`/strip → apply ngay (replace by id) → guard. Không fix
   được → bounce agent MỘT lần (`reflect_count` guard) qua `fix_hint` ephemeral. Hết
   lượt → gửi HONEST_FALLBACK. **Không loop vô hạn.**

**Test:** `tests/test_reflect_lite.py` (blocklist bắt/không, strip).

---

## 4. Corrective-RAG grade → fallback (`grade_node.py`, `fallback_node.py`)

`grade_chunks` (Flash-Lite, structured `{sufficient, reason}`) phân loại ngữ cảnh đủ/thiếu.
`sufficient=false` → `fallback_node` chèn câu honest + `handoff=True` + `sales_stage="cần người"`.
`_last_human_text` duck-type trên `.type=="human"` (không cần import langchain — dễ test).
**Test:** `tests/test_grade_fallback.py` (stub Flash-Lite → route đúng).

---

## 5. KB layer — atomic snapshot + validation (`app/kb/`)

- **Split (golden rule tại data layer):** `course_parser.py` build 1 Document/khóa từ
  các trường mô tả; `hoc_phi`/`uu_dai` giữ verbatim trong `pricing_map`, **KHÔNG embed**.
- **Partial-row validation:** row có `course_id` nhưng thiếu `ten_khoa`/`hoc_phi` (rỗng/space)
  → loại + error (không phục vụ giá thiếu).
- **Pricing-cell sanitization:** ô `hoc_phi`/`uu_dai` chứa newline / chuỗi "SỐ LIỆU CHÍNH
  THỨC" / mẫu lệnh (ignore, bỏ qua, system:, ```…) → quarantine cả khóa (chống forge marker/injection).
- **Atomic snapshot (`vector_store.py`):** `rebuild()` chạy OFF event loop
  (BackgroundScheduler thread / executor). Build store + embed (network call **không giữ lock**),
  rồi 1 lần rebind `self._snapshot=(store,pricing,meta,version)` (GIL-atomic). Reader
  (`retrieve`) đọc snapshot 1 lần → không bao giờ thấy nửa vời/desync, không giữ lock qua network.
  Rebuild fail → giữ last-good snapshot + alert.
- **Test:** `tests/test_course_parser.py` (split, partial-row, injection quarantine, dup, schema).

---

## 6. Tool execution + state mutation (`tool_exec_node.py`, `tools/lead_tools.py`)

Không phụ thuộc "Command-from-tool" API (version-robust). `bind_tools` chỉ dùng schema;
node `tool_exec` tự execute: đọc `tool_calls`, gọi `TOOL_IMPLS[name](args, state)` (async,
trả `ToolResult(message, state_update)`), trả về ToolMessages + **state_update** →
LangGraph ghi thẳng channels `handoff`/`sales_stage`/`lead_profile` (fix "handoff no-op").
Mỗi tool_call đều có ToolMessage (tránh dangling). `retrieve_kb` → build `pricing_context`
+ route `grade_chunks`; tool khác → route `agent`. Loop cap `tool_rounds` (4) → fallback.

---

## 7. Checkpointer lifecycle (`main.py`)

`AsyncPostgresSaver.from_conn_string(dsn)` là **async context manager** → giữ mở suốt
đời app: `async with … as saver: await saver.setup(); set_graph(build_graph(saver)); …; yield`.
Không drop context (nếu drop → pool đóng → mọi ainvoke fail). `thread_id="{channel}:{user_id}"`.
Env `LANGGRAPH_STRICT_MSGPACK=true`. Gemini call bọc `with_retry` (jitter backoff 429/5xx/timeout);
give-up → dispatcher gửi soft-fail line + alert (không mất lượt im lặng).

---

## 8. Channel adapter (`app/channel/`, `app/api/webhook_messenger.py`)

- **Signature:** `verify_signature` HMAC-SHA256 constant-time (`hmac.compare_digest`);
  thiếu/không hợp lệ → 403 trước mọi xử lý.
- **Fast ACK:** POST verify sig SYNC → schedule `process_events` qua FastAPI
  `BackgroundTasks` (drained on graceful shutdown, KHÔNG bare `create_task`) → trả 200 ngay.
- **Dedupe (`dedupe_store.py`):** `dict[mid→expiry]` OrderedDict, TTL 600s + **bounded LRU**
  (maxsize evict oldest). `seen(mid)` True nếu đã thấy.
- **Debounce (`debounce_buffer.py`):** buffer/user, gộp fragment, cancel-reschedule timer
  `DEBOUNCE_SECONDS`. Flush **pop buffer TRƯỚC** khi await on_flush → fragment giữa lượt vào
  buffer mới (next batch). Bounded LRU.
- **Single-flight (`message_dispatcher.py`):** `asyncio.Lock`/thread_id bọc flush→invoke→send.
  2 tin cùng thread → serialize, KHÔNG 2 ainvoke song song (chống clobber checkpoint).
- **Rate-limit (`rate_limiter.py`):** sliding window/PSID (deque msgs/min + msgs/day), global
  concurrency `Semaphore`, daily-spend counter (proxy ~2000 tok/turn) → alert + degrade
  (BUDGET_DEGRADE_LINE) khi vượt `GEMINI_DAILY_BUDGET`. Bounded windows.
- **Send API:** typing_on → text `messaging_type=RESPONSE`, split >1800 ký tự, 429 backoff.
- **Adapter ABC** → Zalo drop-in sau (spine không đổi).
- **Test:** `test_signature_verify`, `test_dedupe_store`, `test_debounce_buffer`,
  `test_rate_limit`, `test_single_flight`, `test_webhook_idempotency`.

---

## 9. Handoff + resume (`app/handoff/`, `app/db/handoff_status_table.py`)

- **Authoritative = table `handoff_status`** (O(1) gate). `ConvState.handoff` chỉ advisory.
- **Atomic touch + auto-resume clock (fix clock-freeze):** `touch_user_and_get` = 1 câu SQL
  (CTE snapshot prev + upsert `last_user_ts=now()`), trả **prev** values. `before_invoke`:
  touch mỗi inbound → nếu prev_active & silence gap > 24h (dựa prev_user_ts, và no recent
  last_human_ts) → auto-resume; ngược lại skip bot. `should_auto_resume` là **pure**.
- **TOCTOU close:** `before_send` re-check `is_active` NGAY trước khi gửi → drop reply nếu
  handoff bật giữa lượt invoke.
- **Resume:** `/resume messenger:<PSID>` từ Telegram → `handoff_manager.clear`.
- **Lead upsert (`lead_sheet.py`):** locate row bằng **`ws.find` (VALUE)**, không enumerate
  index → staff xóa row giữa không ghi đè nhầm SĐT. Re-find ngay trước write + per-user lock.
- **Test:** `test_handoff_resume` (pure + gate + auto-resume), `test_lead_upsert`
  (dedupe + **middle-row-delete correctness**).

---

## 10. Telegram webhook auth (`app/api/webhook_telegram.py`)

Verify header `X-Telegram-Bot-Api-Secret-Token` == `TELEGRAM_WEBHOOK_SECRET`
(constant-time) TRƯỚC khi parse. Body `chat_id` chỉ advisory, KHÔNG phải auth boundary.
Forged/missing → 403. **Test:** `test_telegram_secret_token` (missing/wrong→403, valid→resume).

---

## 11. PII / PDPD (`app/db/retention_purge.py`, `app/log_redaction_filter.py`)

- **Consent:** bot báo mục đích trước khi lưu SĐT; ghi `consent`/`consent_at` trên lead row.
- **Retention purge (daily task):** `purge_expired(days)` xóa checkpoints + handoff rows +
  lead rows quá hạn (dùng `handoff_status.last_user_ts` làm đồng hồ hoạt động thread).
- **Delete-by-PSID:** `delete_by_psid(psid)` xóa checkpoint thread + handoff row + Leads row.
- **Log redaction:** `PhoneRedactionFilter` (logging.Filter, gắn lên mọi root handler) mask
  `0xxx***yy` — enforced, không phải convention.
- **Cross-border:** Sheets/Telegram US-hosted → ghi cơ sở chuyển dữ liệu (business/legal).
- **Test:** `test_retention_purge` (Sheet-side purge + delete_by_user). DB-side purge =
  integration với Postgres thật.

---

## 12. Shadow mode (`app/channel/shadow_gate.py`)

`make_deliver_fn(adapter)`: `SHADOW_MODE=true` → gửi `[DRAFT → PSID]` (HTML-escaped) lên
Telegram, **0 tin tới user thật**; `false` → `adapter.send_text`. Dispatcher gọi qua deliver
này (mọi tin user-facing, kể cả rate-limit/degrade line). **Test:** `test_shadow_mode`.

---

## 13. Test coverage (68 tests, all green trên Python 3.10)

| File | Guard |
|---|---|
| test_vn_numerals | VN-numeral normalize |
| test_pricing_guard | price↔course binding, computed-discount, free-claim, fail-closed |
| test_reflect_lite | promise blocklist + strip |
| test_grade_fallback | Corrective-RAG grade → route |
| test_course_parser | KB split, partial-row, injection quarantine, schema |
| test_signature_verify | HMAC constant-time |
| test_dedupe_store | once + TTL + bounded LRU |
| test_debounce_buffer | coalesce + reset + bounded |
| test_rate_limit | per-min/day cap, budget alert, bounded |
| test_single_flight | same-thread serialize / diff-thread overlap |
| test_webhook_idempotency | resent mid → 1 flush |
| test_lead_upsert | dedupe + **middle-row-delete correctness** |
| test_handoff_resume | gate skip/proceed, auto-resume, TOCTOU, /resume parse |
| test_telegram_secret_token | forged/missing → 403; valid → resume |
| test_shadow_mode | draft-to-Telegram, zero user send |
| test_retention_purge | purge past window + delete-by-user |

**Chạy:** `cd chatbot && pip install -r requirements.txt && pytest`
(pure/async/integration subset chỉ cần pytest+pytest-asyncio+pydantic+httpx+fastapi;
grade/reflect LLM paths dùng stub → không cần Gemini thật).

---

## 14. Red-team fixes → nơi implement (17/17)

| # | Fix | File |
|---|---|---|
| 1 | Deterministic pricing-guard + reflect demote | `pricing_guard.py`, `reflect_node.py` |
| 2 | State-mutating tools ghi channels (no no-op) | `tool_exec_node.py`, `lead_tools.py` |
| 3 | AsyncPostgresSaver context giữ mở | `main.py` |
| 4 | LLM retry/backoff jitter, no dangling turn | `llm/retry.py`, `message_dispatcher.py` |
| 5 | Per-thread single-flight lock | `message_dispatcher.py` |
| 6 | Rate-limit + concurrency + bounded maps + budget | `rate_limiter.py`, `dedupe_store.py`, `debounce_buffer.py` |
| 7 | BackgroundTasks (drained), residual window doc | `webhook_messenger.py` |
| 8 | Telegram secret-token constant-time | `webhook_telegram.py` |
| 9 | Lead upsert by `ws.find` value + per-user lock | `lead_sheet.py` |
| 10 | Auto-resume clock touch-before-check | `handoff_manager.py`, `handoff_status_table.py` |
| 11 | Handoff table authoritative + TOCTOU re-check | `handoff_manager.py`, `message_dispatcher.py` |
| 12 | PII consent/retention/delete/log-redaction | `retention_purge.py`, `log_redaction_filter.py`, `lead_tools.py` |
| 13 | Partial-row validation | `course_parser.py` |
| 14 | Prompt-injection: UNTRUSTED framing + cell sanitize | `agent_node.py`, `course_parser.py` |
| 15 | Vector-store atomic snapshot, lock-free readers | `vector_store.py` |
| 16 | App Review critical path / milestones | `docs/deployment-guide.md`, `plan.md` |
| 17 | Tests for new guards | `tests/` |

---

## 15. Known limitations / cần test thủ công với deps thật

- **Chưa chạy end-to-end với Gemini/Postgres/Sheets thật** (máy dev không có Python; đã
  verify bằng compileall + 68 tests trên WSL Python 3.10 với deps tối thiểu, stub LLM/Sheets/DB).
  Cần test thật: (a) 1 vòng graph có tool loop + checkpoint nhớ 2 lượt; (b) pricing_guard
  reject số ngoài KB trên hội thoại thật; (c) handoff flip + Telegram notify; (d) KB sync từ
  Sheet phản ánh sau 1 interval; (e) webhook handshake từ Meta.
- **Version verify:** khi `pip install`, xác nhận model IDs + `AsyncPostgresSaver` import,
  và exact API `with_structured_output` / tool schema của LangGraph bản cài; đã code
  version-robust (execute tool trong node riêng, không phụ thuộc Command-from-tool).
- **Gemini spend** = proxy ~2000 tok/turn (chưa đọc `usage_metadata` thật) → tinh chỉnh sau.
- **Checkpoint retention** dựa `handoff_status.last_user_ts` (touch mỗi inbound) → thread
  chưa từng inbound sẽ không có row (không cần purge). DB-side purge cần Postgres để test.
- **Single worker** bắt buộc (in-memory state). Multi-worker = Redis (Pha 2).
- **Post-ACK crash window** (mất fragment buffered) — durable queue = Pha 2.

## Unresolved questions
1. Ngưỡng "min real-conversation volume" trước khi flip `SHADOW_MODE=false` (đề xuất ≥50
   convos / ≥30 câu hỏi giá) — cần business chốt.
2. `GEMINI_DAILY_BUDGET` nên đặt bao nhiêu (đơn vị = proxy token/ngày) — cần đo thực tế.
3. Cột `chat_link` hiện lưu `messenger:PSID`; có muốn deep-link page inbox cụ thể không?
