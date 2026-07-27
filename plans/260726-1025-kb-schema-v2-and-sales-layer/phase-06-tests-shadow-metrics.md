# Phase 06 — Tests + shadow-mode metrics

## Context Links
- Plan: [plan.md](plan.md) · Phụ thuộc: tất cả phase 01–05
- Quyết định: report §5 (Success Metrics)
- Nền: `plans/260707-0048-tuyensinh-concierge-pha1/phase-06-shadow-mode-tests-deploy.md` (68 test hiện có, SHADOW_MODE, runbook)

## Overview
- **Priority:** P1 · **Status:** pending · **Effort:** ~2.5d
- Bổ sung test cho toàn bộ thay đổi + instrument metrics mới + chạy shadow mode đo trước khi thả tự động.

## Key Insights
- **68 test hiện có sẽ đỏ một phần** sau rename `pricing`→`facts` và đổi `sales_stage`. Sửa chúng là việc của phase tương ứng (01–05); phase này bổ sung test MỚI, không dọn nợ của phase trước.
- **[REVIEW H4] `test_tool_exec.py` và `test_vector_store.py` đã chuyển sang Phase 02** — 3 file bị sửa nặng nhất (`agent_node`, `tool_exec_node`, `vector_store`) hiện KHÔNG có test nào phủ, nên tiêu chí "test hiện có xanh" của Ph02 vô nghĩa nếu không viết mới ngay tại đó. Phase 06 không gánh hộ.
- **[REVIEW] 4 bug im lặng cần test hồi quy riêng** — chúng không ném lỗi, chỉ trả kết quả sai: C1 (FAQ bị nuốt), C2 (`retrieved` phình), C3 (objection rơi về `agent`), H1 (grade phán "đủ" nhờ chunk cũ). Loại bug này chỉ lộ qua test có chủ đích.
- **Metric quan trọng nhất không phải tỉ lệ đúng, mà là tỉ lệ CHẶN.** Guard siết hơn (Phase 03) có thể làm bot toàn honest-fallback → mất bán hàng mà không ai biết, vì không có incident nào nổ. Phải đo `% draft bị chặn theo loại`.
- **`% hội thoại bot xin SĐT >1 lần` phải ≈ 0** — chỉ số cảnh báo bot nài. Đây là thứ giết page nhanh nhất và không tự lộ ra qua log lỗi.
- Stage machine cho **drop-off analysis miễn phí** — biết rớt ở nấc nào là biết sửa gì.
- Shadow mode đã có (`SHADOW_MODE=true`) → tái dùng, không xây mới.
- **Không dùng fake data/mock để pass build.** LLM/Sheets/DB stub ở biên như plan cũ; logic thật phải test thật.

## Requirements
**Functional**
- Test mới phủ: parser 3 tab, prompt assembly, guard matching phân tầng, date/concession guard, stage transitions, gate xin-SĐT, objection routing + lặp
- Metrics logger ghi structured event mỗi turn: `stage`, `objection_type`, `guard_blocked` (+loại), `phone_asked`, `tool_used`, `latency_ms`
- Script tổng hợp metrics từ log → báo cáo (`% handoff`, `% chặn theo loại`, drop-off theo stage, `% xin SĐT >1 lần`)
- Shadow mode chạy trên hội thoại thật, đủ volume tối thiểu trước khi thả

**Non-functional**
- Không hạ ngưỡng test để pass; test đỏ → sửa code, không sửa test
- Metrics không log PII thô (SĐT, khung giờ) — chỉ boolean/enum

## Architecture
```
mỗi turn ─► metrics_logger.emit(event)  ──► structured log (JSON line)
                                              │
                              scripts/summarize-shadow-metrics.py
                                              │
                                              ▼
                                  báo cáo go/no-go (bảng §Success)
```

## Related Code Files
**Tạo**
- `chatbot/app/common/metrics_logger.py` — emit structured event, redact PII
- `chatbot/scripts/summarize-shadow-metrics.py` — tổng hợp log → bảng
- `chatbot/tests/test_prompt_assembly.py`, `test_guard_dates.py`, `test_guard_concession.py`, `test_phone_ask_gate.py`, `test_objection_routing.py`, `test_kb_snapshot_integrity.py`

**Sửa**
- `chatbot/app/graph/nodes/*` — gọi `metrics_logger.emit` ở điểm quyết định (guard, detect, capture_lead)
- `chatbot/docs/algorithms-and-details.md` — cập nhật thuật toán mới (guard phân tầng, stage machine, objection routing)

