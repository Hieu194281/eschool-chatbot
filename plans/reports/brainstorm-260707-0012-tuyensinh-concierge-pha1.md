# Brainstorm Report — Tuyển Sinh Concierge (chi tiết hóa Pha 1)

**Date:** 2026-07-07 | **Type:** brainstorm | **Status:** consensus reached
**Input:** `2026-07-06-tuyensinh-concierge-brainstorm.md` (high-level design của HieuNT)
**Scope:** chốt quyết định kiến trúc còn mở + bổ sung concerns production cho Pha 1

## 1. Problem Statement

Chatbot tư vấn tuyển sinh + chốt lead cho trung tâm dạy học. Lead từ ads FB/Zalo → bot chăm sóc 24/7, trả lời khóa/học phí/lịch, thu lead structured → Google Sheet, đặt lịch học thử, handoff người thật khi cần. High-level đã chốt: Messenger+Zalo, single LangGraph StateGraph, 2 pha cùng codebase. Brainstorm này chốt phần còn mở: stack, KB, reflection Pha 1, ops/production gaps.

## 2. Context đã xác nhận (qua Q&A)

- **Trung tâm thật, lead đang chạy** → ưu tiên ship nhanh > áp dụng đủ concept học tập
- **KB nhỏ: <20 khóa** (~20-40K token toàn bộ)
- **Stack: Python + Gemini** (LangGraph Python)
- **Hạ tầng: chatbot tách riêng** khỏi hệ eSchool hiện có; DB riêng

## 3. Approaches đã evaluate

### 3.1 Tầng kiến thức
| Approach | Pros | Cons | Verdict |
|---|---|---|---|
| KB-in-context (cắt RAG) | Đơn giản nhất, số liệu chính xác, ship nhanh +1-2 tuần | Mất pattern RAG, phải refactor nếu KB phình | Đề xuất của brainstormer — **user không chọn** |
| **Corrective-RAG như doc gốc** | Đúng pattern đã học, sẵn sàng KB lớn | Thêm pipeline sync Sheet→embed, thêm class bug retrieval | **CHỐT (user quyết)** |
| Lai lookup + embed FAQ | Cân bằng | Phức tạp trung bình | Không chọn |

**Điều kiện an toàn kèm theo (đã đồng thuận):** học phí/ưu đãi KHÔNG đi qua chunk. Nằm ở cột structured trong Sheet, append nguyên văn vào context khi khóa liên quan được retrieve. RAG chỉ lo mô tả/FAQ/lộ trình/chính sách.

### 3.2 Các quyết định khác (đã chốt qua Q&A)
| Hạng mục | Quyết định | Alternatives bị loại |
|---|---|---|
| KB nguồn | **Google Sheet** (nhân viên tự sửa, bot sync ~5 phút) | Markdown repo (đổi ưu đãi phải qua dev), Admin UI (YAGNI Pha 1) |
| Notify handoff/lead nóng | **Telegram group bot** (push tức thì + tóm tắt + link Sheet) | Zalo group (không có bot API chính thức), Email (chậm) |
| Reflection Pha 1 | **Reflect-lite 1 vòng** (Flash-Lite): chỉ check số liệu khớp KB + không hứa bậy; fail → sửa 1 lần | Không reflect (rủi ro bịa giá), full loop (latency x2-3) |

## 4. Quyết định kỹ thuật (recommend, không tranh cãi)

- **Vector store:** in-memory, rebuild toàn bộ mỗi lần sync Sheet (KB bé, vài giây). Không Chroma/pgvector riêng.
- **Embeddings:** Gemini `gemini-embedding-001`.
- **Models:** Gemini 2.5 Flash (agent chính) + Flash-Lite (grade_chunks, reflect-lite).
- **Memory:** LangGraph **PostgresSaver checkpointer**, `thread_id = channel:user_id`. Xóa node `load_memory`/`save_history` tự viết.
- **DB:** Postgres (Docker/VPS) — checkpoints + bảng `lead_profile`.
- **Webhook:** FastAPI, **ACK 200 ngay**, xử lý async, dedupe theo `message_id` (Messenger resend sau ~20s nếu không ACK).
- **Debounce:** buffer in-process 5-8s/user, gom tin nhắn vụn trước khi chạy graph. Không Redis.
- **Fallback KB thiếu:** "để em nhờ tư vấn viên phản hồi" + bật cờ handoff. **CẮT `web_research` vĩnh viễn** — bot sale quote thông tin web (giá đối thủ, info cũ) = thảm họa, vi phạm nguyên tắc vàng.
- **Handoff resume:** tư vấn viên gõ `/resume <user>` trong Telegram; auto-resume sau 24h im lặng.
- **Lead Sheet:** **upsert** theo `channel_user_id`, không append trùng.
- **Thứ tự kênh:** Messenger trước (API dễ test), Zalo OA sau — **nộp hồ sơ xác thực OA ngay** (mất hàng tuần).
- **Ra mắt:** tuần đầu **shadow mode** (bot soạn, người duyệt gửi — hoặc chạy fanpage test) trước khi thả tự động.

