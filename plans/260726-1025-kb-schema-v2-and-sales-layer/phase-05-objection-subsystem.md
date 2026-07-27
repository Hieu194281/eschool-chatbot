# Phase 05 — Objection subsystem (detect + handle, bản đầy đủ)

## Context Links
- Plan: [plan.md](plan.md) · Prev: [phase-04](phase-04-sales-state-machine.md) · Cần: [phase-03](phase-03-guard-hardening.md) xanh
- Quyết định: report §B.6
- Code: `graph/graph_builder.py`, `graph/nodes/*`, `graph/prompts/sales_playbook.py`, `llm/` (lite_llm, with_retry)

## Overview
- **Priority:** P2 · **Status:** pending · **Effort:** ~2d
- Node `detect_objection` (Flash-Lite phân loại) + `handle_objection` (Flash sinh câu theo playbook). Kéo từ Out-of-scope Pha 2 lên. `so_sanh_cho_khac` route thẳng handoff, không sinh câu.

## Key Insights
- **Nhánh objection NGẮN HƠN nhánh thường** — bỏ retrieve + grade + lượt agent thứ 2. Chuỗi: `detect(FL) + handle(F) + reflect(FL)` ≈ 3–4s vs 7–9s. Lo ngại latency ban đầu là sai.
- Chi phí thật = **+~400ms mọi tin nhắn** do `detect` chạy luôn. Chấp nhận. Nếu p95 căng → gate `stage != moi` (tối ưu sau, YAGNI bây giờ).
- **Cộng hưởng phương án C:** catalog (15 khóa) đã in-context → `handle_objection` **không cần tool nào**. `lich_ban` đề xuất ca khác ngay; `gia_cao` dẫn `Center["Trả góp"]`. Nếu vẫn dùng RAG thì node này phải gọi tool → chậm gấp đôi. *(Khi chuyển `CATALOG_MODE=index` ở >30 khóa, node này cần bind thêm `get_course_detail` — ghi lại để không quên.)*
- **`so_sanh_cho_khac` không sinh câu** — route thẳng handoff. Bỏ được đúng lượt sinh nguy hiểm nhất (nói về đối thủ), lại tiết kiệm 1 call.
- **`handle_objection` vẫn phải qua guard.** Đây là node dễ nói bậy nhất (tự giảm giá) → luật nhượng bộ giá ở Phase 03 là điều kiện tiên quyết. Không bật node này trước khi guard xanh.
- **Chống lặp vòng bắt buộc:** cùng nhóm objection lần 2 → handoff ngay. Bot cãi vòng vo về học phí = mất lead lẫn thiện cảm; người thật xử được, bot thì không.
- Phân loại phải có nhãn `none` và **thiên về `none`** khi mơ hồ — false positive (coi câu hỏi thường là objection) làm bot phòng thủ vô cớ.
- **[REVIEW C3] `reflect_lite` bounce về `agent`, KHÔNG về `handle_objection`.** `route_after_reflect` (`reflect_node.py:64-65`) chỉ có 2 đích: `"agent"` | `"pricing_guard"`. Draft objection bị reflect chê → rơi vào `agent` (có bind tools, **không có playbook nhóm**) → trả lời lạc kịch bản, mà `objection_count` đã tăng rồi. **Phải sửa `route_after_reflect`**: khi `route_hint=="fix"` và `objection_type != none` → quay lại `handle_objection`; thêm cờ `objection_fix_done` để không lặp vô hạn (tương tự `reflect_count`).

## Requirements
**Functional**
- `detect_objection(state)` → `objection_type` ∈ `{none, gia_cao, suy_nghi, hoi_y_nguoi_khac, lich_ban, so_sanh_cho_khac}` (structured output, Flash-Lite)
- Route: `none` → `agent`; 4 nhóm → `handle_objection`; `so_sanh_cho_khac` → `handoff` (không sinh câu, dùng câu handoff chuẩn)
- `handle_objection(state)` sinh câu theo playbook nhóm + ràng buộc cấm, không gọi tool
- `objection_count[type]` tăng mỗi lần; **đạt 2 cùng nhóm → handoff ngay**, bỏ qua sinh câu
- Output đi tiếp qua `reflect_lite` → `pricing_guard` như mọi draft khác (không đường tắt)
- LLM lỗi/timeout ở `detect` → coi như `none` (fail-open cho phân loại, vì fail-closed sẽ chặn cả hội thoại bình thường)

