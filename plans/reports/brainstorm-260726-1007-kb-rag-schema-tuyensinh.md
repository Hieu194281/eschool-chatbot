# Brainstorm Report — Tầng kiến thức (KB/RAG) + Tầng sales cho Tuyển Sinh Concierge

**Date:** 2026-07-26 | **Type:** brainstorm | **Status:** consensus reached
**Bối cảnh:** Pha 1 đã implement xong (phases 01–06). Review lại KB schema + bổ sung tầng sales.
**Tiền đề:** `brainstorm-260707-0012-tuyensinh-concierge-pha1.md`, `phase-02-kb-layer-sheet-sync-vectorstore.md`

Report gồm 2 phần dính nhau: **A. Tầng kiến thức** (dữ liệu bot biết) · **B. Tầng sales** (bot dùng dữ liệu đó để chốt lead). Quyết định ở A làm B rẻ đi đáng kể (§B.6).

---

## 1. Problem Statement

**A. KB hiện tại** = 1 worksheet `Courses`, 8 cột embed + 2 cột pricing verbatim:

1. **Thiếu hẳn thông tin cấp trung tâm** — địa chỉ, hotline, giờ mở cửa, chỗ để xe, quy trình đăng ký, thanh toán/trả góp, hoàn phí/bảo lưu, thành tích. Khách hỏi → retrieve ra blob khóa học vô nghĩa → `grade_chunks` fail → handoff. **Câu dễ nhất lại phải gọi người thật.**
2. **Nguyên tắc vàng nửa vời** — chỉ bảo vệ tiền. `lich_khai_giang` (con số) ở nhóm embed → bot diễn giải "05/08" thành "đầu tháng 8", `pricing_guard` không bắt vì không phải token tiền. Tương tự tên GV, địa chỉ.
3. **Không trả lời được "nên học khóa nào"** — không có dữ liệu so sánh; top-k chỉ thấy 2–3 khóa, không thấy toàn cảnh.
4. **FAQ chôn trong blob khóa học** — hit rate thấp; FAQ chung (không thuộc khóa nào) không có chỗ tồn tại.

**B. Chưa có tầng sales** — bot trả lời được nhưng không có cơ chế dẫn khách tới SĐT / lịch học thử. Thiếu: khơi gợi nhu cầu, thời điểm + cớ xin SĐT, xử lý từ chối, state theo dõi nấc chuyển đổi.

## 2. Quyết định chốt qua Q&A

| Hạng mục | Quyết định |
|---|---|
| Câu khách hỏi nhiều | Cả 4 nhóm: cơ sở & liên hệ · nên học khóa nào · thủ tục & thanh toán · chất lượng & cam kết |
| Cấu trúc KB | **3 worksheet** (Courses + Center + FAQ) |
| Verbatim | **Mở rộng cho mọi con số/tên riêng**, không chỉ học phí |
| Tầng kiến thức | **Phương án C — lai**: khóa học in-context, FAQ/Center qua RAG |
| Cớ xin SĐT | Cả 4: học thử miễn phí · test đầu vào · gửi lộ trình Zalo · giữ chỗ lớp |
| Khan hiếm | **CẤM HOÀN TOÀN** (xem §B.4 — cách gỡ mâu thuẫn với cớ "giữ chỗ") |
| Sau khi có SĐT | Tư vấn viên gọi trong giờ làm việc; **bot KHÔNG hứa mốc giờ** (§B.5) |
| Objection | **Node `handle_objection` bản đầy đủ** (sinh câu riêng), kéo từ Pha 2 lên Pha 1 |

---

# PHẦN A — Tầng kiến thức

## A.1 Approaches evaluated

Bối cảnh: KB 20 khóa. Gemini 2.5 Flash 1M context → 12K token không nghẽn; chênh lệch chỉ là tiền + latency.

