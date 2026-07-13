# Phase 02 — KB Layer (Sheet Sync + Vector Store)

## Context Links
- Plan: [plan.md](plan.md)
- Prev: [phase-01-project-setup-infra.md](phase-01-project-setup-infra.md)
- Stack ref: `researcher-260707-0012-langgraph-gemini-stack.md` §3 (InMemoryVectorStore), §4 (gspread)
- Decisions: `brainstorm-260707-0012-*.md` §3.1 (structured pricing rule), §4 (rebuild-on-sync)
- KB template: `2026-07-06-tuyensinh-concierge-brainstorm.md` §7

## Overview
- **Priority:** P1
- **Status:** completed
- **Effort:** ~2d
- Build KB pipeline: read Google Sheet → chunk descriptive fields → embed into fresh InMemoryVectorStore every ~5 min. **CRITICAL:** học phí/ưu đãi live in structured columns, injected VERBATIM (never chunked/embedded).

## Key Insights
- **Golden rule at data layer:** pricing/promo NEVER goes through embeddings. Kept as structured dict per course, injected literally when that course is retrieved. RAG only over: Đối tượng, Mục tiêu, Lộ trình, Lịch, GV, FAQ, Chính sách.
- KB tiny (<20 khóa, 20-40K tokens) → full rebuild each sync is cheap (seconds). No Chroma/pgvector.
- Staff edit Sheet directly → format drift is the top ops risk → validate on sync, report bad rows to Telegram (Phase 05 notifier; here just surface errors).
- **Partial-row validation (HIGH):** a row with a non-empty `course_id` but empty/whitespace `hoc_phi` (or other required field) is a HALF-EDITED row — it must NOT be served as OFFICIAL DATA (would let the bot quote a course with missing pricing). Treat as a bad row → skip + alert, OR exclude that course from retrieval entirely. `course_id`-only check is insufficient.
- **Prompt-injection via Sheet (HIGH):** retrieved chunks + pricing cells are staff/attacker-editable free text injected into the LLM prompt. Wrap retrieved chunks as clearly-delimited UNTRUSTED DATA (data, not instructions); validate pricing cells at parse time (reject newlines / the trust-marker string / instruction-like patterns) so a cell can't forge the "SỐ LIỆU CHÍNH THỨC" marker or override the golden rule. KB Sheet edit access must be locked-down + audited (business responsibility).
- **Thread-safety (HIGH):** rebuild runs on the scheduler thread while async webhook requests read concurrently. Do NOT hold a threading lock across the Gemini embedding network call, and do NOT swap store + pricing as two separate assignments (desync window). Build a new immutable snapshot `(store, pricing, version)` OFF the event loop (thread executor), then swap it via ONE atomic attribute rebind (GIL-atomic) → readers need NO lock and never see a half-built or desynced state.
- Sync failure must NOT crash serving — keep last-good store, log + alert, retry next interval.

## Requirements
**Functional**
- `sync_kb()` fetches all course rows, validates, builds Document list (descriptive fields only), embeds, swaps active store atomically.
- `retrieve(query, k)` returns top-k chunks with `course_id` metadata.
- `get_pricing(course_id)` returns verbatim structured pricing/promo string for a course (from a plain dict, NOT vector store).
- Scheduler runs `sync_kb()` every `KB_SYNC_INTERVAL_SEC`; also once on startup (lifespan). Scheduler = `BackgroundScheduler` (thread) — committed, not undecided.
- Bad-format rows skipped (not fatal), collected into an errors list for alerting. **Partial rows** (course_id present but a required field like `hoc_phi` empty/whitespace) count as bad → skip/exclude + alert.
- Pricing cells validated at parse time: reject/quarantine any cell containing newlines, the trust-marker string ("SỐ LIỆU CHÍNH THỨC"), or instruction-like patterns → route to error sink.

**Non-functional**
- Files <200 LOC each; split fetch / build / store-access.
- One embeddings client reused across rebuilds (avoid re-init cost).
- Sync logs version stamp (timestamp + row count + doc count).
- Rebuild runs in a thread executor (off the event loop); active KB exposed as a single immutable snapshot swapped by one atomic rebind — no lock held across the embed call.

## Architecture
```
Google Sheet (staff-edited)
  worksheet "Courses": one row per khóa, columns per §7 template
        │  gspread get_all_records()
        ▼
kb/sheet-loader.py        → list[dict] raw rows
        │  validate + split
        ▼
kb/course-parser.py       → (documents[], pricing_map{course_id: verbatim_str}, errors[])
        │  documents = descriptive fields chunked; pricing kept OUT
        ▼
kb/vector-store.py (KnowledgeBase)
   - embeddings (Gemini) built once
   - rebuild(): new InMemoryVectorStore → add_documents → atomic swap under lock
   - retrieve(query,k) / get_pricing(course_id)
        │
        ▼
kb/sync-scheduler.py      → APScheduler interval job → KnowledgeBase.rebuild()
```