**Non-functional**
- `detect_objection.py`, `handle_objection.py` mỗi file <200 LOC
- Playbook 5 nhóm nằm trong `sales_playbook.py` (đã tạo Phase 04), không rải rác
- `with_retry` cho cả 2 node như các node LLM khác

## Architecture
```
START → detect_objection
           ├─ none ─────────────► agent ⇄ tool_exec → grade → agent ─┐
           ├─ 4 nhóm ───────────► handle_objection ─────────────────┤
           └─ so_sanh_cho_khac ─► (set handoff) ─► fallback ────────┤
                                                                     ▼
                                                            reflect_lite
                                    fix + objection_type ◄───────────┤
                                    (quay lại handle_objection — C3)
                                                                     ▼
                                                            pricing_guard → END
```
Chèn `detect_objection` làm entry thay `agent`; mọi nhánh vẫn hội tụ về `reflect_lite → pricing_guard`.
**`route_after_reflect` thành 3 đích** (C3): `pricing_guard` | `agent` | `handle_objection`. Nhánh objection chỉ sửa 1 lần (`objection_fix_done`), hết lượt → honest-fallback như hiện tại.

### 5 nhóm playbook
| Nhóm | Làm | CẤM |
|---|---|---|
| `gia_cao` | Tách nhỏ (`Center["Trả góp"]`) → quy về giá trị (sĩ số, GV, học bù từ facts/chính sách) → đề xuất test miễn phí | **Không giảm giá**, không "để em xin sếp" |
| `suy_nghi` | Không ép; chốt giá trị nhỏ: gửi lộ trình qua Zalo | Không hỏi "chị suy nghĩ gì ạ" lần 2, không hối |
| `hoi_y_nguoi_khac` | "Để em gửi lộ trình + học phí qua Zalo cho anh chị cùng xem" → cớ xin SĐT tự nhiên | Không ép quyết ngay |
| `lich_ban` | Hỏi buổi rảnh → tra `[DANH MỤC KHÓA]` tìm ca/khóa khác | Không hứa mở lớp mới / đổi lịch |
| `so_sanh_cho_khac` | **Route handoff, không sinh câu** | Không nhắc tên/giá trung tâm khác |

## Related Code Files
**Sửa**
- `chatbot/app/graph/graph_builder.py` — thêm 2 node + đổi entry + conditional edges
- `chatbot/app/graph/state.py` — `objection_type`, `objection_count: dict`
- `chatbot/app/graph/prompts/sales_playbook.py` — `OBJECTION_PLAYBOOK` 5 nhóm
- `chatbot/app/graph/nodes/fallback_node.py` — dùng lại cho nhánh `so_sanh_cho_khac` (câu handoff chuẩn)

**Tạo**
- `chatbot/app/graph/nodes/detect_objection.py`
- `chatbot/app/graph/nodes/handle_objection.py`
- `chatbot/app/graph/prompts/objection_prompt.py` (nếu `sales_playbook.py` vượt LOC)
- `chatbot/tests/test_detect_objection.py`, `test_handle_objection.py`, `test_objection_routing.py`

## Implementation Steps
1. `state.py`: `objection_type: str`, `objection_count: dict[str, int]`.
2. `detect_objection.py`: Pydantic `ObjectionResult(type: str, confidence: float)`; prompt Flash-Lite, few-shot tiếng Việt (kèm biến thể teencode: "mắc quá", "đắt v", "để t tính đã", "hỏi ck cái đã"); **mơ hồ → `none`**; exception/timeout → `none`.
3. `route_after_detect(state)`: `none`→`agent`; `so_sanh_cho_khac`→`fallback` (kèm `handoff=True`); nhóm khác → kiểm `objection_count[type] >= 1` (tức đây là lần 2) → `fallback`+`handoff`; else → `handle_objection`.
4. `handle_objection.py`: build prompt = system prompt (catalog + center + playbook nhóm) + lịch sử + ràng buộc CẤM của nhóm; gọi Flash, **không bind tool**; trả `AIMessage` + tăng `objection_count[type]`.
5. `graph_builder.py`: `add_node` ×2; `START → detect_objection`; conditional edges theo bước 3; `handle_objection → reflect_lite`.
6. Đảm bảo `retrieved` rỗng ở nhánh objection **không** làm `pricing_guard` chặn oan: guard Phase 03 đọc catalog từ KB snapshot, không từ `state["retrieved"]` → đã an toàn. Test khẳng định điều này.
7. Test: mỗi nhóm route đúng; lần 2 cùng nhóm → handoff; `so_sanh_cho_khac` không gọi LLM sinh câu; detect lỗi → `none`; draft `gia_cao` có "giảm 20%" không khớp `uu_dai` → guard chặn.

