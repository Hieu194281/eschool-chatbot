# Brainstorm — Platform chatbot đa lĩnh vực (multi-tenant, multi-vertical)

**Date:** 2026-07-26 10:47 | **Type:** brainstorm | **Status:** kiến trúc chốt, scope còn 2 ẩn số
**Quyết định của user:** build platform (không dừng ở config-driven N-deploy)
**Constraint:** **repo MỚI** — không refactor `eschool-chatbot` in-place
**Tiền đề:** `brainstorm-260726-1007-kb-rag-schema-tuyensinh.md` (refactor KB+guard+sales đang chờ làm trên repo cũ)

---

## 1. Problem Statement

Bot tuyển sinh (Pha 1, `shadow_mode=True`, chưa live) và bot trà hiện phải là 2 repo riêng. Muốn: 1 platform, tạo chatbot + tạo KB, áp cho nhiều lĩnh vực.

**3 việc bị gộp làm 1, chi phí chênh ~10×:**

| # | Việc | Chi phí |
|---|---|---|
| 1 | Tái dùng code (1 repo, N deploy, mỗi bot 1 config) | rẻ |
| 2 | Multi-tenant runtime (1 deploy phục vụ N bot) | trung bình — phá mọi singleton |
| 3 | Màn tạo chatbot/KB self-serve | **một sản phẩm khác** |

## 2. Coupling thực tế của repo cũ (đã đọc code)

Domain "tuyển sinh" chỉ nằm ở 5 file: `graph/prompts/system_prompt.py` (hardcode 100%), `kb/course_parser.py` (schema cứng), `graph/nodes/pricing_guard.py`, `graph/tools/lead_tools.py`, `graph/prompts/{grade,reflect}_prompt.py`.

**~70% đã domain-agnostic:** toàn bộ `app/channel/`, `app/db/`, `app/llm/`, `app/handoff/`, `log_redaction_filter`, xương LangGraph, `common/vn_numerals`.

Trùng khớp với mục "Không đổi" trong brainstorm KB sáng nay → **S0 chạy song song được với refactor tuyensinh** (xem §7).

## 3. Approaches evaluated

### 3.1 Repo strategy

| | A — fork & tweak (2 repo) | B — config-driven, N deploy | **C — platform multi-tenant (chốt)** |
|---|---|---|---|
| Bot mới | copy repo, sửa | +1 config +1 deploy | +1 row DB |
| Sửa bug guard | ×N repo | 1 chỗ | 1 chỗ |
| Vận hành | N repo | N deploy | 1 deploy |
| UI tạo bot | không | không | có (giai đoạn cuối) |
| Chi phí đầu | 0 | thấp | cao |

Chọn C theo yêu cầu user. B là fallback nếu gate S1/S3 fail.

### 3.2 Chiến lược graph cho nhiều domain

| | S1 — 1 graph duy nhất | S2 — mỗi bot 1 graph | **S3 — mỗi template 1 graph (chốt)** |
|---|---|---|---|
| Số compiled instance | 1 | = số bot | = số template (3–5) |
| Node trong graph | hợp mọi pack | đúng nhu cầu | đúng nhu cầu |
| Engine biết domain? | **có ⇒ phá luật L1** | không | không |
| Topology drift giữa bot | không thể | **rất dễ ⇒ fork tầng graph** | không thể trong cùng template |
| Bug pack `cart` ảnh hưởng bot tuyển sinh | **có** | không | không |

`compile()` rẻ (dựng Pregel, không network) → S2 không *đắt*, nhưng mời gọi lệch topology từng bot = đúng cái fork cần tránh.

## 4. Kiến trúc chốt

### 4.1 Bốn tầng

