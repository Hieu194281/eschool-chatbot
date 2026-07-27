# Phase 01 — Sheet schema v2 + parsers (3 tab)

## Context Links
- Plan: [plan.md](plan.md)
- Quyết định: `plans/reports/brainstorm-260726-1007-kb-rag-schema-tuyensinh.md` §A.3
- Code hiện tại: `chatbot/app/kb/sheet_loader.py`, `course_parser.py`, `vector_store.py`
- Nền cũ: `plans/260707-0048-tuyensinh-concierge-pha1/phase-02-kb-layer-sheet-sync-vectorstore.md`

## Overview
- **Priority:** P1 · **Status:** pending · **Effort:** ~2d
- Sheet 1 tab → 3 tab (`Courses` mở rộng, `Center` mới, `FAQ` mới). `pricing_map` → `facts_map` (9 trường verbatim). Parser sinh thêm **`course_index`** (1 dòng/khóa) + **`course_blocks`** (khối detail mỗi khóa) + `center_always` + docs cho FAQ/Center.
- **Quy mô: 15 khóa** → mode `full` (Index + Detail toàn bộ, ~7K token). Xem plan.md §Đường tăng trưởng.

## Key Insights
- **Chỉ THÊM cột vào `Courses`, không đổi tên cột cũ** → Sheet ngược tương thích, revert code không cần sửa Sheet.
- `giao_vien` tách 2: `giao_vien_ten` (verbatim — bịa tên GV rất tệ) + `giao_vien_gioi_thieu` (prose). Cột `giao_vien` cũ giữ lại đọc được nhưng deprecate.
- `tu_khoa` phục vụ 2 mục đích: nối vào `page_content` của FAQ/Center (khách gõ không dấu), và **course-mention detection ở guard** (Phase 03). Không có nó guard khớp nhầm khóa.
- **Sanitize từng ô, không sanitize khối.** Luật cấm newline/trust-marker/instruction áp cho TỪNG ô verbatim; khối multi-line do code dựng. Giữ nguyên `_is_pricing_cell_safe` hiện có, mở rộng sang 9 trường.
- **Partial-row validation mở rộng:** required fields giờ là `course_id`, `ten_khoa`, `hoc_phi`. KHÔNG thêm các cột mới vào required — nửa vời ở `si_so` không đáng loại cả khóa; thiếu thì bỏ dòng đó khỏi facts block, không bỏ cả khóa.
- **KHÔNG có cột số chỗ còn lại** — đã cấm khan hiếm (§B.4 report). Cột này tồn tại là mời bot nói khan hiếm.
- **[REVIEW C5] Dùng 3× `get_all_records()`, KHÔNG dùng `values_batch_get`.** Quota 300 req/min; sync 5 phút/lần → 3 call = 0.6 req/min. Ép batch_get để "giữ 1 API call" là tối ưu vô nghĩa và buộc phải tự map header→dict — tức tự tạo đúng rủi ro lệch-cột rồi tự viết mitigation cho nó. Giữ `open_worksheet()` + `get_all_records()` sẵn có (đã header-keyed).
- **[REVIEW C1] Mỗi Document phải có `doc_id` trong metadata.** FAQ chung có `course_id` rỗng; `tool_exec._merge_hits` hiện dedupe theo `course_id` → nhiều FAQ docs cùng `""` sẽ bị nuốt còn 1. Parser sinh `doc_id` ổn định (vd `faq:{row_idx}`, `center:{chu_de}`) để Phase 02 dedupe đúng.

## Requirements
**Functional**
- `load_kb()` đọc 3 worksheet trong 1 call, trả `(course_rows, center_rows, faq_rows)`
- `parse_courses()` trả `ParseResult` mở rộng: `facts_map`, `course_blocks`, `course_meta` (thêm `tu_khoa`), `errors`
- `parse_center_faq()` trả `(always_text, verbatim_map, docs, errors)`
- Thiếu tab `Center`/`FAQ` → **không fatal** (log + alert, phục vụ với phần có được). Thiếu tab `Courses` → fatal.
- `Center.loai` không thuộc {always, verbatim, embed} → dòng đó vào errors, bỏ qua

**Non-functional**
- `course_parser.py` giữ <200 LOC → tách phần build block sang helper nếu cần
- `center_faq_parser.py` mới, <200 LOC
- Parser thuần logic (không gspread/langchain) → unit test standalone