| | A — RAG cho tất cả (hiện tại) | B — Cắt RAG, nhét hết prompt | **C — Lai (CHỐT)** |
|---|---|---|---|
| Token/lượt | ~2K | ~12K | ~9K |
| Trượt retrieval trên khóa học | **Có** | Không | Không |
| So sánh nhiều khóa | Kém (chỉ top-k) | Tốt | Tốt |
| Code phải sửa | Ít nhất | Nhiều (xóa mảng lớn) | Vừa |
| `grade_chunks` | Cần | Bỏ | Chỉ FAQ/Center |
| Chịu KB phình | Tốt nhất | Kém | Tốt đến ~50 khóa |

**Nhận định thẳng:** ở 20 khóa, RAG **không bắt buộc**. Nó được chọn ở brainstorm gốc §3.1 vì muốn áp pattern đã học + chuẩn bị KB lớn. Đáng chú ý: phần lớn độ phức tạp của graph (`grade_chunks` + fallback + handoff-khi-thiếu) tồn tại **chỉ để xử lý hậu quả của việc dùng RAG**.

**Chốt C** vì: khóa học là tập bounded (20), nhỏ, sinh tiền trực tiếp → không đáng đánh cược vào retrieval mờ. FAQ/Center là tập tăng không giới hạn (40 dòng hôm nay → vài trăm sau 6 tháng) → đây mới là chỗ RAG đáng tiền.

**Đường tăng trưởng (cập nhật 2026-07-26 — quy mô thật: 15 khóa, sẽ phình):**

Ngưỡng "vượt 50 khóa → quay về A" ban đầu là **thiết kế tồi**: nó tự hẹn một đợt refactor và đợt đó trả lại đúng rủi ro vừa loại (retrieve trượt trên phần sinh tiền). Thay bằng **catalog 2 tầng**, cả hai keyed theo `course_id`:

| Tầng | Nội dung | Token/khóa |
|---|---|---|
| **Index** — always-on vĩnh viễn | `id · tên · đối tượng 1 dòng · hình thức` | ~25 |
| **Detail** | prose + facts | ~440 |

| Quy mô | Mode | Catalog trong prompt |
|---|---|---|
| **≤30** *(nay: 15)* | `full` — Index + Detail | ~7K |
| 30–80 | `index` — Index + tool `get_course_detail(cid)` | ~2K |
| >80 | Lúc đó mới bàn RAG cho **mô tả**; facts vĩnh viễn lookup theo id | — |

Khi phình, Detail rời prompt sang **tra cứu dict theo khóa chính**, không phải similarity search → tính chất "không bao giờ trượt retrieval trên khóa học" giữ được ở mọi quy mô. Chuyển mode = 1 tool + 1 flag, không refactor.

**Index xây ngay** (có giá trị hôm nay: mục lục điều hướng 15 block dài). Tool `get_course_detail` chưa xây — YAGNI.

**`pricing_guard` không chịu ảnh hưởng của ngưỡng nào** — đọc facts qua `get_all_courses()` (dict, 0 token). 15 hay 500 khóa, guard vẫn so đủ catalog.

## A.2 Mô hình 4 tầng + quy tắc quyết định

Áp đúng 4 câu hỏi này cho mỗi mẩu thông tin:

1. Bot cần **mọi lượt**? → **Always-on** (system prompt), không RAG
2. **Con số / tên riêng / cam kết**, sai lệch = nói dối? → **Verbatim facts** (cột structured, copy nguyên byte)
3. Văn xuôi, khách hỏi nhiều kiểu, **tập tăng không giới hạn**? → **RAG embed**
4. Đổi theo phút? → **tool tra cứu live** (Pha 2, chưa làm)

| Tầng | Nội dung (sau C) | Vào prompt khi nào |
|---|---|---|
| Always-on | Center identity + **toàn bộ 20 khóa: mô tả + facts** + sales playbook | Mọi lượt |
| Verbatim facts | Lồng trong khối khóa học, nhãn `SỐ LIỆU CHÍNH THỨC` | Mọi lượt (theo khóa) |
| RAG embed | FAQ (1 doc/dòng) + Center `loai=embed` | Khi retrieve trúng |
| Live tool | — | Pha 2 |

