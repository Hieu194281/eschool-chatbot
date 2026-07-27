# Phase 02 — Prompt assembly (catalog in-context) + thu hẹp retrieve

## Context Links
- Plan: [plan.md](plan.md) · Prev: [phase-01](phase-01-sheet-schema-v2-parsers.md) · **Next (BẮT BUỘC liền kề): [phase-03](phase-03-guard-hardening.md)**
- Quyết định: report §A.1 (phương án C), §A.2, §A.4
- Code: `kb/vector_store.py`, `graph/prompts/system_prompt.py`, `graph/nodes/agent_node.py`, `tool_exec_node.py`, `grade_node.py`, `graph/tools/retrieve_kb_tool.py`

## Overview
- **Priority:** P1 · **Status:** pending · **Effort:** ~1.5d
- Chuyển 20 khóa (prose + facts) từ vector store lên **system prompt**. Vector store chỉ còn FAQ + Center embed docs. `retrieve_kb` đổi phạm vi.

## Key Insights
- **⚠️ Phase này một mình tạo regression.** Sau khi khóa học rời `state["retrieved"]`, `pricing_guard.evaluate_draft(draft, retrieved)` so với tập không còn chứa khóa → allowed-set rỗng hoặc sai. **Không deploy 02 mà thiếu 03.** Hai phase đi chung PR.
- Snapshot phải mang thêm `course_blocks` + `center_always` + `facts_map`, swap bằng **một** atomic rebind như hiện tại — không thêm biến rời (desync).
- System prompt trở thành **động** (đổi mỗi lần sync KB) → không còn là hằng module-level. Phải build per-turn từ snapshot, nhưng giữ thứ tự khối **ổn định** để context caching của Gemini còn ăn prefix.
- `grade_chunks` giờ chỉ chấm FAQ/Center. Ngữ nghĩa "insufficient → fallback + handoff" vẫn giữ, nhưng **không được** kích hoạt cho câu hỏi khóa học (đã có đủ trong prompt) — nếu không bot sẽ handoff oan.
- `agent_node`/`tool_exec_node` hiện ghép `pricing_context` theo hit → **bỏ**, vì facts đã always-on. Để lại sẽ inject trùng lặp + tăng cơ hội LLM nhặt nhầm.
- **15 khóa** (xác nhận 2026-07-26) → catalog ~7K, tổng prompt ~9K (gồm playbook Ph04). Mode `full`.
- **Catalog gồm 2 khối, thứ tự cố định:** `[MỤC LỤC KHÓA]` (index 1 dòng/khóa, ~375 tok) rồi mới `[CHI TIẾT KHÓA]` (15 block). Index không chỉ để dành cho tương lai — nó là **mục lục** giúp LLM điều hướng 15 block dài ngay hôm nay.
- **Ngưỡng chuyển mode: >30 khóa** → `CATALOG_MODE=index` (Index + tool `get_course_detail(cid)`). Tool **chưa xây** ở phase này (YAGNI); chỉ log cảnh báo khi vượt ngưỡng. Xem plan.md §Đường tăng trưởng.

### [REVIEW] 4 lỗi tiềm ẩn trong code hiện tại mà phase này KÍCH HOẠT
- **C1 — `_merge_hits` dedupe theo `course_id`** (`tool_exec_node.py:17-24`). FAQ chung có `course_id` rỗng → nhiều FAQ hit cùng `""` bị nuốt còn **1**, im lặng. Bug chắc chắn nổ khi store chuyển sang FAQ-centric. **Phải sửa trong phase này**: dedupe theo `metadata.doc_id` (Phase 01 cấp).
- **C2 — `retrieved` tích lũy vô hạn.** `tool_exec` merge dồn vào `state["retrieved"]`, mà field này được checkpoint → hội thoại dài phình không giới hạn. Trước đây bị chặn tự nhiên bởi ~20 course_id; sau C1-fix thì không còn chặn. **Cap `MAX_RETRIEVED` (đề xuất 8, giữ hit mới nhất).**
- **H1 — `grade_node` chấm `retrieved` tích lũy, không chấm hit lượt này** (`grade_node.py:28`). Khách hỏi câu mới không trúng gì → grade vẫn thấy chunk lượt trước → phán "sufficient" → **không fallback dù thiếu dữ liệu thật**. Phải truyền hit **của lượt hiện tại** cho grade (thêm `retrieved_this_turn` transient), không dùng field tích lũy.
- **H5 — `pricing_context` thành field mồ côi**: `state.py:27` khai báo, `tool_exec` ghi, không ai đọc. Xóa cả field khỏi `ConvState`, không chỉ xóa hàm.

