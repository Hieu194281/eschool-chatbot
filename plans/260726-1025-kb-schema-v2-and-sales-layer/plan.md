---
title: "KB Schema v2 (3-tab, hybrid in-context) + Sales Layer"
description: "Chuyển khóa học từ RAG sang in-context (phương án C), tách Sheet thành 3 tab, siết guard cho không gian 20 khóa, và bổ sung tầng sales: stage machine, khơi gợi, xin SĐT có luật, node objection đầy đủ."
status: completed
priority: P1
effort: 13d (actual: 1 session, all 6 phases)
branch: master
tags: [chatbot, langgraph, rag, sales, python, backend]
blockedBy: []
blocks: []
created: 2026-07-26
---

# KB Schema v2 + Sales Layer

> Nâng cấp trên nền Pha 1 đã engineering-complete (`plans/260707-0048-tuyensinh-concierge-pha1/`, status completed).
> Nguồn quyết định (LOCKED): `plans/reports/brainstorm-260726-1007-kb-rag-schema-tuyensinh.md`.
> Không đổi xương sống graph — thêm/đổi node + đổi nguồn dữ liệu vào prompt.

**Goal:** Bot trả lời được câu cấp trung tâm (địa chỉ/thủ tục/thanh toán) không cần handoff, không bao giờ trượt retrieval trên khóa học, và có tầng sales dẫn khách tới SĐT + lịch học thử theo luật rõ ràng.

**Thay đổi cốt lõi:** khóa học (mô tả + facts verbatim) chuyển từ vector store lên **system prompt**; vector store chỉ còn FAQ + Center. Sheet 1 tab → **3 tab**. Guard repoint input + siết matching. Thêm stage machine + `detect_objection`/`handle_objection`.

**Quy mô hiện tại: 15 khóa** (xác nhận 2026-07-26), sẽ phình dần → xem §Đường tăng trưởng.

## Đường tăng trưởng catalog (thay cho ngưỡng "50 khóa → quay lại RAG")

Catalog tách **2 tầng ngay từ Phase 01**, cùng keyed theo `course_id`:

| Tầng | Nội dung | Token/khóa |
|---|---|---|
| **Index** — always-on **vĩnh viễn** | `id · tên · đối tượng 1 dòng · hình thức` | ~25 |
| **Detail** | prose + facts đầy đủ | ~440 |

| Quy mô | Mode | Prompt catalog |
|---|---|---|
| **≤30 khóa** *(hiện tại: 15)* | `full` — Index + Detail toàn bộ | ~7K |
| 30–80 khóa | `index` — Index + tool `get_course_detail(course_id)` | ~2K |
| >80 khóa | Lúc đó mới bàn RAG cho phần **mô tả**; facts **vĩnh viễn** lookup theo id | — |

**Vì sao không phải "quay về RAG":** khi phình, tầng Detail rời prompt sang `get_course_detail(cid)` — **tra cứu dict theo khóa chính**, không phải similarity search. Agent đọc Index (chính xác) → chọn `cid` → lấy detail (chính xác). Không có bước nào mờ, nên tính chất "không bao giờ trượt retrieval trên khóa học" được giữ ở mọi quy mô. Chuyển mode = thêm 1 tool + 1 flag `CATALOG_MODE`, **không refactor**.

**Index xây ngay ở Phase 01** vì nó có giá trị hôm nay (mục lục đầu khối catalog, giúp LLM điều hướng 15 block dài), đồng thời là bản lề tăng trưởng. Tool `get_course_detail` **chưa xây** (YAGNI) — chỉ ghi ngưỡng kích hoạt.

**`pricing_guard` KHÔNG chịu ảnh hưởng của bất kỳ ngưỡng nào** — nó đọc facts qua `get_all_courses()` (dict lookup, O(n) bộ nhớ, **0 token**). Dù 15 hay 500 khóa, guard luôn so được với đủ toàn bộ catalog. Đừng "tối ưu" nhầm chỗ này.