## A.3 Schema 3 worksheet

**Tab `Courses`** — ranh giới cột L\|M là đường phân chia duy nhất cần nhớ:

| Nhóm | Cột |
|---|---|
| Metadata | `course_id`, `ten_khoa`, `tu_khoa` (alias/không dấu/viết tắt) |
| **VERBATIM** | `hoc_phi`, `uu_dai`, `khai_giang`, `lich_hoc`, `thoi_luong`, `si_so`, `hinh_thuc`, `giao_vien_ten`, `co_so` |
| **Mô tả** (prose) | `doi_tuong`, `muc_tieu`, `lo_trinh`, `giao_vien_gioi_thieu`, `chinh_sach`, `ghi_chu` |

- `giao_vien` tách 2 cột cố ý: **tên** = verbatim (bịa tên GV rất tệ), **giới thiệu** = prose.
- `tu_khoa` giữ lại dù khóa học không còn embed — dùng cho **course-mention detection** ở guard (§A.5).
- **KHÔNG có cột số chỗ còn lại** — đã cấm khan hiếm (§B.4).

**Tab `Center`** — `chu_de · noi_dung · loai · tu_khoa`, `loai` ∈ {`always`, `verbatim`, `embed`}:
- `always` → địa chỉ, hotline, giờ mở cửa
- `verbatim` → số tài khoản, **trả góp**, **phí test đầu vào**, **cam kết gọi lại** (§B.5), cam kết/thành tích đã duyệt
- `embed` → quy trình đăng ký, thủ tục nhập học, thanh toán, hoàn phí/bảo lưu/học bù, cơ sở vật chất

Ba dòng `verbatim` in đậm là nguồn dữ liệu bắt buộc cho playbook sales (§B.4, §B.5).

**Tab `FAQ`** — `cau_hoi · tra_loi · course_id (rỗng = chung) · tu_khoa`. **Mỗi dòng = 1 Document riêng.** Câu khách khớp trực tiếp cột `cau_hoi` → hit rate cao nhất hệ. Tự lớn lên: mỗi tuần lấy log câu bot handoff → nhân viên thêm dòng.

## A.4 Cấu trúc prompt sau C

```
[SYSTEM]
  Nguyên tắc vàng + bảng CẤM (số liệu + sales, §B.4)
  [THÔNG TIN TRUNG TÂM]        ← Center.loai=always            (~200 tok)
  [DANH MỤC KHÓA — 20 khối]                                    (~8.800 tok)
      mỗi khối:
        --- id=T7-MG "Toán 7 Mất Gốc" ---
        Đối tượng/Mục tiêu/Lộ trình/GV/Chính sách   (prose)
        [SỐ LIỆU CHÍNH THỨC — id=T7-MG]
        Học phí/Ưu đãi/Khai giảng/Lịch/Sĩ số/GV/Cơ sở  (verbatim)
  [SALES PLAYBOOK]             ← §B                            (~1.500 tok)
[CONTEXT LƯỢT NÀY]
  [DỮ LIỆU KHÔNG TIN CẬY] FAQ/Center chunks retrieve được      (~500 tok)
[LỊCH SỬ CHAT]  PostgresSaver, thread_id=channel:user_id
```

Facts **lồng trong khối của chính khóa đó**, không phải danh sách giá phẳng — giảm rủi ro LLM nhặt nhầm giá khóa khác.

## A.5 [CRITICAL] `pricing_guard` — repoint input + siết matching

**Trạng thái thực tế (đã verify code `graph/nodes/pricing_guard.py`):** course-mention binding **ĐÃ CÓ** — `_resolve_named()` khớp `ten_khoa` với draft rồi mới lấy allowed-set. Không cần xây lại từ đầu.

**Ba việc thật sự phải làm dưới phương án C:**