```
L4  DỮ LIỆU TENANT   KB rows · leads · orders · hội thoại · handoff     (đổi mỗi ngày)
L3  MANIFEST BOT     tenants/<slug>/bot.yaml → template + persona + KB  (đổi mỗi tuần)
L2  DOMAIN TEMPLATE  lead-gen-edu · retail-consult · retail-order · support-faq
                     = playbook + tool pack + guard pack + stage machine
L1  ENGINE           assembler · guard runner · KB pipeline · channel ·
                     tenancy · checkpointer · rate limit · handoff · obs
```

**Luật cứng:** L1 không được biết "khóa học" hay "trà" là gì. L2 biết *hình dạng phễu*. L3 biết *doanh nghiệp cụ thể*.

Mnemonic: **Engine không biết bán gì · Template biết bán kiểu gì · Manifest biết ai bán · Data biết bán cái gì.**

### 4.2 Chia biến thiên theo 2 trục

| Biến thiên theo | Ví dụ | Đi vào đâu |
|---|---|---|
| **Template** | có node `cart` không · tool set · stage machine · loại guard | **closure lúc `compile()`** |
| **Tenant** | persona text · KB snapshot · giá trị verbatim · sheet id | **`config["configurable"]` lúc invoke** |

```python
# engine/graph/registry.py — cache key là TEMPLATE FINGERPRINT, không phải tenant_id
_cache: dict[str, object] = {}

def get_graph(tenant, checkpointer):
    key = tenant.template.fingerprint      # "lead-gen-edu@v3+objection+booking"
    g = _cache.get(key)
    if g is None:
        g = _cache[key] = build_graph(tenant.template, checkpointer)
    return g
```

```python
# engine/graph/assembler.py
def build_graph(tpl, checkpointer):
    g = StateGraph(ConvState)
    g.add_node("agent",     make_agent(tpl.persona_tmpl, tpl.tools))
    g.add_node("tool_exec", make_tool_exec(tpl.tools))
    g.add_node("grade",     make_grade(tpl.grade_prompt))
    g.add_node("reflect",   make_reflect(tpl.reflect_rules))
    g.add_node("guard",     make_guard(tpl.guard_pack))
    g.add_node("fallback",  make_fallback(tpl.fallback_line))
    wire_skeleton(g)
    for pack in tpl.packs:      # objection · booking · cart · order · shipping
        pack.attach(g)          # tự add_node + rewire edge
    return g.compile(checkpointer=checkpointer)
```

**[CRITICAL] Chỉ nhét `tenant_id` dạng string vào `configurable`, resolve object trong node qua registry.** `configurable` đi kèm checkpoint metadata, có thể bị serialize. Repo cũ đã set `langgraph_strict_msgpack=True` → đã từng bị serialization cắn, đừng mở lại cửa đó.

**Luật giữ hệ không thoái hóa:** config tenant KHÔNG được đổi topology. Cần thêm/bớt node → template mới hoặc pack mới. `fingerprint` = hash(template version + danh sách pack) ⇒ `lead-gen-edu` và `lead-gen-edu+objection` tự thành 2 entry cache, vẫn bounded.
**Escape hatch:** khách one-off khai `packs: [custom/acme-x]` → pack riêng trong `packs/`, tự sinh fingerprint riêng, không làm bẩn template chung.

### 4.3 Guard pack — moat sống sót qua tổng quát hóa

`pricing_guard` hiện tại (so token tiền với `hoc_phi` của khóa retrieve được) → tổng quát thành runner + khai báo:

```yaml
# templates/lead-gen-edu/guards.yaml
- type: verbatim_binding
  entity: course
  fields:    [hoc_phi, uu_dai, khai_giang, si_so, giao_vien_ten]
  detectors: [vn_money, vn_date, integer, proper_noun]
- type: forbidden_phrases
  groups: [urgency, price_concession, guarantee]
```

Refactor §A.5 (course-mention binding + `facts_map`) chốt sáng nay **chính là** bước generalize này — không trùng công, chỉ khác là viết dạng khai báo thay vì hardcode `hoc_phi`.

### 4.4 Request flow