## 5. Production gaps đã phát hiện (không có trong doc gốc)

1. **Message debouncing** — user VN nhắn 3-5 tin vụn liên tiếp; không gom = bot trả lời chồng chéo. Quan trọng hơn reflection.
2. **Webhook idempotency + ACK nhanh** — không làm = bot trả lời đúp.
3. **Zalo OA policy:** tin CSKH chỉ trong 48h từ tin cuối của user; tin chủ động phải mua gói + OA xác thực DN. Messenger: cửa sổ 24h. → **Nurture "bot nhắn lại hôm sau" không khả thi miễn phí** → chiến lược đúng: xin SĐT sớm, tư vấn viên gọi là đường nurture thật.
4. **KB ops:** ưu đãi đổi hàng tháng; nguồn Google Sheet cho nhân viên tự sửa là điều kiện sống còn (chốt ở 3.2).
5. **Handoff mechanics:** tư vấn viên trả lời trực tiếp fanpage inbox/Zalo OA chat; bot chỉ im khi cờ bật; resume theo lệnh/timeout.
6. **Lead dedupe** trong Sheet (upsert).

## 6. Kiến trúc Pha 1 sau brainstorm

```
Messenger/Zalo webhook → ACK ngay → dedupe message_id → debounce 5-8s/user
    → LangGraph StateGraph (checkpointer = PostgresSaver):
        agent (Gemini 2.5 Flash) ⇄ tools:
            retrieve_kb   → grade_chunks (Flash-Lite) → thiếu: honest-fallback + handoff
            capture_lead  → upsert Google Sheet + notify Telegram nếu nóng
            book_trial    → ghi Sheet/Calendar
            handoff_to_human → cờ + notify Telegram (tóm tắt + link)
        → reflect-lite 1 vòng (Flash-Lite: số liệu khớp KB? hứa bậy?) → send_reply

KB pipeline: Google Sheet (nhân viên sửa)
    → sync ~5 phút → chunk mô tả/FAQ → re-embed in-memory vector store
    → học phí/ưu đãi = cột structured, inject nguyên văn, KHÔNG chunk
```

Pha 2 như doc gốc: full reflection loop, `handle_objection`, `score_lead` — thêm node, không đổi xương. (`web_research` đã cắt khỏi Pha 2.)

## 7. Risks

| Risk | Mitigation |
|---|---|
| Bịa học phí/cam kết | Structured pricing ngoài chunk + reflect-lite + system prompt ràng buộc + shadow mode tuần đầu |
| Sheet sync lệch vector store | Rebuild toàn bộ mỗi sync (KB bé); log version sync |
| Zalo OA xác thực chậm | Nộp hồ sơ ngay, ship Messenger trước |
| Bot trả lời đúp/chồng | ACK ngay + dedupe + debounce |
| Nhân viên sửa Sheet sai format | Template + validation khi sync, báo lỗi Telegram |
| Latency cao (agent+grade+reflect) | Flash-Lite cho phụ trợ; typing indicator; giới hạn 1 vòng reflect |

## 8. Success Metrics (Pha 1)

- % câu hỏi học phí/lịch trả lời đúng KB (shadow mode đo, target >95% trước khi thả)
- Số lead structured vào Sheet/tuần; % lead có SĐT
- Thời gian phản hồi < 15s/tin
- % hội thoại cần handoff (theo dõi để tinh chỉnh KB)
- Zero incident bịa giá/cam kết sai

## 9. Next Steps

1. Tạo implementation plan Pha 1 (`/ck:plan`) — ĐANG LÀM
2. Song song ngoài code: nộp xác thực Zalo OA; gom dữ liệu <20 khóa vào Google Sheet theo template (Đối tượng/Mục tiêu/Lộ trình/Lịch/Học phí-ưu đãi structured/GV/FAQ/Chính sách)
3. Lập Telegram group tư vấn viên + tạo bot token
4. Chuẩn bị fanpage test cho shadow mode

## Unresolved Questions

- VPS/hosting cụ thể chưa chốt (cần public HTTPS cho webhook) — quyết ở planning
- Ai là người vận hành Sheet KB + quy trình duyệt shadow mode — cần phân công phía trung tâm
- Zalo OA đã xác thực doanh nghiệp chưa? (ảnh hưởng timeline kênh Zalo)