1. **Đổi nguồn input** — `evaluate_draft(draft, state["retrieved"])`: sau C khóa học không còn đi qua `retrieved` (chỉ còn FAQ/Center chunks). Guard phải đọc **catalog 20 khóa + facts** từ KB snapshot.
2. **Siết matching** — `_name_in_draft` dùng ngưỡng trùng-từ 0.6. Trong không gian 20 tên khóa, `"Toán 7 Mất Gốc"` vs `"Toán 9 Mất Gốc"` trùng 3/4 = 0.75 → **khớp nhầm khóa**. Phải: ưu tiên `course_id` / alias `tu_khoa` / tên khớp chính xác; ngưỡng fuzzy cao hơn + loại token dùng chung (`toán`, `lớp`, số lớp); **≥2 khóa khớp mập mờ → fail-closed**.
3. **Xử lý tường minh nhánh không-nêu-tên-khóa** — fallback `if not named and len(retrieved)==1` thành vô hiệu với 20 khóa → allowed-set rỗng → mọi token tiền bị chặn. An toàn nhưng over-block. Cần quyết: draft có token tiền mà không nêu khóa → chặn + ép agent nêu tên khóa (giữ fail-closed, nhưng bằng đường có chủ đích).

Bỏ qua mục 1–2 → C là **bước lùi** về an toàn số liệu (guard so nhầm khóa hoặc so với tập rỗng).

## A.6 `date_guard` (mới, cùng file guard)

Regex ngày/giờ trong draft phải khớp `khai_giang`/`lich_hoc` của khóa được nhắc. Cùng cơ chế binding như A.5.

**KHÔNG viết guard cho** tên GV / địa chỉ / sĩ số — verbatim ở tầng data + `reflect_lite` là đủ. Guard deterministic trên free text = false positive nổ, bot im lặng vô lý. Đây là chỗ dễ over-engineer nhất.

## A.7 Không đưa vào KB

- **Kịch bản bán hàng / xử lý từ chối / giọng điệu** → system prompt (retrieve trượt = mất guardrail). Xem §B
- **Danh sách CẤM** → system prompt, hard rule
- **Cam kết chất lượng** → chỉ được nói câu có **nguyên văn** trong `Center.loai=verbatim`. Không suy diễn. Rủi ro pháp lý, không phải UX
- **Data học viên cũ có danh tính** → PII

---

# PHẦN B — Tầng sales

## B.1 Mục tiêu chốt của bot KHÔNG phải "đăng ký khóa"

```
inbox → hiểu nhu cầu → SĐT/Zalo → buổi test/học thử → đóng phí
                        ↑                    ↑
                   bot dừng ở đây      tư vấn viên gọi
```

Phụ huynh gần như không chuyển 5.4tr qua Messenger cho người lạ. Bot đẩy khách lên nấc **"có SĐT + có lịch học thử"** rồi giao người thật. Thiết kế bot đi xa hơn nấc đó = tự hạ tỉ lệ chuyển đổi.

## B.2 Stage machine — xương sống tầng sales

```
moi ──► da_ro_nhu_cau ──► da_bao_gia ──► co_sdt ──► da_hen_lich ──► handoff
```

| Stage | Bot biết gì | Hành động DUY NHẤT tiếp theo |
|---|---|---|
| `moi` | chưa gì | Hỏi khơi gợi #1 |
| `da_ro_nhu_cau` | lớp + tình trạng | Đề xuất khóa cụ thể + lộ trình, **chưa báo giá vội** |
| `da_bao_gia` | đã nói học phí | **Xin SĐT kèm cớ** (§B.4) |
| `co_sdt` | có SĐT | Hỏi khung giờ tiện (§B.5) + đề xuất chốt lịch học thử |
| `da_hen_lich` | có ngày giờ | Xác nhận, nhắc mang gì, **dừng bán** |
| `handoff` | — | Im, chờ tư vấn viên |