```
POST /webhook/messenger
  ├─ verify X-Hub-Signature        (1 Meta App, app_secret dùng chung N page)
  ├─ entry[].id = page_id ──► TenantResolver ──► tenant_id
  ├─ dedupe(mid) · debounce(6s) · rate_limit(tenant_id)     ← budget THEO tenant
  ├─ GraphRegistry.get(tenant) ─miss─► assemble từ template
  ├─ invoke(thread_id = f"{tenant_id}:messenger:{psid}", configurable.tenant_id)
  └─ shadow_gate(tenant)   on→Telegram tenant   |   off→Messenger thật
```

**3 chỗ sai = rò dữ liệu giữa khách hàng:**
1. `thread_id` thiếu `tenant_id` → trộn hội thoại (Messenger psid unique, nhưng Zalo/web widget thì không)
2. Query Postgres (`handoff_status`, leads, orders) thiếu `tenant_id` trong `WHERE` → dùng RLS
3. `page_access_token` phải per-tenant, mã hóa trong DB — không còn ở env

### 4.5 Trần tài nguyên

gemini-embedding-001 = 3072 dim × 4B = **12.3KB/vector**. 300 doc ≈ 3.7MB/tenant.

| Số bot | KB in-memory | Trạng thái |
|---|---|---|
| 20 | ~74MB | ổn |
| 50 | ~185MB | ổn, bắt đầu để ý cold start (re-embed mỗi restart) |
| 200 | ~740MB | **phải chuyển pgvector** |

Compiled graph không phải nút cổ chai (KB mỗi cái). **KB snapshot mới là.** Ngưỡng chuyển pgvector: **~50–100 bot**.

## 5. Repo structure (repo mới)

```
chatbot-platform/
├── engine/                    ← L1, bê 70% từ eschool-chatbot, KHÔNG viết mới
│   ├── graph/assembler.py · registry.py · nodes/ (factory fns)
│   ├── guards/                ← runner + detectors (vn_money, vn_date, phrases)
│   ├── kb/                    ← loader(sheet|csv|db) → classify(schema.yaml) → embed → snapshot
│   ├── channel/               ← messenger · zalo · telegram        ⟵ copy nguyên + test
│   ├── tenancy/               ← registry · resolver(page_id→tenant) · secret vault
│   ├── integrations/          ← StockProvider · OrderSink interface (POS adapter)
│   └── obs/                   ← log redaction · metrics · shadow gate
├── templates/  lead-gen-edu/ · retail-consult/ · retail-order/ · support-faq/
│                 └─ persona.md · playbook.md · tools.py · guards.yaml · stages.yaml
├── packs/      objection/ · booking/ · cart/ · order/ · shipping/
├── tenants/    eschool-tuyensinh/bot.yaml · traviet/bot.yaml
└── admin/      ← Next.js, giai đoạn S4
```

## 6. Vertical #2 = retail-order (bot trà bán hàng)

**Khác loại, không khác mức độ:** bot tuyển sinh kết thúc ở *"giao 1 SĐT cho người thật"*; bot trà kết thúc ở *"commit một giao dịch"*. Sai của bot 1 = mất lead. Sai của bot 2 = giao sai hàng, thu sai tiền, bán vượt kho.

### 6.1 Tái dùng

| | retail-order dùng lại |
|---|---|
| `engine/channel` · `db` · `llm` · `obs` · `handoff` · xương graph | **100%** |
| `engine/kb` | 100% cho thông tin SP · **0% cho tồn kho** |
| `engine/guards` runner + detectors | ~80% (thêm 1 loại source) |
| `templates/lead-gen-edu` playbook/stage/cớ xin SĐT | **~25%** |
| `packs/cart` · `order` · `shipping` | **0% — viết mới** |

⇒ **engine ~95%, template ~25%.** Tầng engine là thứ trả lời "1 repo hay 2 repo" → 1 repo thắng rõ.

