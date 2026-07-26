# Phase 03 — Guard hardening (catalog-bound + date_guard + concession)

## Context Links
- Plan: [plan.md](plan.md) · **Prev (đi chung PR): [phase-02](phase-02-prompt-assembly-retrieve-scope.md)**
- Quyết định: report §A.5, §A.6, §B.6 (luật nhượng bộ giá)
- Code: `graph/nodes/pricing_guard.py`, `common/vn_numerals.py`, `graph/nodes/reflect_node.py`, `graph/prompts/reflect_prompt.py`
- Nền: red-team #1 plan cũ (guard là gate ĐƯỢC THỰC THI, prompt chỉ advisory)

## Overview
- **Priority:** P0 (chặn regression) · **Status:** pending · **Effort:** ~3d *(REVIEW M2: 2d quá mỏng — phase gánh matching 4 tầng + stopword VN + date tokenizer viết mới + concession + test dày + write-site `sales_stage`)*
- Guard hiện **đã có** course-mention binding. Việc của phase này: đổi nguồn input sang catalog 20 khóa, siết matching cho không gian lớn, thêm `date_guard` + luật nhượng bộ giá.

## Key Insights
- **Đính chính so với hiểu ban đầu:** `_resolve_named()` (`pricing_guard.py:54`) đã bind giá theo khóa được NÊU TÊN trong draft. Không xây lại — chỉ repoint + siết.
- **Va chạm tên khóa là rủi ro mới.** `_name_in_draft` khớp khi ≥60% từ (len≥3) của `ten_khoa` xuất hiện trong draft. Với 2–3 khóa retrieve thì ổn; với **cả catalog** (nay 15 khóa, sẽ phình) thì `"Toán 7 Mất Gốc"` vs `"Toán 9 Mất Gốc"` trùng `toán/mất/gốc` = 3/4 = 0.75 → **khớp nhầm** → giá khóa 9 được chấp nhận cho khóa 7. Rủi ro này **tăng theo số khóa**, nên phải siết ngay khi còn 15.
- **Guard KHÔNG chịu ảnh hưởng của `CATALOG_MODE`.** Nó đọc facts qua `get_all_courses()` — dict lookup, **0 token**. Dù prompt chỉ chứa Index (mode `index` tương lai), guard vẫn so được với đủ toàn bộ catalog. Đừng "tối ưu" cắt input của guard theo mode.
- **Fallback `len(retrieved)==1` chết lâm sàng** với catalog 20 → không bao giờ fire. Draft nói giá mà không nêu tên khóa → allowed-set rỗng → chặn hết. An toàn nhưng phải là quyết định tường minh, không phải tác dụng phụ.
- `date_guard` dùng **cùng** cơ chế binding — viết chung file, chung `_resolve_named`. Không tách thành node riêng (thêm node = thêm điểm lỗi, không thêm giá trị).
- **KHÔNG** viết guard cho tên GV / địa chỉ / sĩ số — free text, guard deterministic sẽ nổ false positive. Đây là ranh giới over-engineering đã chốt.
- Luật nhượng bộ giá là **regex + đối chiếu `uu_dai`**, không phải LLM — playbook `gia_cao` (Phase 05) chắc chắn sẽ thử đẻ ra "để em xin ưu đãi riêng".
- **[REVIEW H2] `iter_date_tokens` CHƯA TỒN TẠI.** `vn_numerals.py` chỉ có money/pct, và `_TOKEN_RE` **cố tình né** ngày (docstring: tránh "15/8", "năm 2026", số điện thoại). Viết tokenizer ngày mới, cẩn thận không giẫm lên `_TOKEN_RE`.
- **[REVIEW C4] `pricing_guard.py:105` ghi `sales_stage="cần người"`** — giá trị tiếng Việt cũ. Phase 04 đổi sang `handoff`. **Sửa write-site này NGAY trong phase 03**, đừng để Phase 04 gánh — nếu sót thì state lai 2 hệ giá trị và hỏng im lặng. Tổng có **4 write-site**: `pricing_guard.py:105`, `lead_tools.py:67`, `:113`, `:133`.