Bot không "cảm hứng bán hàng" — nó biết mình ở đâu và bước kế là gì. Quan trọng hơn số lượng mẫu câu.

## B.3 Khơi gợi — 5 câu, mỗi câu nuôi 1 field lead

| # | Câu hỏi | Điền vào |
|---|---|---|
| 1 | *"Bé nhà mình đang học lớp mấy ạ?"* | `lop` |
| 2 | *"Bé đang yếu phần nào nhất — hay điểm môn này tầm bao nhiêu ạ?"* | `tinh_trang` |
| 3 | *"Chị mong bé đạt được gì — theo kịp lớp hay ôn thi ạ?"* | `muc_tieu` |
| 4 | *"Nhà mình gần cơ sở nào hơn ạ?"* | `co_so` |
| 5 | *"Bé thường rảnh buổi nào trong tuần ạ?"* | `lich_ranh` |

**Luật cứng:**
- **1 câu hỏi / 1 lượt trả lời.** Hỏi dồn = khách trả lời 1 câu hoặc bỏ chạy
- Chỉ hỏi field **chưa có** (lý do cần `lead_profile` persist)
- Khách đang có câu chưa được trả lời → **trả lời trước, hỏi sau**. Không cướp lượt

## B.4 Xin SĐT — 4 cớ, chọn theo tín hiệu

| Tín hiệu khách phát | Cớ dùng |
|---|---|
| Lo con yếu, chưa rõ trình độ | **Test đầu vào miễn phí** (dẫn `Center.verbatim`) |
| Đã ưng khóa, hỏi lịch/khai giảng | **Giữ chỗ buổi học thử** ngày cụ thể từ `khai_giang` |
| Còn phân vân, hỏi nhiều về lộ trình | **Gửi lộ trình qua Zalo** — cớ nhẹ nhất, gần như không bị từ chối |
| Hỏi học phí / ưu đãi | **Tư vấn viên gửi bảng phí + xác nhận ưu đãi** — không kèm hối thúc |

Cớ tốt = thứ khách **nhận được**, không phải thứ mình muốn lấy.

**Luật xin SĐT:**
1. Chỉ xin **sau khi đã trả lời trọn vẹn** câu của khách — trao giá trị trước
2. **Tối đa 1 lần / hội thoại.** Bị né → không xin lại trong 24h, trừ khi có tín hiệu mới mạnh hơn
3. Luôn kèm cớ cụ thể + ngày giờ thật từ Sheet
4. Không xin ở lượt đầu, trừ khi khách tự nói *"cho em đăng ký"*
5. Bị từ chối → **chuyển hẳn sang chế độ tư vấn**, không quay lại chủ đề SĐT

Điểm 2 và 5 phân biệt bot dùng được với bot bị phụ huynh block page.

### Gỡ mâu thuẫn: "cấm khan hiếm" vs cớ "giữ chỗ / giữ ưu đãi"

| | Được | Cấm |
|---|---|---|
| **Nêu sự thật** | *"Ưu đãi giảm 15% đến hết 31/08"* — nguyên văn ô `uu_dai` | — |
| **Đặt chỗ** | *"Em giữ chỗ buổi học thử cho bé ngày 05/08"* — thao tác vận hành | — |
| **Tạo áp lực** | — | *"Chỉ còn 4 chỗ"* · *"Nhanh kẻo hết"* · *"Chị quyết sớm giúp em"* |
| **Bịa số** | — | Mọi phát biểu về số chỗ trống — không có cột nào chứa data này |

**Được nói ngày hết hạn có thật, cấm dùng nó làm đòn bẩy.** Cần chốt chặn deterministic: regex cụm hối thúc (`còn ... chỗ`, `nhanh kẻo`, `chỉ còn`, `sắp hết`, `gấp`, `quyết sớm`) trong `reflect_lite`. Không có nó thì "cấm hoàn toàn" chỉ là lời khuyên trong prompt.

## B.5 Sau khi có SĐT — bot HỎI giờ, không HỨA giờ