**Điểm mạnh ngoài dự kiến:** một vertical khác hình dạng phễu là **bài test thật** của boundary L1/L2. Tenant #2 nếu lại là lead-gen (trung tâm khác, phòng khám) thì chứng minh được rất ít.

### 6.2 Ba thứ order bot cần mà lead-gen không cần

**① Dữ liệu live — snapshot vô dụng.** KB sync 5 phút hoàn hảo cho khóa học, **chí tử cho tồn kho**. Đây là tầng 4 "live tool" trong mô hình 4 tầng (§A.2 brainstorm KB) — tầng đang hoãn sang Pha 2. Order bot cần nó từ ngày đầu.

**② Triết lý lỗi đảo ngược.** Hiện `run_capture_lead` nuốt exception (*"non-fatal: never break the reply over a Sheet hiccup"*) — đúng vì mọi side effect idempotent.
```
lead-gen  → fail-OPEN : Sheet lỗi vẫn chat tiếp
order     → fail-CLOSED: không chắc đã tạo đơn ⇒ KHÔNG được nói "đã đặt hàng"
```
`debounce(6s)` + `dedupe(mid)` + single-flight đã có là nền tốt. Thêm **idempotency key = hash(thread_id + cart fingerprint)** — khách gõ "ok" 2 lần không ra 2 đơn.

**③ Bot buộc phải tính tiền** — đúng thứ nguyên tắc vàng đang cấm (`system_prompt.py`: *"TUYỆT ĐỐI KHÔNG tự tính giá sau giảm"*).

Gỡ: **không cho LLM tính.** Cart là object Python authoritative, tiền tính bằng Python, LLM chỉ đọc lại.

```yaml
# templates/retail-order/guards.yaml
- type: verbatim_binding          # số liệu tĩnh khớp KB
  entity: product
  fields: [gia, xuat_xu, khoi_luong]
- type: computed_binding          # MỚI — mọi token tiền khớp cart đã tính
  source: cart
  fields: [subtotal, ship_fee, discount, total, items[].don_gia]
- type: tool_backed_claim         # MỚI — đắt giá nhất
  claims: [con_hang, het_hang, so_luong_ton]
  requires_tool: check_stock      # lượt này chưa gọi check_stock → CHẶN
- type: forbidden_phrases
  groups: [urgency, guarantee]
```

`tool_backed_claim` = `pricing_guard` chuyển thể: deterministic, kiểm được, chặn đúng cái nguy hiểm nhất (hứa còn hàng mà chưa tra).

### 6.3 Delta graph + stage

```
packs/order ─┬─ check_stock       LIVE, không qua snapshot
             ├─ cart_add/remove ─► cart node (deterministic, tính tiền)
             ├─ quote_shipping     (bảng phí theo tỉnh × khối lượng)
             └─ create_order ────► CONFIRM GATE (2 bước + idempotency key)

stage: moi → ro_gu → goi_y_sp → co_gio_hang → co_dia_chi → cho_xac_nhan → da_tao_don → handoff
```

Objection chuyển được: `gia_cao` ✓ · `suy_nghi` ✓ · `so_sanh_cho_khac` ✓ · `lich_ban` ✗ · `hoi_y_nguoi_khac` ✗. Mới: `phi_ship_cao`, `so_hang_gia`, `doi_COD`.

### 6.4 Nguồn tồn kho — abstract, đừng chờ câu trả lời

`engine/integrations/` khai 2 interface (cùng pattern `adapter_interface.py` đã có cho channel):

```python
class StockProvider(Protocol):    # KiotViet · Sapo · Haravan · Nhanh · SheetStock · NullStock
    async def check(self, sku: str) -> StockInfo: ...
class OrderSink(Protocol):        # POS API · PlatformDB · SheetSink
    async def create(self, order: Order, idem_key: str) -> OrderRef: ...
```