## Phases

| Phase | Name | Status | Notes |
|-------|------|--------|-------|
| 01 | [Sheet schema v2 + parsers](phase-01-sheet-schema-v2-parsers.md) | completed | KbRows + CenterFaqResult dataclass; doc_id stable (hash-based) |
| 02 | [Prompt assembly + retrieve scope](phase-02-prompt-assembly-retrieve-scope.md) | completed | Dedupe C1; cap C2; retrieved_this_turn H1; test_tool_exec/vector_store added |
| 03 | [Guard hardening + date + concession](phase-03-guard-hardening.md) | completed | 5 write-sites fixed C4; vn_dates module separate from vn_numerals H2 |
| 04 | [Sales state machine](phase-04-sales-state-machine.md) | completed | phone_asked_at stamped in reflect (not capture); `capture_lead` schema 11 tham số (H3 ✓) |
| 05 | [Objection subsystem](phase-05-objection-subsystem.md) | completed | route_after_reflect 3 routes C3; escalation → handoff+Telegram (not advisory) |
| 06 | [Tests + metrics](phase-06-tests-shadow-metrics.md) | code-done | Metrics emit all guard/detect/lead/tools; summarize script ready; shadow mode/go-no-go **operational only** |

## Dependencies

```
01 ──> 02 ──> 03 ──> 04 ──> 05 ──> 06      (tuần tự — xem M3, không còn nhánh song song)
       └─ 02+03 CHUNG PR ─┘
```

- **03 PHẢI đi liền ngay sau 02.** Sau 02, khóa học rời `retrieved` → guard đang so với tập rỗng/sai khóa. Merge 02 mà chưa có 03 = **cửa sổ regression an toàn số liệu**. Hai phase này nên đi chung 1 PR/commit range, không deploy riêng.
- **[REVIEW M3] 04 KHÔNG chạy song song 03 được** (tuyên bố cũ sai). Cả hai đụng `pricing_guard.py` và `lead_tools.py`: 03 sửa logic guard + chuẩn hóa 4 write-site `sales_stage` (hằng `SalesStage`), 04 dựng stage machine trên chính hằng đó. **04 nối tiếp sau 03.**
- 05 cần 04 (stage + objection_count) và hưởng lợi từ 02 (catalog in-context → objection node không cần tool). 05 cũng sửa `reflect_node.route_after_reflect` (C3) → đụng file của 03; nối tiếp, không song song.

## Plan Review — 2026-07-26

Đối chiếu plan với code thật. **14 phát hiện, đã áp fix vào các phase file.**

| # | Sev | Phát hiện | Áp vào |
|---|---|---|---|
| C1 | 🔴 | `tool_exec._merge_hits` dedupe theo `course_id` → nhiều FAQ chung (`course_id` rỗng) bị nuốt còn 1, im lặng | Ph01 (`doc_id`), Ph02 (dedupe) |
| C2 | 🔴 | `retrieved` merge dồn qua từng lượt + được checkpoint → phình vô hạn | Ph02 (`MAX_RETRIEVED=8`) |
| C3 | 🔴 | `route_after_reflect` chỉ có `agent`/`pricing_guard` → draft objection bị chê rơi về `agent` lạc playbook | Ph05 (3 đích + `objection_fix_done`) |
| C4 | 🔴 | 4 write-site ghi `sales_stage` giá trị tiếng Việt cũ (`pricing_guard.py:105`, `lead_tools.py:67/113/133`) | Ph03 (hằng `SalesStage`) |
| C5 | 🔴 | Plan ép `values_batch_get` — over-engineering (quota dùng 0.6/300 req/min) và tự tạo rủi ro lệch cột | Ph01 (3× `get_all_records()`) |
| H1 | 🟠 | `grade_node` chấm `retrieved` tích lũy → phán "đủ" nhờ chunk lượt trước, không fallback khi thật sự thiếu | Ph02 (`retrieved_this_turn`) |
| H2 | 🟠 | `iter_date_tokens` chưa tồn tại; `_TOKEN_RE` cố tình né ngày → phải viết mới. Ph03 2d quá mỏng | Ph03 (→3d) |
| H3 | 🟠 | Schema `@tool capture_lead` chỉ 5 tham số — thêm field vào `LeadProfile` mà quên schema = tầng khơi gợi vô dụng | Ph04 |
| H4 | 🟠 | `agent_node`/`tool_exec`/`vector_store` — 3 file sửa nặng nhất KHÔNG có test hiện có | Ph02 (viết test tại chỗ) |
| H5 | 🟠 | `pricing_context` là field ConvState mồ côi (ghi mà không ai đọc) | Ph02 (xóa field) |
| M1 | 🟡 | `k=3` hardcode `tool_exec_node.py:62`; store FAQ-centric cần k lớn hơn | Ph02 (k=5) |
| M2 | 🟡 | Effort Ph03 (P0) 2d → 3d; tổng 12d → 13d | plan.md |
| M3 | 🟡 | Tuyên bố "04 song song 03" **sai** — chung `pricing_guard.py`/`lead_tools.py` | plan.md (tuần tự) |
| M4 | 🟡 | Không có bước verify Sheet đúng schema trước deploy | Ph01 (`verify-sheet-schema.py`) |