## Implementation Steps
1. `metrics_logger.py`: 1 hàm `emit(event: dict)` → JSON line; whitelist field (không log free text, không log SĐT); dùng logger riêng để tách khỏi log ứng dụng.
2. Cắm emit: `pricing_guard` (blocked + loại vi phạm), `detect_objection` (type), `capture_lead` (phone_asked, stage mới), `agent_node` (tool_used), dispatcher (latency).
3. Test bổ sung theo danh sách §Related. Ưu tiên **test đối kháng** cho guard: bảng tên khóa THẬT của trung tâm (không chỉ ví dụ trong doc) để bắt va chạm.
4. `test_kb_snapshot_integrity.py`: assert không doc nào có `source=course`; `facts_map` không rò vào `page_content`; snapshot swap atomic dưới đọc đồng thời (tái dùng smoke test cũ).
5. `summarize-shadow-metrics.py`: đọc log → bảng metrics §Success; in cảnh báo khi vượt ngưỡng.
6. Chạy WSL: `python -m compileall` + full `pytest` → **toàn bộ xanh**, không skip.
7. Bật `SHADOW_MODE=true` trên fanpage test / luồng người-duyệt; thu hội thoại thật; chạy script tổng hợp hàng ngày.
8. Cập nhật `chatbot/docs/algorithms-and-details.md` + `docs/system-architecture.md` + `docs/project-changelog.md`.

## Todo List
- [x] `metrics_logger.py` + PII whitelist
- [x] Cắm emit ở guard / detect / capture_lead / agent / dispatcher
- [x] Test parser 3 tab (mở rộng Phase 01)
- [x] Test prompt assembly (thứ tự khối, catalog sort, KB chưa ready)
- [x] Test guard: 4 tầng matching + va chạm tên khóa + ngày + nhượng bộ
- [x] Test gate xin SĐT lần 2
- [x] Test objection routing + lặp lần 2 + detect lỗi→none
- [x] Test snapshot integrity (không rò facts, không doc course)
- [x] Test hồi quy 4 bug im lặng (C1, C2, C3, H1)
- [x] Test không còn literal `sales_stage` tiếng Việt nào trong code (C4)
- [x] `summarize-shadow-metrics.py`
- [x] compileall + full pytest xanh (WSL), không skip
- [ ] Shadow mode chạy real traffic, collect minimum volume, báo cáo go/no-go — OPERATIONAL, NOT CODE
- [ ] Adversarial tests against center's REAL course-name table — REQUIRES BUSINESS DATA (not in repo)

## Success Criteria (cổng go-live)
| Metric | Ngưỡng |
|---|---|
| Câu cấp trung tâm trả lời không cần handoff | >90% |
| Incident báo giá/ngày sai khóa | **0** |
| `% hội thoại bot xin SĐT >1 lần` | ≈0 (bất kỳ ca nào = bug) |
| `% draft bị guard chặn` | <10%, và **không** tập trung ở 1 loại |
| `% hội thoại thu được SĐT` | có baseline + xu hướng tăng |
| Tỉ lệ handoff | giảm so với baseline Pha 1 |
| Latency p95/turn | <15s |
| Test suite | 100% xanh, không skip |

## Risk Assessment
| Risk | L×I | Mitigation |
|---|---|---|
| **Guard chặn nhiều → bot vô dụng mà không ai biết** | Med×High | Metric `% chặn theo loại` là cổng go-live, không phải chỉ số tham khảo |
| Sửa test cho pass thay vì sửa code | Med×High | Quy tắc: test đỏ → sửa code; ghi rõ ở Key Insights |
| Shadow mode không đủ volume → kết luận sai | Med×Med | Đặt volume tối thiểu trước khi đọc số (như red-team #16 plan cũ) |
| Metrics log rò PII | Low×High | Whitelist field + test assert không có `sdt` trong log |
| Test dùng tên khóa ví dụ, không bắt va chạm thật | Med×High | Bước 3: nạp bảng tên khóa thật của trung tâm |

## Security Considerations
- Metrics log là bề mặt rò PII mới → whitelist, không blacklist. Test khẳng định.
- Log redaction filter (red-team #12) phải phủ field mới của `LeadProfile`.
- Retention purge áp cho cả metrics log, không chỉ checkpoint.

## Next Steps
- Đạt cổng go-live → tắt `SHADOW_MODE`, thả tự động theo lộ trình plan cũ (App Review đã xong).
- Vòng lặp KB: log câu bot handoff → nhân viên thêm dòng `FAQ` hàng tuần.
- Theo dõi số khóa (nay 15); vượt **30** → chuyển `CATALOG_MODE=index` + xây tool `get_course_detail(cid)` (~0.5d, không refactor). Xem plan.md §Đường tăng trưởng.