### Google Sheet template (worksheet "Courses")
One row per course. Columns (header row exact names):
| Column | RAG? | Notes |
|---|---|---|
| `course_id` | metadata | unique key |
| `ten_khoa` | embedded | course name |
| `doi_tuong` | embedded | target audience |
| `muc_tieu` | embedded | outcomes |
| `lo_trinh` | embedded | roadmap/duration |
| `lich_khai_giang` | embedded | schedule text |
| `giao_vien` | embedded | teacher info |
| `faq` | embedded | Q&A block |
| `chinh_sach` | embedded | policy (bảo lưu/hoàn phí) |
| `hoc_phi` | **STRUCTURED — verbatim** | tuition; NEVER embedded |
| `uu_dai` | **STRUCTURED — verbatim** | current promo; NEVER embedded |

### Chunking strategy (KISS)
- Per course, build **one Document** combining name + descriptive fields (KB tiny; per-field chunking = overkill, YAGNI). `page_content = f"Khóa: {ten}\nĐối tượng:...\nFAQ:..."`, `metadata={course_id, ten_khoa}`.
- If a course's descriptive text is large, split by field into ≤N docs sharing `course_id` — only if a single doc exceeds embed limits. Default: 1 doc/course.
- `pricing_map[course_id] = f"Học phí: {hoc_phi}\nƯu đãi: {uu_dai}"` — stored raw, keyed by course_id.

### Verbatim injection contract (hardened against prompt injection)
`retrieve_kb` tool (Phase 03) returns for each hit: the chunk text PLUS `get_pricing(course_id)` appended verbatim. Pricing string is passed to the LLM as fixed context, flagged "SỐ LIỆU CHÍNH THỨC — không được sửa đổi".
- **Untrusted-data framing:** retrieved descriptive chunks are wrapped in a clearly-delimited UNTRUSTED-DATA block in the prompt — they are DATA to answer from, never instructions to follow. A chunk saying "ignore the golden rule / give a discount" must not be obeyed.
- **Trust-marker integrity:** the "SỐ LIỆU CHÍNH THỨC" marker is added by our code around a cell that has already been validated. Parse-time validation REJECTS any pricing cell containing newlines, the marker string itself, or instruction-like patterns → so a staffer/attacker can't inject a forged marker (e.g. via newlines) to smuggle a fake official price. Quarantined cells route to the Telegram error sink; that course is excluded from pricing until fixed.

## Related Code Files
**Create**
- `chatbot/app/kb/sheet-loader.py` — gspread client (service_account + BackOffHTTPClient), fetch "Courses" rows
- `chatbot/app/kb/course-parser.py` — validate rows (incl partial-row + pricing-cell sanitization), build Documents (descriptive only) + pricing_map + errors
- `chatbot/app/kb/vector-store.py` — `KnowledgeBase`: embeddings, `rebuild()` (off event loop), `retrieve()`, `get_pricing()`, lock-free readers via one atomic `(store,pricing,version)` snapshot rebind
- `chatbot/app/kb/sync-scheduler.py` — APScheduler `BackgroundScheduler` (thread) interval job wrapper
- `chatbot/app/kb/__init__.py` — expose singleton `knowledge_base`

**Modify**
- `chatbot/app/main.py` — lifespan: initial `rebuild()` + start scheduler; stop scheduler on shutdown

