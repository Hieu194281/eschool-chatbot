# Phase 04 — Sales state machine + khơi gợi + luật xin SĐT

## Context Links
- Plan: [plan.md](plan.md) · Prev: [phase-01](phase-01-sheet-schema-v2-parsers.md) (cần `Center.verbatim`)
- Quyết định: report §B.1–B.5
- Code: `graph/state.py`, `graph/tools/lead_tools.py`, `graph/prompts/system_prompt.py`, `integrations/*` (lead Sheet, Telegram)

## Overview
- **Priority:** P1 · **Status:** pending · **Effort:** ~2d
- Biến `sales_stage` (đã có, 5 giá trị mô tả) thành **state machine 6 nấc có next-action xác định**; thêm 5 field khơi gợi vào `LeadProfile`; đóng luật xin SĐT (1 lần/hội thoại) và luật cam kết gọi lại (hỏi giờ, không hứa giờ).

## Key Insights
- **`sales_stage` ĐÃ TỒN TẠI** (`state.py:29`, giá trị `mới | đang tư vấn | đã xin SĐT | đã chốt | cần người`). Mở rộng field này — **không** thêm `stage` song song (DRY; hai nguồn sự thật về nấc bán hàng là lỗi kinh điển).
- `LeadProfile` đã có `ten/sdt/khoa_quan_tam/nhu_cau/do_nong` → **thêm** field, không tạo struct mới.
- **Luật xin SĐT phải cưỡng chế bằng state, không bằng prompt.** Prompt nói "chỉ xin 1 lần" thì LLM vẫn xin lại. Cần `phone_asked_at` + kiểm tra deterministic trước khi cho phép câu xin SĐT đi qua.
- **Bot HỎI giờ, không HỨA giờ** (§B.5). Câu hứa mốc gọi lại đã bị chặn ở blocklist Phase 03. Phase này cung cấp đường thay thế: hỏi `khung_gio_tien` + đọc nguyên văn `Center["Cam kết gọi lại"]`.
- Khơi gợi: **1 câu hỏi/lượt**, chỉ hỏi field **chưa có**, và **không cướp lượt** khi khách còn câu chưa được trả lời. Ba luật này quyết định bot có bị coi là phiền hay không.
- **[ĐÍNH CHÍNH]** Codebase **không** dùng `Command(update=...)`. Cơ chế thật là `ToolResult(message, state_update)` + `tool_exec_node` áp `update.update(result.state_update)` (`tools/lead_tools.py:19`, `tool_exec_node.py:68`) — cố ý tránh phụ thuộc API `Command` theo version LangGraph. **Giữ contract `ToolResult` này**, đừng đổi sang `Command`. Bản chất red-team #2 vẫn đúng: tool phải ghi qua `state_update`, không được chỉ trả `str`.
- **[REVIEW H3] Schema `@tool capture_lead` chỉ có 5 tham số** (`lead_tools.py:26-35`). Thêm field vào `LeadProfile` mà quên sửa **schema `@tool`** → LLM không có đường ghi `lop/tinh_trang/muc_tieu/co_so/lich_ranh/khung_gio_tien` → toàn bộ tầng khơi gợi thành trang trí. Phải sửa **cả hai**: schema `@tool` và `run_capture_lead`.
- **[REVIEW C4] Write-site `sales_stage` đã được sửa ở Phase 03** (hằng `SalesStage` dùng chung). Phase này chỉ còn: `_LEGACY_STAGE_MAP` khi ĐỌC checkpoint cũ + `derive_stage`.

## Requirements
**Functional**
- `sales_stage` ∈ `{moi, da_ro_nhu_cau, da_bao_gia, co_sdt, da_hen_lich, handoff}`; migration: giá trị cũ map sang giá trị mới khi đọc checkpoint cũ
- `LeadProfile` thêm `lop`, `tinh_trang`, `muc_tieu`, `co_so`, `lich_ranh`, `khung_gio_tien`
- `ConvState` thêm `phone_asked_at` (epoch giây | None)
- **Schema `@tool capture_lead` thêm 6 tham số** khơi gợi (H3) — không sửa schema thì LLM không ghi được
- `run_capture_lead` cập nhật stage + field khơi gợi qua `ToolResult.state_update`; upsert Sheet + notify Telegram khi có SĐT
- Playbook trong system prompt: bảng stage→next-action, 5 câu khơi gợi, 4 cớ xin SĐT, bảng CẤM sales
- Deterministic gate: draft chứa ý xin SĐT **và** `phone_asked_at` trong vòng 24h **và** `lead_profile.sdt` rỗng → strip/thay câu xin SĐT (không chặn cả câu trả lời)

**Non-functional**
- `sales_playbook.py` <200 LOC; là dữ liệu text thuần + vài hàm build → dễ test
- Migration stage cũ→mới không làm vỡ checkpoint đang có