## Requirements
**Functional**
- `KnowledgeBase` expose `get_catalog_text()`, `get_center_always()`, `get_facts(course_id)`, `get_all_courses()` (cho guard Phase 03)
- `build_system_prompt()` ráp: nguyên tắc vàng + bảng cấm → `[THÔNG TIN TRUNG TÂM]` → `[DANH MỤC KHÓA]` → (chỗ dành cho `[SALES PLAYBOOK]` Phase 04)
- `retrieve_kb` chỉ tra FAQ + Center; docstring/tool description đổi để agent hiểu **không** dùng nó cho câu hỏi khóa học
- KB chưa ready (snapshot None) → system prompt vẫn dựng được (khối rỗng), không crash

**Non-functional**
- Thứ tự khối cố định (caching-friendly); catalog sort theo `course_id` để prefix ổn định giữa các lần sync
- Log token estimate + số khóa mỗi sync; cảnh báo khi >50 khóa

## Architecture
```
_Snapshot(store, facts_map, course_blocks, center_always, meta, version)
        │                    │              │
        │ (FAQ+Center docs)  │              │
        ▼                    ▼              ▼
   retrieve_kb        build_system_prompt()  ──► agent / handle_objection
   (FAQ/Center)              │
        │                    └── [DANH MỤC KHÓA] 20 khối (prose + facts)
        ▼
   grade_chunks (chỉ FAQ/Center)
```

Prompt (thứ tự cố định):
```
1. Persona + NGUYÊN TẮC VÀNG + bảng CẤM        (tĩnh)
2. [THÔNG TIN TRUNG TÂM]                        ← center_always
3. [MỤC LỤC KHÓA] — N dòng, sort theo course_id ← course_index   (~375 tok)
4. [CHI TIẾT KHÓA] — N khối, cùng thứ tự        ← course_blocks   (mode `full`)
5. [SALES PLAYBOOK]                             ← Phase 04 (chỗ trống ở phase này)
6. [DỮ LIỆU KHÔNG TIN CẬY] FAQ/Center chunks    ← per-turn
```

## Related Code Files
**Sửa**
- `chatbot/app/kb/vector_store.py` — `_Snapshot` thêm `course_blocks`, `center_always`, `facts_map` (rename từ `pricing`); readers mới; store chỉ add FAQ/Center docs
- `chatbot/app/graph/prompts/system_prompt.py` — `SYSTEM_PROMPT` hằng → `build_system_prompt()`; sửa mục "CÁCH LÀM VIỆC" (retrieve_kb không dùng cho khóa học)
- `chatbot/app/graph/nodes/agent_node.py` — dùng `build_system_prompt()`; bỏ `pricing_lines`
- `chatbot/app/graph/nodes/tool_exec_node.py` — bỏ `_pricing_context`
- `chatbot/app/graph/nodes/grade_node.py` — chỉ chấm FAQ/Center; không route fallback cho câu hỏi khóa học
- `chatbot/app/graph/tools/retrieve_kb_tool.py` — đổi description + scope
- `chatbot/app/graph/state.py` — `retrieved` đổi nghĩa (FAQ/Center), comment lại

## Implementation Steps
1. `vector_store.py`: `rebuild()` gọi `load_kb()` + cả 2 parser; docs đưa vào store = **chỉ** FAQ + Center embed; `_Snapshot` frozen dataclass thêm 3 field; giữ nguyên pattern rebuild-off-loop + một rebind. Rename `pricing`→`facts` toàn file (giữ `get_pricing()` làm alias deprecate 1 phase để tránh vỡ import).
2. Thêm readers: `get_catalog_text()` (join `course_blocks` sort theo cid), `get_center_always()`, `get_facts(cid)`, `get_all_courses()` → `[{course_id, ten_khoa, tu_khoa, facts}]` (Phase 03 cần).
3. `system_prompt.py`: `build_system_prompt(catalog, center, playbook="")` thuần hàm (dễ test); `SYSTEM_PROMPT` giữ phần tĩnh. Sửa dòng "Khi khách hỏi về khóa học/học phí/lịch → GỌI `retrieve_kb`" thành: khóa học **đã có sẵn trong `[DANH MỤC KHÓA]`, không cần gọi tool**; chỉ gọi `retrieve_kb` cho FAQ/thủ tục/chính sách/thông tin trung tâm.
4. `agent_node.py`: build prompt từ snapshot mỗi turn; xóa `pricing_lines`.
5. `tool_exec_node.py`: xóa `_pricing_context`; `retrieved` item = `{text, source, doc_id, course_id?}`; **`_merge_hits` dedupe theo `doc_id`** (C1); **cap `MAX_RETRIEVED=8`, giữ mới nhất** (C2); ghi thêm `retrieved_this_turn` (transient, chỉ hit của lượt này) cho grade.
6. `grade_node.py`: chấm **`retrieved_this_turn`**, KHÔNG chấm `retrieved` tích lũy (H1). Nếu agent **không gọi tool** (câu hỏi khóa học đã có trong catalog) → không đi qua grade, không coi là insufficient.
6b. `state.py`: **xóa `pricing_context`** (mồ côi, H5); thêm `retrieved_this_turn`; cập nhật comment `retrieved` = FAQ/Center only.
7. Log mỗi sync: `courses=N, catalog_tokens≈X, faq_docs=Y`; `logger.warning` khi **N>30** — ngưỡng chuyển `CATALOG_MODE=index` (plan.md §Đường tăng trưởng). Cảnh báo nêu rõ hành động cần làm, không chỉ báo số.
8. WSL: compileall + pytest hiện có (một số test sẽ đỏ do rename — sửa cùng phase, **không** skip).