## Requirements
**Functional**
- `evaluate_draft(draft, courses)` nhận **catalog** (`get_all_courses()`), không nhận `state["retrieved"]`
- Matching phân tầng: (1) `course_id` xuất hiện → chắc chắn; (2) `ten_khoa` khớp chính xác (substring) → chắc chắn; (3) alias trong `tu_khoa` khớp → chắc chắn; (4) fuzzy word-overlap → chỉ dùng khi **đúng 1** khóa vượt ngưỡng
- **≥2 khóa khớp ở tầng fuzzy → fail-closed** (mập mờ = không cho qua)
- Draft có money/percent token nhưng `named` rỗng → **chặn**, `fix_hint` = "nêu rõ tên khóa khi báo giá"
- `date_guard`: token ngày (`dd/mm`, `dd/mm/yyyy`, `ngày X`) và giờ (`HHhMM`, `HHh–HHh`) trong draft phải khớp `khai_giang`/`lich_hoc` của khóa được nêu
- Luật nhượng bộ: cụm `giảm|bớt|ưu đãi riêng|xin sếp|trường hợp của (chị|anh)|giá đặc biệt` chỉ hợp lệ nếu khớp nguyên văn `uu_dai` của khóa được nêu

**Non-functional**
- `evaluate_draft` thuần/deterministic → unit test dày (đây là gate cuối, không có lưới nào phía sau)
- `pricing_guard.py` <200 LOC → tách `graph/nodes/guard_matching.py` (resolve named) nếu cần
- Fail-closed mọi nhánh: exception trong guard → coi như violation

## Architecture
```
draft ──┐
        ├─► resolve_named(draft, catalog)  ── tầng 1-4, mập mờ → []
catalog ┘            │
                     ├─► money/pct check   ← facts_map (hoc_phi, uu_dai)
                     ├─► date/time check   ← facts_map (khai_giang, lich_hoc)
                     └─► concession check  ← uu_dai nguyên văn
                            │
                     ok ────┴──── violation → HONEST_FALLBACK + handoff=True
```

### Tầng matching (thứ tự, dừng ở tầng đầu tiên có kết quả)
| Tầng | Tín hiệu | Độ chắc |
|---|---|---|
| 1 | `course_id` xuất hiện literal trong draft | chắc chắn |
| 2 | `ten_khoa` là substring của draft (lower, normalize khoảng trắng) | chắc chắn |
| 3 | Alias trong `tu_khoa` là substring | chắc chắn |
| 4 | Word-overlap ≥ ngưỡng, **loại stopword dùng chung** (`toán`, `anh`, `lý`, `lớp`, `khóa`, số lớp) | chỉ nhận khi duy nhất 1 khóa |

Tầng 4 có ≥2 khóa → `named=[]` → mọi số bị chặn (fail-closed, có chủ đích).

## Related Code Files
**Sửa**
- `chatbot/app/graph/nodes/pricing_guard.py` — đổi signature; matching phân tầng; thêm date + concession check
- `chatbot/app/graph/prompts/reflect_prompt.py` — blocklist thêm cụm hối thúc (§B.4) + mốc gọi lại (§B.5)
- `chatbot/app/graph/nodes/reflect_node.py` — dùng blocklist mở rộng (không đổi luồng)
- `chatbot/app/common/vn_numerals.py` — thêm `iter_date_tokens()` nếu chưa có (chuẩn hóa `05/08` ≡ `05/08/2026` ≡ `ngày 5/8`)

**Tạo**
- `chatbot/app/graph/nodes/guard_matching.py` (nếu vượt LOC)
- `chatbot/tests/test_guard_matching.py`, mở rộng `test_pricing_guard.py`

## Implementation Steps
1. `guard_matching.py`: `resolve_named(draft, courses) -> (named: list, ambiguous: bool)` theo 4 tầng ở trên. Stopword list tiếng Việt cho tên khóa (`toán`, `văn`, `anh`, `lý`, `hóa`, `lớp`, `khóa`, `căn`, `bản`, chữ số) — chỉ dùng ở tầng 4.
2. `pricing_guard.py`:
   - `evaluate_draft(draft, courses)`; đọc catalog qua `knowledge_base.get_all_courses()` trong node (giữ `evaluate_draft` thuần, nhận tham số)
   - Bỏ fallback `len(retrieved)==1`; thay bằng: `named` rỗng **và** draft có money token → violation `"báo giá mà không nêu rõ khóa"`
   - `ambiguous=True` → violation `"tên khóa mập mờ, không xác định được giá thuộc khóa nào"`
