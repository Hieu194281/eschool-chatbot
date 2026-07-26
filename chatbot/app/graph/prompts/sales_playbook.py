"""Sales playbook — the `[SALES PLAYBOOK]` block injected per turn.

Text data + a few pure functions, so the whole thing is unit-testable.

Design rule that shapes everything here: inject ONLY the line for the CURRENT
stage, never the whole table. A model given six possible next actions picks one at
random; given one, it follows it. Same reason the elicitation returns exactly one
question — a bot that asks three things per turn reads as an interrogation.

Phone-ask reasons quote `Center.loai=verbatim` rows rather than inventing an offer.
When a row is missing, the reason degrades to the one that needs no data instead of
disappearing (Phase 01 already alerts on the missing row).
"""

from __future__ import annotations

from ..sales_stage import ORDER, SalesStage, normalize_stage

STAGE_ACTIONS = {
    SalesStage.MOI:
        "Hỏi 1 câu khơi gợi để hiểu nhu cầu. CHƯA đề xuất khóa, CHƯA báo giá.",
    SalesStage.DA_RO_NHU_CAU:
        "Đề xuất 1-2 khóa cụ thể kèm lộ trình ngắn. CHƯA báo giá trừ khi khách hỏi thẳng.",
    SalesStage.DA_BAO_GIA:
        "Xin số điện thoại MỘT LẦN kèm cớ hợp lý bên dưới. Khách né → tuyệt đối không xin lại.",
    SalesStage.CO_SDT:
        "Hỏi khung giờ tiện để tư vấn viên gọi, rồi đề xuất chốt lịch học thử.",
    SalesStage.DA_HEN_LICH:
        "Xác nhận lịch, nhắc cần mang gì. NGỪNG chào bán.",
    SalesStage.HANDOFF:
        "Tư vấn viên người thật đang tiếp quản — không tự trả lời.",
}

# Order matters: this is the sequence the customer is walked through.
ELICITATION = (
    ("lop", "Dạ bé nhà mình đang học lớp mấy ạ?"),
    ("tinh_trang", "Hiện tại lực học môn này của bé thế nào ạ?"),
    ("muc_tieu", "Anh/chị mong bé đạt được gì sau khóa học ạ?"),
    ("co_so", "Mình tiện đi cơ sở nào ạ?"),
    ("lich_ranh", "Bé thường rảnh học vào buổi nào trong tuần ạ?"),
)

# (signal predicate, reason template, Center.verbatim topic it quotes)
_WEAK_WORDS = ("yếu", "mất gốc", "kém", "chưa rõ", "không theo kịp", "sợ")

SALES_FORBIDDEN = (
    "KHÔNG nói số chỗ còn lại / sắp hết chỗ dưới mọi hình thức — trung tâm không có dữ liệu này.",
    "KHÔNG hối thúc (nhanh kẻo hết, quyết sớm, đăng ký ngay hôm nay).",
    "KHÔNG tự hứa mốc gọi lại — chỉ đọc đúng nội dung 'Cam kết gọi lại' nếu có.",
    "KHÔNG xin số điện thoại lần thứ hai sau khi khách đã né.",
    "KHÔNG hỏi quá 1 câu trong một lượt.",
    "KHÔNG tự nghĩ ra ưu đãi/giảm giá ngoài ô 'Ưu đãi' của khóa.",
)


def next_elicitation(profile: dict) -> tuple | None:
    """First still-empty elicitation field, or None when the profile is complete."""
    profile = profile or {}
    return next(((f, q) for f, q in ELICITATION if not profile.get(f)), None)


def phone_reason(profile: dict, verbatim: dict) -> str:
    """Pick the ask-for-phone excuse that fits what we know about this customer."""
    profile, verbatim = profile or {}, verbatim or {}
    tinh_trang = (profile.get("tinh_trang") or "").lower()

    if any(word in tinh_trang for word in _WEAK_WORDS) and verbatim.get("Test đầu vào"):
        return ("Mời khách làm bài test đầu vào để biết bé đang hổng phần nào — "
                f"đọc đúng nội dung: \"{verbatim['Test đầu vào']}\"")
    if profile.get("lich_ranh"):
        return "Xin SĐT để giữ chỗ buổi học thử vào đúng buổi khách đã nói là rảnh."
    if verbatim.get("Cam kết gọi lại"):
        return ("Xin SĐT để tư vấn viên gửi bảng học phí chi tiết — "
                f"đọc đúng nội dung cam kết: \"{verbatim['Cam kết gọi lại']}\"")
    return "Xin SĐT để gửi lộ trình học chi tiết qua Zalo."


def render_playbook(state: dict, verbatim: dict | None = None) -> str:
    """The `[SALES PLAYBOOK]` body for THIS turn. Empty string → block omitted."""
    state = state or {}
    stage = normalize_stage(state.get("sales_stage"))
    profile = state.get("lead_profile") or {}

    lines = [f"Nấc hiện tại: {stage} ({_position(stage)})",
             f"Việc DUY NHẤT cần làm lượt này: {STAGE_ACTIONS[stage]}"]

    if stage not in (SalesStage.DA_HEN_LICH, SalesStage.HANDOFF):
        pending = next_elicitation(profile)
        if pending:
            lines.append(f"Câu khơi gợi kế tiếp (hỏi TỐI ĐA 1 câu, và chỉ khi khách "
                         f"không đang chờ mình trả lời): {pending[1]}")
        if known := _known_fields(profile):
            lines.append(f"ĐÃ biết, KHÔNG hỏi lại: {known}")

    if stage == SalesStage.DA_BAO_GIA and not profile.get("sdt"):
        lines.append(f"Cớ xin SĐT lần này: {phone_reason(profile, verbatim)}")

    lines.append("CẤM:\n" + "\n".join(f"- {rule}" for rule in SALES_FORBIDDEN))
    return "\n".join(lines)


def _position(stage: str) -> str:
    if stage == SalesStage.HANDOFF:
        return "ngoài thang bán hàng"
    return f"nấc {ORDER.index(stage) + 1}/{len(ORDER)}"


def _known_fields(profile: dict) -> str:
    return ", ".join(f"{field}={profile[field]}"
                     for field, _ in ELICITATION if profile.get(field))