## Architecture
```
Google Sheet (3 tab)
  ├─ Courses  ─┐
  ├─ Center   ─┼─ kb/sheet_loader.py  load_kb() → 1 batch_get
  └─ FAQ      ─┘
                 │
        ┌────────┴────────┐
        ▼                 ▼
kb/course_parser.py           kb/center_faq_parser.py
  facts_map{cid:str}            always_text: str
  course_index{cid:str}  ← 1 dòng/khóa, always-on VĨNH VIỄN
  course_blocks{cid:str} ← detail, keyed by cid (bản lề mode `index`)
  course_meta{cid:{}}           verbatim_map{chu_de:str}
  errors[]                      docs[] (FAQ 1 dòng=1 doc; Center loai=embed)
                                errors[]
        └────────┬────────┘
                 ▼
        kb/vector_store.py (Phase 02 wiring)
```

### Cột tab `Courses` (thêm mới in đậm)
| Cột | Loại | Ghi chú |
|---|---|---|
| `course_id`, `ten_khoa` | metadata | required |
| **`tu_khoa`** | metadata | alias/không dấu/viết tắt, phân tách bởi `,` |
| `hoc_phi`, `uu_dai` | verbatim | required: `hoc_phi` |
| **`khai_giang`, `lich_hoc`, `thoi_luong`, `si_so`, `hinh_thuc`, `giao_vien_ten`, `co_so`** | verbatim | optional; thiếu → bỏ dòng khỏi block |
| `doi_tuong`, `muc_tieu`, `lo_trinh`, `chinh_sach` | prose | |
| **`giao_vien_gioi_thieu`**, `ghi_chu` | prose | `giao_vien` cũ = fallback nếu cột mới rỗng |

### Tab `Center` / `FAQ`
- `Center`: `chu_de · noi_dung · loai · tu_khoa`. `loai=always` → nối vào `always_text`; `verbatim` → `verbatim_map[chu_de]`; `embed` → Document.
- `FAQ`: `cau_hoi · tra_loi · course_id · tu_khoa` → **1 Document/dòng**, `page_content = f"Q: {cau_hoi}\nA: {tra_loi}\nTừ khóa: {tu_khoa}"`, `metadata={source:"faq", course_id, doc_id:f"faq:{row_idx}"}`. Center embed docs: `metadata={source:"center", doc_id:f"center:{chu_de}"}`. **`doc_id` bắt buộc** — xem Key Insights C1.
- **Bắt buộc có 3 dòng `verbatim`** cho Phase 04/05: `Trả góp`, `Test đầu vào`, `Cam kết gọi lại`. Thiếu → warning vào errors (không fatal).

### Sanitize (mở rộng từ code hiện có)
`VERBATIM_FIELDS` = 9 cột. Mỗi ô: reject nếu chứa newline / `"SỐ LIỆU CHÍNH THỨC"` / `_INJECTION_RE`. Ô `hoc_phi` bẩn → **loại cả khóa** (như hiện tại). Ô verbatim khác bẩn → **bỏ riêng dòng đó** khỏi facts block + alert (không loại cả khóa — `si_so` bẩn không đáng chặn bán hàng). Áp cùng luật cho `Center.loai=verbatim`.

## Related Code Files
**Sửa**
- `chatbot/app/kb/sheet_loader.py` — `load_kb()` batch_get 3 tab; giữ `load_courses()` làm wrapper cho tương thích
- `chatbot/app/kb/course_parser.py` — `VERBATIM_FIELDS` 9 cột; `pricing_map`→`facts_map`; build `course_blocks`; `course_meta` thêm `tu_khoa`; sanitize phân cấp
- `chatbot/app/kb/__init__.py` — export mới

**Tạo**
- `chatbot/app/kb/center_faq_parser.py`
- `chatbot/tests/test_center_faq_parser.py`, mở rộng `test_course_parser.py`

## Implementation Steps
1. `sheet_loader.py`: thêm `load_kb()` gọi `open_worksheet()` + `get_all_records()` **3 lần** (Courses/Center/FAQ) — giữ nguyên pattern hiện có, không tự map header. Tab thiếu (`WorksheetNotFound`) → trả `[]` + ghi errors, không fatal (trừ `Courses`).
2. `course_parser.py`:
   - `VERBATIM_FIELDS = (hoc_phi, uu_dai, khai_giang, lich_hoc, thoi_luong, si_so, hinh_thuc, giao_vien_ten, co_so)`; `PROSE_FIELDS` thêm `giao_vien_gioi_thieu`
   - Sanitize phân cấp: `hoc_phi` bẩn/thiếu → loại khóa; verbatim khác bẩn → drop dòng + error
   - `facts_map[cid]` = join các dòng `"Nhãn: giá trị"` của ô verbatim hợp lệ
   - `course_index[cid]` = `{cid}  {ten_khoa} — {doi_tuong rút gọn ≤80 ký tự} — {hinh_thuc}` (~25 token). **Dict keyed by cid**, không phải chuỗi gộp sẵn — để mode `index` tương lai dùng lại nguyên vẹn.
   - `course_blocks[cid]` = `--- id={cid} "{ten}" ---\n{prose}\n[SỐ LIỆU CHÍNH THỨC — id={cid}]\n{facts}`. **Dict keyed by cid** (bản lề chuyển mode `index` + `get_course_detail(cid)` khi >30 khóa — xem plan.md §Đường tăng trưởng).
   - `course_meta[cid]` thêm `tu_khoa` (list đã split/strip/lower)
   - Nếu file vượt 180 LOC → tách builder sang `kb/course_block_builder.py`