3. `date_guard` (cùng file): `iter_date_tokens(draft)` so với `khai_giang`+`lich_hoc` của `named`. Chuẩn hóa: bỏ năm khi so nếu draft không nêu năm; `18h`≡`18h00`. Không có `named` mà có token ngày → **cảnh báo, không chặn** (ngày có thể là của FAQ/Center, vd giờ mở cửa) — khác money (money luôn thuộc khóa).
4. Concession check: regex cụm nhượng bộ; hit → yêu cầu chuỗi đó (hoặc con số đi kèm) khớp `uu_dai` của `named`; không khớp → violation.
5. `reflect_prompt.py` blocklist thêm: `còn \d+ chỗ`, `chỉ còn`, `nhanh kẻo`, `sắp hết`, `quyết sớm`, `gấp lên`, `trong hôm nay`, `trong \d+ phút`, `ngay bây giờ`, `chút nữa`. **Lưu ý:** đây là blocklist của `reflect_lite` (có đường sửa 1 lần), không phải guard fail-closed — chọn vậy vì hối thúc là vấn đề giọng điệu, sửa được, không như số liệu sai.
6. Wrap toàn bộ `pricing_guard_node` trong try/except → exception = violation (fail-closed).
7. Test: mỗi tầng matching; va chạm `Toán 7 Mất Gốc` vs `Toán 9 Mất Gốc`; giá đúng-số-sai-khóa; giá không nêu khóa; ngày lệch; `18h` vs `18h00`; "để em xin ưu đãi riêng"; guard ném exception.

## Todo List
- [x] `resolve_named` 4 tầng + stopword + cờ `ambiguous`
- [x] `evaluate_draft` nhận catalog; bỏ fallback `len==1`
- [x] `named` rỗng + có money → chặn
- [x] `ambiguous` → chặn
- [x] `date_guard` + `iter_date_tokens` (new module `common/vn_dates.py`, not vn_numerals)
- [x] Concession check đối chiếu `uu_dai`
- [x] Blocklist hối thúc + mốc gọi lại vào `reflect_prompt`
- [x] try/except bọc node → fail-closed
- [x] `SalesStage` hằng dùng chung + **5 write-site sửa** (found 5 not 4: fallback_node.py:16 was missed) — C4
- [x] Test: va chạm tên khóa, sai khóa, không nêu khóa, ngày lệch, nhượng bộ giá
- [x] compileall + pytest xanh (WSL)

## Success Criteria
- Draft `"Toán 7 Mất Gốc 2.400.000đ"` trong khi facts T7-MG = `1.800.000` → **chặn** (dù 2.400.000 là giá thật của khóa khác)
- Draft `"Toán 9 Mất Gốc..."` không kéo nhầm facts của `Toán 7 Mất Gốc`
- Draft `"học phí bên em 1.800.000đ"` (không nêu khóa) → **chặn** + fix_hint
- Draft `"khai giảng 12/08"` trong khi facts ghi `05/08 và 19/08` → **chặn**
- Draft `"để em xin ưu đãi riêng cho chị"` → **chặn**
- Draft `"lớp học 18h–19h30"` khớp facts `18h00–19h30` → **qua**
- Exception trong guard → honest-fallback + handoff, không crash graph
- Coverage `evaluate_draft` + `resolve_named` ≥90%

## Risk Assessment
| Risk | L×I | Mitigation |
|---|---|---|
| Siết matching quá tay → over-block câu hợp lệ | High×Med | Tầng 1-3 là substring chắc chắn (không siết); chỉ tầng 4 khắt khe. Đo tỉ lệ chặn ở shadow mode (Phase 06) |
| `date_guard` false positive với ngày trong FAQ/giờ mở cửa | Med×Med | Không `named` → cảnh báo thay vì chặn (bước 3) |
| Stopword list thiếu → vẫn va chạm tên | Med×High | Test bảng tên khóa thật của trung tâm, không chỉ ví dụ |
| Regex nhượng bộ bắt nhầm câu mô tả `uu_dai` hợp lệ | Med×Med | Chỉ vi phạm khi **không khớp** `uu_dai` của `named`; câu đọc đúng ô luôn qua |
| Guard chặn nhiều → bot toàn honest-fallback, mất bán hàng | Med×High | Metric "% draft bị chặn theo loại" (Phase 06) là điều kiện go-live |
| **Sót 1 trong 4 write-site `sales_stage`** (C4) | Med×High | Hằng `SalesStage` dùng chung; grep `sales_stage.*=` toàn repo trong review; test assert không còn literal tiếng Việt |
| **Date tokenizer giẫm lên `_TOKEN_RE`** (H2) | Med×Med | Tokenizer ngày tách file/regex riêng; test khẳng định `1.800.000` không bị đọc là ngày và `05/08` không bị đọc là tiền |

## Security Considerations
- Guard là **gate được thực thi duy nhất** cho nguyên tắc vàng — prompt và `reflect_lite` chỉ advisory. Mọi thay đổi ở đây cần test trước, không sửa nóng.
- Fail-closed tuyệt đối: không rõ → chặn. Bot im lặng an toàn hơn bot báo sai giá.
- Catalog đọc từ snapshot đã sanitize (Phase 01) — guard không tự tin vào text chưa qua parser.

## Next Steps
- Merge chung PR với Phase 02.
- Phase 05 (`handle_objection`) phụ thuộc luật nhượng bộ giá ở đây; không bật node objection trước khi guard này xanh.