## Architecture
```
ConvState.sales_stage  (6 nấc)          LeadProfile (mở rộng)
        │                                      │
        ▼                                      ▼
build_system_prompt(..., playbook=render_playbook(state))
        │
        ├── bảng stage → next action (chỉ chèn dòng của stage HIỆN TẠI)
        ├── câu khơi gợi kế tiếp (field đầu tiên còn trống)
        ├── cớ xin SĐT phù hợp tín hiệu (nếu stage=da_bao_gia)
        └── bảng CẤM sales

@tool capture_lead(... +6 tham số khơi gợi)     ← schema LLM nhìn thấy (H3)
run_capture_lead(...) → ToolResult(msg, state_update={lead_profile, sales_stage, phone_asked_at})
                        └─► tool_exec áp state_update ─► Sheet upsert + Telegram (lead nóng)
```

### Bảng stage → next action
| Stage | Điều kiện vào | Next action DUY NHẤT |
|---|---|---|
| `moi` | mặc định | Hỏi khơi gợi #1 (`lop`) |
| `da_ro_nhu_cau` | có `lop` + `tinh_trang` | Đề xuất khóa cụ thể + lộ trình, **chưa báo giá** |
| `da_bao_gia` | đã nói học phí | Xin SĐT kèm cớ (1 lần) |
| `co_sdt` | có `sdt` | Hỏi `khung_gio_tien` + đề xuất chốt lịch học thử |
| `da_hen_lich` | có ngày giờ học thử | Xác nhận, nhắc mang gì, **dừng bán** |
| `handoff` | cờ handoff | Im |

**Chỉ chèn dòng của stage hiện tại** vào prompt, không chèn cả bảng — giảm nhiễu, LLM bám next-action tốt hơn.

### 4 cớ xin SĐT (chọn theo tín hiệu, dữ liệu từ `Center.verbatim`)
| Tín hiệu | Cớ | Nguồn dữ liệu |
|---|---|---|
| Lo con yếu, chưa rõ trình độ | Test đầu vào miễn phí | `Center["Test đầu vào"]` |
| Đã ưng khóa, hỏi lịch | Giữ chỗ buổi học thử ngày cụ thể | `khai_giang` của khóa |
| Phân vân, hỏi lộ trình | Gửi lộ trình qua Zalo | — |
| Hỏi học phí/ưu đãi | Tư vấn viên gửi bảng phí | `Center["Cam kết gọi lại"]` |

### Bảng CẤM sales (vào prompt)
- Số chỗ còn lại (mọi dạng) · cụm hối thúc · mốc gọi lại không có trong `Center["Cam kết gọi lại"]`
- Xin SĐT lần 2 sau khi bị từ chối · hỏi >1 câu/lượt · bán tiếp khi đã `da_hen_lich`

## Related Code Files
**Sửa**
- `chatbot/app/graph/state.py` — `sales_stage` 6 nấc + comment; `LeadProfile` +6 field; `phone_asked_at`
- `chatbot/app/graph/tools/lead_tools.py` — `capture_lead` cập nhật stage/field qua `Command(update=...)`; suy ra stage từ profile
- `chatbot/app/graph/prompts/system_prompt.py` — nhận `playbook` (chỗ trống Phase 02)
- `chatbot/app/graph/nodes/agent_node.py` — truyền `render_playbook(state)`
- `chatbot/app/graph/nodes/reflect_node.py` — gate xin-SĐT-lần-2

**Tạo**
- `chatbot/app/graph/prompts/sales_playbook.py`
- `chatbot/tests/test_sales_playbook.py`, `test_stage_transitions.py`

## Implementation Steps
1. `state.py`: đổi giá trị `sales_stage`; thêm `_LEGACY_STAGE_MAP` (`"mới"→moi`, `"đang tư vấn"→da_ro_nhu_cau`, `"đã xin SĐT"→co_sdt`, `"đã chốt"→da_hen_lich`, `"cần người"→handoff`) áp khi đọc state cũ. Thêm field `LeadProfile` + `phone_asked_at`.
2. `sales_playbook.py`: hằng `STAGE_ACTIONS`, `ELICITATION` (thứ tự 5 field + câu hỏi), `PHONE_REASONS`, `SALES_FORBIDDEN`; `render_playbook(state)` → chỉ dòng stage hiện tại + câu khơi gợi kế + cớ phù hợp.
3. `next_elicitation(profile)` → field trống đầu tiên theo thứ tự `lop → tinh_trang → muc_tieu → co_so → lich_ranh`; đủ hết → `None`.
4. `derive_stage(profile, current)` thuần: có `sdt` → ≥`co_sdt`; có `lop`+`tinh_trang` → ≥`da_ro_nhu_cau`; **chỉ tiến, không lùi** (trừ `handoff`).
5. `lead_tools`: **(a)** schema `@tool capture_lead` thêm `lop, tinh_trang, muc_tieu, co_so, lich_ranh, khung_gio_tien` (H3); **(b)** `run_capture_lead` merge 6 field mới vào profile + trả `ToolResult(msg, state_update={...})` (giữ contract hiện có, KHÔNG đổi sang `Command`); set `phone_asked_at`; upsert Sheet + Telegram khi `sdt` mới xuất hiện. Cột Sheet lead cũng phải thêm 6 field.
6. Gate xin-SĐT-lần-2 trong `reflect_node`: regex ý xin SĐT (`số điện thoại|sđt|zalo|số liên hệ`) + `phone_asked_at` <24h + chưa có `sdt` → thay câu đó bằng câu tư vấn trung tính (dùng đường `fixed_reply` sẵn có, không cần nhánh mới).
7. Prompt: chèn `[SALES PLAYBOOK]` vào chỗ trống Phase 02.
8. Test: chuyển stage theo profile; `next_elicitation` bỏ qua field đã có; gate chặn xin SĐT lần 2; `capture_lead` trả `Command`; migration stage cũ.