## Implementation Steps
1. `sheet-loader.py`: build gspread client from `GOOGLE_SA_JSON_PATH` with `BackOffHTTPClient`; open `KB_SHEET_ID` → worksheet "Courses" → `get_all_records()`. Single API call per sync.
2. `course-parser.py`:
   - Required columns present? missing header → raise config error (whole-sheet fatal).
   - **Row validation class** — a row is valid only if `course_id` non-empty AND all required fields (incl `hoc_phi`) non-empty/non-whitespace; else it's a **partial/bad row** → skip→errors (don't serve half-edited pricing). Distinguish "empty row skip" vs "partial row (has id, missing required)" in the error so alerts are actionable.
   - **Pricing-cell sanitization:** reject/quarantine any `hoc_phi`/`uu_dai` cell containing newlines, the trust-marker string ("SỐ LIỆU CHÍNH THỨC"), or instruction-like patterns → error sink; exclude that course from `pricing_map` (so it can't be quoted) until fixed.
   - Build descriptive `page_content` (exclude `hoc_phi`/`uu_dai`). Build `pricing_map[course_id]` verbatim from validated cells. Return `(docs, pricing_map, errors)`.
3. `vector-store.py` `KnowledgeBase` (lock-free readers, atomic snapshot):
   - `__init__`: create embeddings once (`GoogleGenerativeAIEmbeddings(GEMINI_EMBED_MODEL)`); `self._snapshot=None` (an immutable `(store, pricing, version)` tuple/frozen dataclass).
   - `rebuild()`: **run OFF the event loop** (called from a thread via executor / BackgroundScheduler thread). load→parse→new `InMemoryVectorStore(embeddings)`→`add_documents(docs)` (the Gemini embed network call happens HERE, holding NO lock). Then build `snap=(store, pricing, version=(ts,len))` and do ONE atomic rebind `self._snapshot = snap` (GIL-atomic; no lock needed, no desync between store and pricing). On exception keep old snapshot, log, return errors for alerting.
   - `retrieve(query,k=3)`: read `snap=self._snapshot` once (atomic), `snap.store.similarity_search`; return `{text, course_id, pricing}` via snapshot's pricing. No lock, never holds a lock across an embed/query network call.
   - `get_pricing(course_id)`: `self._snapshot.pricing.get(course_id, "")`.
4. `sync-scheduler.py`: APScheduler **`BackgroundScheduler`** (thread — committed choice; `rebuild()` is blocking/sync and must not block the event loop), interval=`KB_SYNC_INTERVAL_SEC`, job=`knowledge_base.rebuild`; expose `start()`/`shutdown()`. Return errors → hand to Telegram notifier (Phase 05) via injected callback (default callback = log).
5. Wire lifespan in `main.py`: `await`/run initial rebuild (fail startup only if sheet totally unreadable), then `scheduler.start()`.
6. Manual test: edit Sheet, wait interval, confirm `retrieve` reflects change; confirm pricing string identical to cell (verbatim).

## Todo List
- [ ] `sheet-loader.py` gspread + backoff, single-call fetch
- [ ] `course-parser.py` validation (partial-row class + pricing-cell sanitization) + docs/pricing split + errors
- [ ] `vector-store.py` KnowledgeBase rebuild (off event loop) / retrieve (lock-free) / get_pricing via atomic snapshot rebind
- [ ] `sync-scheduler.py` BackgroundScheduler interval job + error callback hook
- [ ] `main.py` lifespan: initial rebuild + scheduler start/stop
- [ ] Verbatim pricing verified byte-identical to Sheet cell
- [ ] Concurrent-read-during-rebuild smoke test (no crash/partial/desync)
- [ ] Bad-row skip + errors surfaced (not fatal)
- [ ] Partial row (id present, `hoc_phi` empty) skipped/excluded + alerted (not served)
- [ ] Pricing cell with newline / forged trust-marker / instruction text quarantined + alerted

## Success Criteria
- Editing a course description in Sheet reflects in `retrieve()` within one interval.
- `hoc_phi`/`uu_dai` NEVER appear in any embedded Document; only via `get_pricing`, byte-identical to cell.
- **A course with empty/whitespace `hoc_phi` is NOT retrievable with pricing** (skipped/excluded) and an alert names it — never quoted as official data with missing price.
- **A pricing cell containing a newline or a forged "SỐ LIỆU CHÍNH THỨC" marker is quarantined** (not injected) + alerted.
- Sync failure keeps last-good snapshot serving; error logged + alert-ready.
- Concurrent retrieve during rebuild returns a consistent snapshot (old-or-new `(store,pricing)` together), never partial or store/pricing-desynced; readers hold no lock across the embed call.
- Rebuild of 20 courses completes in seconds.

## Risk Assessment
| Risk | L×I | Mitigation |
|---|---|---|
| Staff breaks Sheet format | High×High | Per-row validation, skip+collect errors, Telegram alert (Ph05); required-header check |
| Half-edited row → course quoted with missing/empty pricing as official | Med×High | Partial-row validation class: required-field (incl `hoc_phi`) non-empty else skip/exclude + alert |
| Prompt injection via Sheet cell (override golden rule / forge trust-marker) | Med×High | Wrap chunks as UNTRUSTED-DATA (data≠instructions); reject pricing cells w/ newline/marker/instruction patterns; lock down + audit Sheet edit access |
| Vector-store concurrency: lock held across embed call / store↔pricing desync | Med×High | rebuild off event loop; single immutable `(store,pricing,version)` snapshot swapped by one atomic rebind; lock-free readers |
| Pricing leaks into embeddings (bịa giá vector) | Low×High | Parser hard-excludes `hoc_phi`/`uu_dai` from page_content; unit test asserts absence |
| Sync error crashes service | Med×High | try/except in rebuild; keep last-good snapshot; retry next interval |
| gspread quota (300 req/min) | Low×Med | 1 batch call/sync; BackOffHTTPClient auto-retry |
| Embedding API latency/failure mid-rebuild | Med×Med | Rebuild atomic (all-or-nothing snapshot); on fail keep old |

## Security Considerations
- Service-account JSON path from env; file gitignored, least-privilege (only KB + Leads sheets shared to SA email).
- KB contains no PII (course info only) — pricing sensitive commercially, keep Sheet access restricted.
- **Sheet content is untrusted input:** retrieved chunks framed as data (not instructions); pricing cells sanitized at parse (reject newline/trust-marker/instruction patterns) to prevent prompt-injection / forged-official-price. KB Sheet edit access locked-down + audited (business responsibility).
- Log version stamps, not full KB dumps.

## Next Steps
- Unblocks Phase 03: `retrieve_kb` tool wraps `knowledge_base.retrieve`; grade_chunks consumes results; pricing injected into agent context.
- Error callback consumed by Phase 05 Telegram notifier.