## Todo List
- [x] `objection_type` + `objection_count` vào state
- [x] `detect_objection` Flash-Lite + few-shot teencode + mơ hồ→`none` + lỗi→`none`
- [x] `route_after_detect` 3 nhánh + kiểm lặp lần 2
- [x] `handle_objection` không bind tool, dùng catalog in-context
- [x] `so_sanh_cho_khac` → handoff, không sinh câu
- [x] `OBJECTION_PLAYBOOK` 5 nhóm trong sales_playbook
- [x] Graph wiring: entry = detect, mọi nhánh hội tụ reflect→guard
- [x] `route_after_reflect` 3 đích + `objection_fix_done` (C3) — objection rơi lại `handle_objection` không `agent`
- [x] `objection_count` tăng chỉ ở lần sinh đầu (detect), không tăng khi reflect bounce
- [x] Test routing/lặp/lỗi/guard-chặn-nhượng-bộ
- [x] Escalation actually calls handoff table + Telegram (fixed: not just advisory flag)

## Success Criteria
- "học phí mắc quá" → `gia_cao`, bot tách nhỏ theo `Center["Trả góp"]`, **không** nhắc giảm giá
- "để em suy nghĩ thêm" → `suy_nghi`, bot không ép, đề xuất gửi lộ trình
- "bên kia rẻ hơn" → `so_sanh_cho_khac` → handoff **không sinh câu**, Telegram bắn
- Cùng nhóm objection lần 2 → handoff, không thuyết phục tiếp
- Câu hỏi thường ("khai giảng khi nào") → `none`, đi nhánh agent bình thường
- Draft objection có nhượng bộ giá không khớp `uu_dai` → guard chặn (test end-to-end)
- Nhánh objection p95 < nhánh thường (đo log)

## Risk Assessment
| Risk | L×I | Mitigation |
|---|---|---|
| **`handle_objection` tự giảm giá** | Med×High | Luật nhượng bộ giá Phase 03 (fail-closed) + playbook CẤM rõ + shadow mode |
| False positive: câu hỏi thường bị coi là objection | Med×Med | Mơ hồ → `none`; few-shot có ví dụ âm; đo tỉ lệ phân loại ở shadow mode |
| Detect lỗi → chặn cả hội thoại | Low×High | Fail-open về `none` (khác guard — phân loại sai không gây nói dối) |
| Bot cãi vòng vo | Med×High | `objection_count` → handoff lần 2 |
| **Draft objection bị reflect chê → rơi về `agent` lạc playbook** (C3) | **High×High** | `route_after_reflect` 3 đích + `objection_fix_done`; test bounce quay đúng node |
| `objection_count` tăng 2 lần trong 1 lượt (sinh + bounce) → handoff oan | Med×Med | Chỉ tăng ở lần sinh đầu |
| +400ms mọi tin nhắn | High×Low | Chấp nhận; gate `stage != moi` để dành nếu p95 vượt |
| Nhánh objection bỏ qua KB → nói sai chính sách | Med×Med | Catalog + center đã in-context; chính sách nằm trong `chinh_sach`/Center |

## Security Considerations
- `handle_objection` sinh câu về **tiền** nhiều nhất → tuyệt đối không đường tắt qua guard. Mọi nhánh phải đi `reflect_lite → pricing_guard`.
- Playbook là dữ liệu tĩnh trong repo (không từ Sheet) → không phải vector prompt-injection. Giữ như vậy; **không** chuyển playbook sang Sheet cho nhân viên sửa.
- `so_sanh_cho_khac` → handoff tránh rủi ro pháp lý so sánh cạnh tranh.

## Next Steps
- Phase 06 đo: phân bố nhóm objection, tỉ lệ handoff do lặp, tỉ lệ guard chặn draft objection.