*"Sẽ liên hệ sớm nhất"* an toàn nhưng yếu — vẫn là lời hứa mơ hồ, mà mơ hồ thì phụ huynh không tin.

> ❌ *"Tư vấn viên sẽ gọi cho chị trong hôm nay ạ."*
> ❌ *"Tư vấn viên sẽ liên hệ chị sớm nhất ạ."*
> ✅ *"Dạ em ghi nhận rồi ạ. **Chị tiện nghe máy khoảng mấy giờ để em ghi chú cho tư vấn viên gọi đúng lúc ạ?**"*

Được 3 thứ: không hứa gì phải giữ · thu `khung_gio_tien` (tăng tỉ lệ bắt máy) · giữ hội thoại tiếp diễn.

Khách hỏi thẳng *"khi nào gọi?"* → bot đọc **nguyên văn** dòng `Center`:
```
chu_de: Cam kết gọi lại
noi_dung: Tư vấn viên liên hệ trong giờ làm việc 8h–20h30
loai: verbatim
```
Để ở Sheet chứ không hardcode: vận hành siết lại được thì nhân viên sửa 1 ô.

**Cấm:** mọi mốc thời gian gọi lại không có nguyên văn trong ô đó — `"trong hôm nay"`, `"trong 5 phút"`, `"ngay bây giờ"`, `"chút nữa"`.

**Luồng khác:** `capture_lead` upsert Sheet + **notify Telegram ngay** (lead nóng). Bot **tiếp tục chat bình thường**, chỉ im khi cờ handoff bật. Stage → `co_sdt`.

## B.6 `handle_objection` — bản đầy đủ

```
                    ┌─ none ──► agent ⇄ tools → grade → agent ─┐
user msg ► detect ──┤                                          ├─► reflect → guard → END
                    ├─ 4 nhóm ──► handle_objection ────────────┘
                    └─ so_sanh_cho_khac ──► handoff (không sinh câu)
```

| Nhánh | Chuỗi call | Ước lượng |
|---|---|---|
| Thường | detect(FL) + agent(F) + grade(FL) + agent(F) + reflect(FL) | ~7–9s |
| Objection | detect(FL) + handle_objection(F) + reflect(FL) | **~3–4s** |

Nhánh objection **ngắn hơn** nhánh thường (bỏ retrieve + grade + lượt agent thứ hai). Chi phí thật = **+~400ms trên mọi tin nhắn** do `detect` chạy luôn. Nếu p95 căng → gate: chỉ chạy `detect` khi `stage != moi`.

**Cộng hưởng với phương án C:** vì cả 20 khóa đã nằm sẵn trong system prompt, `handle_objection` **không cần gọi tool nào**. `lich_ban` đề xuất ca/khóa khác ngay; `gia_cao` dẫn chính sách trả góp — tất cả đã trong context.

### 5 nhóm objection

| Nhóm | Làm | **Cấm** |
|---|---|---|
| `gia_cao` | Tách nhỏ (*đóng theo tháng, không phụ thu* — `Center.verbatim`) → quy về giá trị (sĩ số 12, GV chuyên mất gốc, học bù) → đề xuất test miễn phí | **Tuyệt đối không giảm giá**, không "để em xin sếp" |
| `suy_nghi` | Không ép. Chốt bằng giá trị nhỏ: *"em gửi lộ trình qua Zalo chị xem dần nhé"* | Không hỏi *"chị suy nghĩ gì ạ"* 2 lần, không hối |
| `hoi_y_nguoi_khac` | *"Để em gửi lộ trình + học phí qua Zalo cho anh chị cùng xem"* → cớ xin SĐT tự nhiên nhất | Không ép quyết ngay |
| `lich_ban` | Hỏi buổi rảnh → tra `[DANH MỤC KHÓA]` tìm ca/khóa khác | Không hứa mở lớp mới / đổi lịch |
| `so_sanh_cho_khac` | **Route thẳng handoff, không sinh câu** | Không nhắc tên/giá trung tâm khác, không chê |