3. `center_faq_parser.py`: validate `loai`; build `always_text` (join `noi_dung` của `loai=always`), `verbatim_map`, `docs` (FAQ mỗi dòng + Center embed); sanitize ô `loai=verbatim`; warning nếu thiếu 3 `chu_de` bắt buộc.
4. Unit tests (không cần network): schema thiếu cột → `KbSchemaError`; ô `si_so` có newline → khóa vẫn phục vụ, mất dòng đó; ô `hoc_phi` có trust-marker → khóa bị loại; `Center.loai` sai → error; FAQ 3 dòng → 3 docs.
5. Chạy WSL: `python -m compileall` + `pytest chatbot/tests -k "parser"`.

## Todo List
- [x] `load_kb()` 3× `get_all_records()` + returns `KbRows` dataclass (not bare tuple)
- [x] `doc_id` ổn định trong metadata (`faq:<sha1[:10]>`, `center:{chu_de}`) — C1 chặn
- [x] Script `scripts/verify-sheet-schema.py` — kiểm Sheet đủ cột/tab trước deploy
- [x] `VERBATIM_FIELDS` 9 cột + sanitize phân cấp (hoc_phi vs verbatim khác)
- [x] `facts_map` + `course_index` + `course_blocks` keyed by `course_id` + `course_meta.tu_khoa`
- [x] `center_faq_parser.py` returns `CenterFaqResult`: always/verbatim/embed + FAQ 1 dòng = 1 doc
- [x] Warning khi thiếu 3 dòng `Center.verbatim` bắt buộc
- [x] Sanitize prose cells, `ten_khoa`, `Center.loai=always` (review finding)
- [x] Unit tests parser (course + center/faq) xanh
- [x] Mọi file <200 LOC

## Success Criteria
- `hoc_phi`/`uu_dai`/7 cột verbatim mới **không xuất hiện** trong bất kỳ `page_content` nào (test assert)
- `facts_map[cid]` byte-identical với ô Sheet cho từng dòng
- Ô `si_so` bẩn → khóa vẫn bán được, chỉ mất dòng sĩ số + có alert
- Ô `hoc_phi` bẩn/rỗng → khóa bị loại hoàn toàn + alert nêu tên khóa
- Thiếu tab `FAQ` → service vẫn chạy, chỉ mất FAQ docs + alert
- 1 sync = 1 API call

## Risk Assessment
| Risk | L×I | Mitigation |
|---|---|---|
| ~~`batch_get` lệch cột~~ — **đã loại bỏ bằng cách không dùng batch_get** (C5) | — | `get_all_records()` tự map header |
| Deploy Phase 01 khi Sheet chưa thêm cột/tab | High×Med | Cột mới optional → không vỡ; tab thiếu → warning. Chạy `verify-sheet-schema.py` trước deploy |
| Nhân viên điền `loai` sai chính tả | High×Med | Dropdown data-validation trong Sheet + error nêu rõ dòng |
| Tách `giao_vien` làm 20 khóa hiện có rỗng cột mới | High×Med | Fallback: `giao_vien_gioi_thieu` rỗng → dùng cột `giao_vien` cũ |
| File `course_parser.py` vượt 200 LOC | Med×Low | Tách `course_block_builder.py` |

## Security Considerations
- Sheet là **untrusted input**. Sanitize mở rộng cho cả 9 cột verbatim + `Center.loai=verbatim` — nếu không, `khai_giang` hoặc `Cam kết gọi lại` trở thành vector prompt-injection mới (chúng cũng được inject với nhãn tin cậy cao).
- Không log full KB dump; chỉ log version stamp (rows/docs/errors).
- Service account least-privilege, chỉ share 2 Sheet (KB + Leads).

## Next Steps
- Unblocks Phase 02 (vector_store consume `course_blocks`/`center_always`; prompt assembly).
- `course_meta.tu_khoa` là input bắt buộc của Phase 03 (guard matching).