| Shop đang dùng | Provider | Ghi chú |
|---|---|---|
| Sapo / KiotViet / Haravan / Nhanh.vn | POS adapter | **Tốt nhất** — bot không sở hữu kho; adapter tái dùng cho mọi khách retail sau |
| Không có gì / Excel | `SheetStock` + `PlatformDB` | **2 nguồn sự thật về kho = rủi ro vận hành**. Bắt buộc: `tool_backed_claim` + confirm gate người thật |
| Chỉ Shopee/TikTok Shop | — | đơn Messenger là thứ yếu |

## 7. Lộ trình

Giả định: 1 dev full-time, tái dùng ~70% code sẵn.

| Sprint | Nội dung | Gate pass/fail | Ước |
|---|---|---|---|
| **S−1** *(repo cũ)* | Xong refactor KB+guard+sales · ship prod · **freeze** | tuyensinh live, shadow off | (đang làm) |
| **S0** ‖ *song song S−1* | Bê `engine/` floor: `channel/` `db/` `llm/` `handoff/` `obs/` `vn_numerals` + **9 test file kèm theo**. Khung `tenancy/` | 9 test copy sang **xanh, không sửa logic** | 2–4 ngày |
| **S1** | `assembler` + `registry` + node factories + `guards/` runner + `kb/` pipeline generic + `templates/lead-gen-edu` + `tenants/eschool-tuyensinh/bot.yaml` | **Parity**: chạy shadow song song repo cũ, cùng input → output tương đương | 2–3 tuần |
| **S2** | Multi-tenant runtime: tenant table · resolver `page_id→tenant` · secret vault (PAT mã hóa) · budget/rate theo tenant · `tenant_id` trong `thread_id` + mọi WHERE (RLS) · KB snapshot registry | 1 deploy 2 tenant, **test rò dữ liệu chéo phải fail-safe** | 1.5–2 tuần |
| **S3** | Vertical #2: `templates/retail-order` + `packs/{cart,order,shipping}` + `integrations/{StockProvider,OrderSink}` + `computed_binding` + `tool_backed_claim` | **KHÔNG sửa 1 dòng nào trong `engine/`** ← bài test sinh tử | 3–4 tuần |
| **S4** | Admin UI (Next.js), đúng thứ tự: KB editor → log hội thoại → lead/order list → **màn tạo bot (cuối)** | nhân viên tenant tự sửa KB không cần bạn | 3–5 tuần |
| **S5** | Self-serve SaaS: auth · billing · onboarding · metering · **Meta App Review** | khách tự nối fanpage | nhiều tháng, phụ thuộc Meta |

**S0 song song được với S−1** vì brainstorm KB sáng nay ghi rõ mục "Không đổi": *channel adapters, debounce/dedupe, handoff manager, Telegram notifier, PostgresSaver* — đúng những gì S0 bê đi. Không tranh chấp file.

**Tới S3 = ~2–2.5 tháng** (2 vertical trên 1 platform). **Tới S4 = ~3.5 tháng.**

**Màn "tạo chatbot" nằm cuối S4, không phải đầu** — trước S3 chưa biết form đó cần ô gì.

### Gate quan trọng nhất

> **S3: viết pack mới thì được, sửa `engine/` thì KHÔNG.**
> Nếu để cart chạy được mà phải mở `engine/graph/assembler.py` hay `engine/guards/runner.py` → boundary L1/L2 sai. **Dừng, sửa boundary, đừng đi tiếp lên S4.**

## 8. Risks