`so_sanh_cho_khac` bỏ được đúng lượt sinh nguy hiểm nhất, không tốn call.

### Guard bổ sung cho nhánh objection

```
Mọi cụm nhượng bộ giá — "giảm", "bớt", "ưu đãi riêng", "xin sếp",
"trường hợp của chị" — chỉ hợp lệ nếu khớp NGUYÊN VĂN ô uu_dai
của khóa được nhắc. Không khớp → chặn.
```
Không có luật này thì playbook `gia_cao` sớm muộn đẻ ra *"để em xin ưu đãi riêng cho chị"* — đúng thứ nguyên tắc vàng cấm.

### Chống lặp vòng

`state.objection_count[type]`. Cùng nhóm objection lặp **lần 2** → **handoff ngay**, không thuyết phục tiếp. Bot cãi vòng vo với phụ huynh về học phí = mất lead lẫn thiện cảm.

---

## 3. Code impact (gộp A + B)

**Sửa**
- `kb/sheet_loader.py` — đọc 3 worksheet trong 1 `batch_get` (vẫn 1 API call, không đụng quota 300/min)
- `kb/course_parser.py` — `pricing_map` → `facts_map` (9 trường); sanitize **từng ô**; build `course_blocks` thay vì Document
- `kb/vector_store.py` — snapshot `(store, facts_map, course_blocks, center_always, version)`; store **chỉ còn FAQ + Center embed docs**; giữ atomic rebind
- `graph/prompts/system_prompt.py` — chèn `center_always` + 20 `course_blocks` + sales playbook + bảng cấm
- `graph/nodes/pricing_guard.py` — course-mention binding (A.5) + `date_guard` (A.6) + luật nhượng bộ giá (B.6)
- `graph/nodes/reflect_node.py` — regex chặn cụm hối thúc (B.4) + mốc giờ gọi lại (B.5)
- `graph/tools/retrieve_kb_tool.py` — scope thu về FAQ/Center
- `graph/nodes/grade_node.py` — chỉ chấm FAQ/Center chunks
- `graph/nodes/agent_node.py`, `tool_exec_node.py` — bỏ inject pricing theo hit (đã always-on)
- `graph/state.py` — **mở rộng `sales_stage` đã có** (đổi 5 giá trị tiếng Việt sang 6 stage §B.2, không thêm field song song); thêm `objection_type`, `objection_count`, `phone_asked_at`; **mở rộng `LeadProfile` đã có** thêm `lop`, `tinh_trang`, `muc_tieu`, `co_so`, `lich_ranh`, `khung_gio_tien`
- `graph/tools/lead_tools.py` — stage transition + điền field khơi gợi + `khung_gio_tien`
- `graph/graph_builder.py` — cắm `detect_objection` + `handle_objection` vào luồng

**Tạo**
- `kb/center_faq_parser.py` — parser tab Center + FAQ (<200 LOC)
- `graph/nodes/detect_objection.py` — Flash-Lite classify 5 nhóm + `none`
- `graph/nodes/handle_objection.py` — sinh câu theo playbook nhóm
- `graph/prompts/sales_playbook.py` — khơi gợi + 4 cớ + 5 playbook + bảng cấm

**Không đổi:** channel adapters, debounce/dedupe, handoff manager, Telegram notifier, PostgresSaver.

**Sheet:** không cần cột số chỗ (đã cấm khan hiếm). `Center` bắt buộc có 3 dòng `verbatim`: `Trả góp`, `Test đầu vào`, `Cam kết gọi lại`.

## 4. Risks