## Implementation — 2026-07-26

**Status:** 309 tests pass (WSL); all code <200 LOC; graph compiles (test thật, không chỉ route thuần). Shipped: 3-tab KB v2; catalog in-context; guard 4-tier + date + concession; 6-stage machine; 5-group objection; metrics + shadow mode.

**Code review (`plans/reports/code-reviewer-260726-1104-...md`): 3 critical + 9 high — ĐÃ SỬA HẾT**, mỗi mục có regression test:

| # | Lỗ hổng | Fix |
|---|---|---|
| C1 | Guard bind nhiều khóa → hợp nhất facts → giá khóa A gán khóa B vẫn qua | Bind **theo từng câu**; câu nêu ≥2 khóa + số tiền → chặn; `_drop_shadowed` bỏ tên khóa bị tên dài hơn che |
| C2 | "bốn triệu rưỡi" vô hình với tokenizer | Word-numeral trong `vn_numerals` |
| C3 | Ô prose/`ten_khoa`/`Center.always` không sanitize → giả khối `[SỐ LIỆU CHÍNH THỨC]` | `is_prose_cell_safe` + fold dấu/khoảng trắng khi so trust-marker |
| H1 | Escalation Ph05 chỉ set cờ advisory, không ai được báo | `detect_objection._escalate` gọi handoff table + Telegram |
| H2 | `sales_stage=handoff` hấp thụ, ghi bởi fallback/guard → 1 fallback thường giết tầng sales | fallback/guard **không** ghi stage nữa |
| H3 | `DA_BAO_GIA` không nơi nào ghi → bot không bao giờ xin SĐT | Guard ghi khi verdict sạch + có giá đã verify (`advance_stage`) |
| H4/H5 | Alias ngắn + chữ số trong giá cướp binding | Alias ≥4 ký tự + word-boundary; tier-4 strip span tiền/ngày bằng chính tokenizer |
| H6 | Phone gate early-return làm bypass blocklist hứa hẹn cấm | Gate chạy **sau** blocklist |
| H7 | `tool_rounds`/`reflect_count` không reset → cap tính cả hội thoại | `detect_objection._TURN_RESET` |
| H8 | `build_graph()` chưa từng chạy trong test | Cài langgraph + `test_graph_wiring.py` |
| H9 | Sheet Leads thiếu header 6 cột PII mới | `verify-sheet-schema.py` kiểm, fail cứng |

**Review vòng 2** (verify bằng cách chạy code, không đọc diff) — 4 lỗ vẫn khai thác + 3 defect DO CHÍNH FIX VÒNG 1 gây ra. Đã sửa hết:

| # | Vấn đề | Fix |
|---|---|---|
| N1 | Regex cắt câu không tách được câu kết thúc bằng chữ số → binding theo câu âm thầm thoái hóa về theo cả draft | Bỏ lookbehind `(?<!\d)` |
| N2 | Binding suy đoán kéo theo check ngày → chặn đúng các câu mà playbook `co_sdt`/`da_hen_lich` yêu cầu nói (giờ mở cửa, lịch học thử) | `check_schedule` chỉ chạy khi câu tự nêu tên khóa |
| N3 | Escalation set handoff table giữa lượt → dispatcher drop chính câu chào của bot ⇒ khách nhận **im lặng** | `_invoke_graph` trả `(reply, self_escalated)`; đây cũng là consumer thật đầu tiên của `state["handoff"]` |
| V1 | `resolve_named` dừng ở tier đầu → nêu 1 khóa bằng id + 1 bằng alias thì đếm ra 1 → block đa-khóa không nổ | Hợp nhất tier 1-3 |
| V2 | `_drop_shadowed` bỏ cả khóa được nêu **riêng** → mở lại đúng lỗ C1 | So theo span, không theo substring |
| V3 | "mười lăm triệu" → 5.000.000: **giá trị SAI**, tệ hơn bỏ sót vì trông như đã verify | `_word_number()` parse hàng chục + đuôi ("một triệu tám") |
| V4 | `_INJECTION_RE` khớp trên raw có dấu → bỏ dấu là qua hết | Chuyển sang `cell_sanitizer.py`, pattern không dấu, khớp trên `fold()` |
| N6 | `_TURN_RESET` là dict module-level → chia sẻ cùng 1 list giữa các thread | `turn_reset()` trả dict mới |
| N7 | Test wiring chứng minh reachability, chưa phải dominance | Assert `pricing_guard` là predecessor DUY NHẤT của END |

**Review vòng 3** — segmentation và span-drop **chịu được tấn công** (không dựng được draft nào cắt đứt money token hay làm span-drop bỏ nhầm khóa). 1 critical mới + 3 lỗ đuôi:

| # | Vấn đề | Fix |
|---|---|---|
| X1 🔴 | Fix N3 dùng `state["handoff"]` — cờ này **không bao giờ được clear** và cũng do fallback/guard ghi advisory ⇒ sau lần honest-fallback ĐẦU TIÊN, mọi lượt sau đều "trông như đã escalate", bot nói đè lên người thật vừa tiếp quản (mở lại red-team #11) | Tách cờ `escalated` — chỉ `run_handoff_to_human` ghi; `turn_reset()` clear cả `handoff` lẫn `escalated` |
| W1 | "muoi lam trieu" (không dấu) → **không khớp gì cả** ⇒ giá vô hình, đúng lỗi C2 | Thêm spelling không dấu (`lam`, `nham`, `tu`) |
| W2 | Thiếu đơn vị "tỷ" | Thêm nhóm `bil` |
| X3 | Tier-2 `ten_khoa` thiếu word-boundary (alias đã có từ vòng 2) | `_whole_word_in` dùng chung |

**Review vòng 4** — X1 xác nhận đóng (reviewer tấn công lại cờ mới, không dựng được đường nào để `escalated` sống sót sang lượt sau). 5 defect mới, đã sửa hết:

| # | Vấn đề | Fix |
|---|---|---|
| Y2 🟠 | `set_active` lỗi nhưng vẫn trả `escalated`+`sales_stage=HANDOFF` ⇒ 1 lần DB chớp tắt là thread bị park VĨNH VIỄN vào "người thật đã tiếp quản" trong khi **không ai tiếp quản** và bot vẫn trả lời — H2 quay lại qua đường lỗi | Chỉ claim ownership khi ghi row thành công; lỗi → advisory, lượt sau thử lại |
| Y1 🟠 | Đơn vị `tỷ` tôi vừa thêm nuốt luôn "tỷ lệ đậu" / "tỉ mỉ" → 1e9 → chặn oan câu thường | Negative lookahead `lệ/mỉ/phú` |
| Y3 | `_spans` dùng substring thô trong khi matcher dùng word-boundary → 2 helper bất đồng về "thế nào là khớp" | Dùng chung một luật |
| Y4 | Thiếu `tram` không dấu (bất nhất với chính lý do sửa W1) | Thêm |
| Y5 | Escalation phát metric dưới 2 tên (`turn.handoff` vs `objection.escalated`) ⇒ escalation qua tool không bao giờ vào bảng go-live | Thống nhất `escalated` |

**329 tests.** Còn mở (chấp nhận, có lý do ghi rõ):
- **W5 — gate chống injection là best-effort, KHÔNG phải control.** Nó là blocklist từ khóa; reviewer dựng được 7 paraphrase lọt. Hệ quả về **tiền và hứa hẹn** vẫn bị chặn bởi `check_money`/`_FREE_RE`/reflect (không dựa trên từ khóa). Cái không chặn được là override hành vi không để lại dấu vết số. ⇒ **Quyền sửa Sheet mới là ranh giới tin cậy thật** — đưa Sheet vào access review.
- W3 (lịch học thử cùng câu với tên khóa vẫn bị chặn), X2 (số bằng chữ bắt nhầm "ba nghìn từ vựng"), M4 (tiền cọc có thể bị đọc thành học phí), M8 (2 lần đọc snapshot/lượt — fail-closed), N4 (nhiều khóa nối bằng dấu phẩy trong 1 câu), dangling tool_call nếu cap tool nổ trong cùng lượt.

### Key Deviations
- Ph03 C4: **5 write-sites** fixed (not 4 — fallback_node missed); Ph03 H2: date_guard in new module `common/vn_dates`; Ph04: phone_asked_at in reflect (not capture); Ph05: escalation→handoff+Telegram.

## Deploy Prerequisites

1. **Google Sheet KB** — run `scripts/verify-sheet-schema.py`: Courses +9 columns; Center (chu_de/noi_dung/loai/tu_khoa); FAQ (cau_hoi/tra_loi/course_id/tu_khoa); **3 required Center rows** (Trả góp, Test đầu vào, Cam kết gọi lại) loai=verbatim.

2. **Leads sheet** — append 6 columns IN ORDER (L–Q): lop, tinh_trang, muc_tieu, co_so, lich_ranh, khung_gio_tien. Script fails hard if missing.

3. **Test env** — install langchain-core + langgraph (WSL). CI includes graph smoke test.

4. **SHADOW_MODE=true** until Phase 06 operational gates (volume + go/no-go) pass. Blocks real sends without deploy.

## Rollback

Mỗi phase = 1 commit revert được. KB rebuild từ Sheet mỗi 5 phút (stateless) → revert code là đủ, không cần migrate dữ liệu. Sheet giữ ngược tương thích: tab `Courses` chỉ **thêm** cột, cột cũ không đổi tên → code cũ vẫn đọc được nếu phải revert. `SHADOW_MODE=true` chặn mọi send mà không cần deploy.

**Ngoại lệ:** nếu 02 đã merge mà 03 chưa, phải revert 02 chứ không được để chạy — xem §Dependencies.

## Quan hệ với plan cũ

`260707-0048-tuyensinh-concierge-pha1` status `completed` → không block. Plan này **thay thế** một phần quyết định của phase-02 (KB layer) và phase-03 (brain) trong plan đó, và **kéo `handle_objection` từ Out-of-scope Pha 2 lên**. Không sửa file phase cũ; plan này là nguồn mới cho các quyết định chồng lấn.

## Ràng buộc kỹ thuật

- Mỗi file `.py` < 200 LOC; snake_case cho Python (xem Naming convention plan cũ)
- Windows host không có Python → chạy/test qua **WSL Ubuntu**
- Không hard-pin version; model IDs `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-embedding-001`
- Shadow mode đo metrics trước khi thả tự động