| Risk | L×I | Mitigation |
|---|---|---|
| **Dual maintenance repo cũ ↔ platform** | High×High | S1 parity + freeze repo cũ ngay sau đó. Không có mốc freeze → fork vĩnh viễn |
| **Trừu tượng hóa từ 1 ví dụ chưa chạy thật** | High×High | S−1 ship tuyensinh trước; S1 parity là target tĩnh, không di chuyển |
| **Boundary L1/L2 sai, phát hiện muộn ở S4** | Med×High | Gate S3 tuyệt đối; không build UI trước khi S3 xanh |
| **Rò dữ liệu giữa tenant** | Med×Critical | `tenant_id` trong `thread_id` + RLS + test rò chéo là điều kiện pass S2 |
| **Order bot bán vượt kho** | High×High | `tool_backed_claim` + `StockProvider` live + confirm gate 2 bước |
| **Đơn trùng do debounce/retry** | Med×High | idempotency key = hash(thread_id + cart fingerprint), fail-closed |
| **2 nguồn sự thật tồn kho** (shop không có POS) | Med×High | Ưu tiên POS adapter; nếu không có → kho advisory + người xác nhận |
| Noisy neighbor: 1 tenant đốt hết quota Gemini | Med×Med | budget/rate limit theo tenant từ S2 (hiện đang global) |
| RAM KB tuyến tính theo tenant | Low×Med | ngưỡng ~50–100 bot → pgvector |
| `configurable` bị serialize vào checkpoint | Med×Med | chỉ `tenant_id` string, resolve qua registry |
| Meta App Review chặn self-serve | Med×High | S5; agency model (page của bạn quản) không cần review nặng |
| Cạnh tranh Dify/Chatbase/Ahachat/Bothub | High×Med | Moat = guard verbatim + playbook VN theo vertical, KHÔNG phải builder UI |

## 9. Success Metrics

**Kiến trúc** (đo được, không cảm tính):
- S1: parity — % lượt output tương đương repo cũ trên cùng bộ input
- S3: **số dòng `engine/` phải sửa để thêm vertical retail-order = 0**
- Thời gian onboard bot mới cùng template: mục tiêu **< 1 ngày** (hiện: ~1 tuần fork repo)
- Số compiled graph = số template (không được tăng theo số bot)

**Sản phẩm:** % câu trả lời không cần handoff · % hội thoại thu SĐT (lead-gen) · % hội thoại tạo đơn (retail) · % draft bị guard chặn theo loại · **zero incident** báo sai giá/kho.

## 10. Next Steps

1. `/ck:plan` cho **S0 + S1** (2 sprint đầu, đủ rõ để plan chi tiết). S2–S4 plan sau khi S1 xanh.
2. Tiếp tục S−1 trên repo cũ song song (refactor KB per brainstorm 1007).
3. Chốt 2 ẩn số ở §11 trước khi bắt đầu S3.
4. Đặt tên + tạo repo mới; quyết stack `admin/` (khuyến nghị: engine Python giữ nguyên, admin Next.js riêng — không port graph sang TS).

## 11. Unresolved Questions

- **Tồn kho + đơn hàng shop trà hiện nằm ở đâu?** (POS nào / Excel / không có) — quyết định `StockProvider` nào là mặc định và S3 nặng hay nhẹ. **Chặn S3, không chặn S0–S2.**
- **Shop trà là khách trả tiền thật hay giả định?** Nếu giả định → cân nhắc đảo S3 xuống sau, bán bot lead-gen thứ hai trước (cùng phễu, ~0 code mới) để có doanh thu.
- Mô hình kinh doanh cuối: agency (bạn setup) hay SaaS self-serve? Quyết định S5 có tồn tại và Meta App Review có cần không.
- Số bot mục tiêu 12 tháng — quyết định ngưỡng pgvector có chạm trong tầm nhìn không.
- Zalo OA có trong phạm vi không? (`adapter_interface` đã sẵn, nhưng OA có quota + quy trình duyệt riêng)
- Thanh toán bot trà: chỉ COD, hay có VietQR/SePay? Nếu có → thêm `packs/payment` + webhook đối soát.
- Ai chịu trách nhiệm nội dung `verbatim` của từng tenant (cam kết, giá, kho)? Rủi ro pháp lý nhân N khách.