| Risk | L×I | Mitigation |
|---|---|---|
| **Guard suy yếu do 20 giá cùng lúc** | High×High | Course-mention binding (A.5) — **bắt buộc, không phải tùy chọn** |
| **`handle_objection` tự giảm giá** | Med×High | Luật nhượng bộ giá ở guard (B.6) + playbook cấm rõ + shadow mode |
| Bot nài SĐT → khách block page | Med×High | Luật 1-lần/hội thoại + không xin lại 24h (B.4) + metric cảnh báo |
| LLM nhặt nhầm giá giữa 20 khóa | Med×High | Facts lồng trong khối khóa + nhãn `id=` + guard A.5 |
| Bot hứa mốc gọi lại không giữ được | Med×High | Bot hỏi giờ thay vì hứa (B.5) + regex chặn mốc thời gian |
| Bot cãi vòng vo về học phí | Med×Med | `objection_count` → handoff ở lần lặp thứ 2 (B.6) |
| 3 tab → nhân viên sửa sai nhiều hơn | High×Med | Validate per-tab, alert Telegram nêu rõ tab + dòng; `Center.loai` dropdown data-validation |
| Prompt phình khi KB tăng | Med×Med | Catalog 2 tầng: >30 khóa → `CATALOG_MODE=index` + `get_course_detail(cid)` (dict lookup, không RAG). Không refactor vì `course_index`/`course_blocks` keyed by cid ngay từ Ph01 |
| Cam kết trong Sheet do nhân viên tự viết | Med×High | Cột `duyet_boi`; quy trình duyệt phía trung tâm (business) |
| Chi phí token tăng ~4.5× | Med×Low | Context caching (prefix ổn định) + Flash-Lite cho node phụ |
| Khách gõ không dấu → RAG FAQ trượt | Med×Med | Cột `tu_khoa` nối vào `page_content` của FAQ/Center docs |

## 5. Success Metrics

**Tầng kiến thức**
- **% câu cấp trung tâm** (địa chỉ, giữ xe, thủ tục, thanh toán) trả lời không cần handoff — target >90% (hiện ~0%)
- % câu "nên học khóa nào" route đúng khóa
- **Zero incident** báo giá/ngày sai khóa
- FAQ tab tăng đều mỗi tuần (chỉ dấu vòng phản hồi đang chạy)

**Tầng sales**
- **% hội thoại thu được SĐT** ← chỉ số chính
- % hội thoại chốt được lịch học thử
- **Rớt ở nấc nào nhiều nhất** (stage machine cho biết miễn phí)
- **% hội thoại bot xin SĐT >1 lần → phải ≈ 0** (cảnh báo bot nài)
- % draft bị guard chặn, chia theo loại: giá / ngày / hối thúc / nhượng bộ giá

## 6. Next Steps

1. Implementation plan (`/ck:plan`) — schema migration + guard rework + sales layer
2. Ngoài code: nhân viên điền tab `Center` + `FAQ`; bổ sung cột verbatim mới cho 20 khóa hiện có
3. Chốt quy trình duyệt nội dung `Center.loai=verbatim` (cam kết/thành tích/cam kết gọi lại)
4. Shadow mode đo lại metrics §5 trước khi thả tự động

## Unresolved Questions

- Ai duyệt nội dung cam kết/thành tích trong tab `Center`? Cần người chịu trách nhiệm phía trung tâm (rủi ro pháp lý)
- ~~Có bao nhiêu khóa thật?~~ **Đã trả lời 2026-07-26: 15 khóa**, sẽ phình dần → đường tăng trưởng 2 tầng ở §A.1
- Context caching của Gemini có áp được cho prefix system prompt trong LangGraph setup hiện tại không — ảnh hưởng trực tiếp chi phí phương án C
- FAQ khởi tạo lấy từ đâu: log chat cũ của fanpage hay nhân viên tự soạn?
- Có đội telesales riêng không, hay tư vấn viên kiêm? Ảnh hưởng nội dung ô `Cam kết gọi lại`
- Buổi học thử/test đầu vào có giới hạn slot/ngày không? Nếu có, bot đang đặt chỗ mà không biết slot còn — cần quy trình thủ công phía tư vấn viên xác nhận lại