## Todo List
- [x] `sales_stage` 6 nấc + `_LEGACY_STAGE_MAP` cho checkpoint cũ
- [x] `LeadProfile` +6 field, `phone_asked_at`
- [x] `sales_playbook.py`: STAGE_ACTIONS / ELICITATION / PHONE_REASONS / SALES_FORBIDDEN
- [x] `render_playbook()` chỉ chèn stage hiện tại
- [x] `derive_stage()` chỉ tiến không lùi
- [x] **Schema `@tool capture_lead` +6 tham số** (H3) — 11 tham số, `test_sales_playbook.py::test_tool_schema_exposes_every_elicitation_field` khẳng định
- [x] `run_capture_lead` trả `ToolResult(msg, state_update)` (giữ contract, không đổi `Command`)
- [x] Cột Sheet `Leads` thêm 6 field (`lop, tinh_trang, muc_tieu, co_so, lich_ranh, khung_gio_tien`)
- [x] `phone_asked_at` stamped in `reflect_node` (when ask actually goes out, not in capture_lead)
- [x] Gate deterministic chặn xin SĐT lần 2 trong 24h
- [x] Cớ xin SĐT đọc từ `Center.verbatim`
- [x] Test stage/elicitation/gate/migration

## Success Criteria
- Hội thoại mới: bot hỏi đúng 1 câu khơi gợi/lượt, không hỏi lại field đã biết
- Bot xin SĐT **đúng 1 lần**; khách né → các lượt sau không còn câu xin SĐT nào (test tự động)
- Có SĐT → Sheet upsert đúng dòng + Telegram bắn ngay + stage `co_sdt`
- Khách hỏi "khi nào gọi?" → bot đọc **nguyên văn** `Center["Cam kết gọi lại"]`, không tự chế mốc
- Bot hỏi `khung_gio_tien` thay vì hứa giờ; field này vào Sheet lead
- Checkpoint cũ (stage tiếng Việt) load được, không crash
- `da_hen_lich` → bot ngừng chào bán

## Risk Assessment
| Risk | L×I | Mitigation |
|---|---|---|
| **Tool trả `str` → stage không đổi (silent no-op)** | Med×High | Ghi qua `ToolResult.state_update`; test assert state đổi thật (đã dính red-team #2 plan cũ) |
| **Sửa `LeadProfile` mà quên schema `@tool`** (H3) | High×High | Todo tách riêng 2 mục; test assert LLM schema có đủ 11 tham số |
| LLM vẫn xin SĐT lần 2 dù prompt cấm | High×Med | Gate deterministic ở `reflect_node`, không tin prompt |
| Stage lùi ngược gây hỏi lại từ đầu | Med×Med | `derive_stage` chỉ tiến (trừ handoff) |
| Checkpoint cũ vỡ vì đổi giá trị stage | Med×High | `_LEGACY_STAGE_MAP` + test load state cũ |
| Khơi gợi thành thẩm vấn | Med×High | Luật 1 câu/lượt + không cướp lượt; đo ở shadow mode |
| `Center.verbatim` thiếu dòng → cớ rỗng | Med×Med | Phase 01 warning; playbook fallback sang cớ "gửi lộ trình Zalo" |

## Security Considerations
- SĐT là PII (PDPD Decree 13/2023 — red-team #12 plan cũ): giữ nguyên câu thông báo mục đích trước khi lưu; `khung_gio_tien` cũng là dữ liệu cá nhân → chịu cùng retention purge + delete-by-PSID.
- Không log `sdt`/`khung_gio_tien` thô — log redaction filter phải phủ field mới.
- Cớ xin SĐT đọc từ Sheet → đã sanitize Phase 01; không nối chuỗi thô từ ô Sheet vào câu lệnh.

## Next Steps
- Unblocks Phase 05 (objection cần `sales_stage` + `objection_count`).
- Metrics stage-drop-off là đầu vào Phase 06.