## Todo List
- [x] `_Snapshot` + readers (`get_catalog_text`, `get_center_always`, `get_facts`, `get_all_courses`)
- [x] Store chỉ chứa FAQ + Center docs (không doc `source=course`)
- [x] `build_system_prompt()` thứ tự khối cố định + sort theo `course_id`
- [x] `[MỤC LỤC KHÓA]` đứng TRƯỚC `[CHI TIẾT KHÓA]`, cùng thứ tự sort
- [x] Cảnh báo khi >30 khóa nêu rõ hành động
- [x] `retrieve_kb` đổi description + scope
- [x] Xóa `pricing_context` ở agent_node + tool_exec_node + ConvState (H5)
- [x] `_merge_hits` dedupe theo `doc_id` (C1) + test nhiều FAQ cùng `course_id` rỗng
- [x] Cap `MAX_RETRIEVED=8` giữ hit mới nhất (C2)
- [x] `grade_node` chấm `retrieved_this_turn` (H1)
- [x] `grade_chunks` không handoff khi agent không gọi tool
- [x] Nâng k=5 cho retrieve FAQ (M1)
- [x] Log token estimate + cảnh báo >50 khóa
- [x] `test_tool_exec.py`, `test_vector_store.py` viết mới (H4)
- [x] Test hiện có xanh sau rename
- [x] Merged với Phase 03 (bắt buộc)

## Success Criteria
- Hỏi "trung tâm ở đâu" → trả lời đúng từ `center_always`, **không** gọi tool, không handoff
- Hỏi "con lớp 7 yếu toán học khóa nào" → bot liệt kê/route đúng khóa mà không cần retrieve
- Hỏi "có giữ xe không" → retrieve trúng FAQ doc
- Không Document nào trong store có `metadata.source == "course"`
- Sync 20 khóa vẫn xong trong vài giây (ít doc hơn trước → nhanh hơn)
- Log hiện `courses`, `catalog_tokens`, cảnh báo ngưỡng

## Risk Assessment
| Risk | L×I | Mitigation |
|---|---|---|
| **Merge 02 thiếu 03 → guard so tập rỗng/sai khóa** | High×High | Ràng buộc quy trình: 02+03 chung PR; checklist "không merge lẻ" ở Todo |
| Prompt động phá context caching | Med×Med | Thứ tự khối cố định + sort `course_id`; phần tĩnh đứng đầu |
| `grade_chunks` handoff oan khi agent không gọi tool | Med×High | Bước 6 — phân biệt "không gọi tool" vs "gọi nhưng không trúng" |
| Rename `pricing`→`facts` vỡ import chỗ khác | Med×Med | Giữ alias `get_pricing()` 1 phase; grep toàn repo trước khi xóa |
| **FAQ hit bị nuốt do dedupe `course_id`** (C1) | **High×High** | Dedupe theo `doc_id`; test nhiều FAQ cùng `course_id` rỗng |
| **`retrieved` phình vô hạn qua hội thoại dài** (C2) | High×Med | Cap `MAX_RETRIEVED=8` |
| **grade phán "đủ" nhờ chunk lượt trước** (H1) | High×High | Chấm `retrieved_this_turn`; test 2 lượt liên tiếp khác chủ đề |
| Sửa 3 file không có test hiện có (H4) | High×Med | Viết `test_tool_exec.py` + `test_vector_store.py` **trong phase này**, không đẩy sang 06 |
| KB phình vượt 30 khóa → prompt nặng dần | Med×Med | Log + cảnh báo nêu hành động; chuyển `CATALOG_MODE=index` (thêm 1 tool + 1 flag, **không refactor** — nhờ `course_index`/`course_blocks` đã keyed by cid từ Ph01) |

## Security Considerations
- `center_always` và `course_blocks` được inject với **nhãn tin cậy cao** → Phase 01 sanitize là điều kiện tiên quyết; không được nới.
- Khối FAQ/Center retrieve về vẫn giữ nhãn `[DỮ LIỆU KHÔNG TIN CẬY]` — nhãn này không được áp nhầm cho catalog và ngược lại.
- Prompt dài hơn → đảm bảo log redaction filter (red-team #12 plan cũ) không vô tình dump prompt.

## Next Steps
- **Phase 03 ngay lập tức** — repoint guard sang catalog, siết matching.
- Chỗ trống `[SALES PLAYBOOK]` do Phase 04 điền.
