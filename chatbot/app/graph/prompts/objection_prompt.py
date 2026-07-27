"""Objection classification + handling playbook (5 groups).

Static repo data on purpose. Moving this to the Sheet would hand staff — and
anyone who can edit the Sheet — a direct channel into the instruction half of the
prompt. Course facts come from the Sheet and are sanitized; behaviour rules do not.

Classification biases toward `none`. A false positive turns an ordinary question
("khai giảng khi nào?") into a defensive objection reply, which is worse than
missing an objection: the normal branch still answers the question correctly.
"""

from __future__ import annotations

NONE = "none"
GIA_CAO = "gia_cao"
SUY_NGHI = "suy_nghi"
HOI_Y_NGUOI_KHAC = "hoi_y_nguoi_khac"
LICH_BAN = "lich_ban"
SO_SANH_CHO_KHAC = "so_sanh_cho_khac"

OBJECTION_TYPES = (NONE, GIA_CAO, SUY_NGHI, HOI_Y_NGUOI_KHAC, LICH_BAN, SO_SANH_CHO_KHAC)

# `so_sanh_cho_khac` has no entry: it never generates a reply, it hands off.
OBJECTION_PLAYBOOK = {
    GIA_CAO: {
        "lam": (
            "1) Ghi nhận cảm giác của khách, KHÔNG phản bác.\n"
            "2) Tách nhỏ chi phí theo buổi/tháng nếu số liệu có sẵn trong khối chi tiết khóa.\n"
            "3) Quy về giá trị: sĩ số, giáo viên, chính sách học bù — chỉ nêu điều CÓ trong KB.\n"
            "4) Nếu KB có nội dung trả góp, đọc ĐÚNG NGUYÊN VĂN nội dung đó."
        ),
        "cam": (
            "TUYỆT ĐỐI không giảm giá, không 'để em xin sếp', không 'ưu đãi riêng', "
            "không 'giá đặc biệt'. Chỉ được nhắc lại đúng ô Ưu đãi có sẵn."
        ),
    },
    SUY_NGHI: {
        "lam": (
            "Tôn trọng nhịp quyết định của khách. Chốt một giá trị nhỏ, không phải cái bán: "
            "đề nghị gửi lộ trình học chi tiết để anh/chị xem dần."
        ),
        "cam": (
            "Không hỏi 'anh/chị còn băn khoăn gì ạ' lần thứ hai, không hối thúc, "
            "không nhắc thời hạn."
        ),
    },
    HOI_Y_NGUOI_KHAC: {
        "lam": (
            "Ủng hộ việc bàn với người nhà. Đề nghị gửi lộ trình + học phí để cả nhà cùng xem — "
            "đây cũng là cớ tự nhiên để xin số liên hệ nếu chưa có."
        ),
        "cam": "Không ép quyết ngay, không hạ thấp vai trò người còn lại.",
    },
    LICH_BAN: {
        "lam": (
            "Hỏi buổi/khung giờ khách rảnh, rồi tra [MỤC LỤC KHÓA] và [CHI TIẾT KHÓA] "
            "để đề xuất ca hoặc khóa khác có lịch phù hợp."
        ),
        "cam": (
            "Không hứa mở lớp mới, không hứa đổi lịch lớp hiện có, "
            "không nêu ngày/giờ không có trong KB."
        ),
    },
}

_FEW_SHOT = """Ví dụ:
"học phí mắc quá em ơi" → gia_cao
"đắt v" → gia_cao
"cao hơn dự tính của chị rồi" → gia_cao
"để chị suy nghĩ thêm nhé" → suy_nghi
"để t tính đã" → suy_nghi
"chị cân nhắc rồi báo lại" → suy_nghi
"để hỏi ck cái đã" → hoi_y_nguoi_khac
"chị bàn với ba cháu đã nhé" → hoi_y_nguoi_khac
"giờ đó cháu bận học thêm rồi" → lich_ban
"lịch này trùng mất em ạ" → lich_ban
"bên kia rẻ hơn" → so_sanh_cho_khac
"chị đang xem trung tâm ABC nữa" → so_sanh_cho_khac
"khai giảng khi nào em" → none
"học phí bao nhiêu vậy" → none
"cho chị xin địa chỉ" → none
"cháu đang học lớp 7" → none
"""


def build_detect_prompt(message: str) -> str:
    return (
        "Bạn là bộ phân loại phản đối bán hàng. Đọc TIN NHẮN CUỐI của khách và chọn "
        "ĐÚNG MỘT nhãn:\n"
        "- gia_cao: chê đắt, than học phí cao\n"
        "- suy_nghi: hoãn quyết định, cần cân nhắc thêm\n"
        "- hoi_y_nguoi_khac: cần hỏi vợ/chồng/ông bà/người nhà\n"
        "- lich_ban: vướng lịch, giờ học không tiện\n"
        "- so_sanh_cho_khac: đang so sánh với trung tâm khác\n"
        "- none: mọi trường hợp còn lại (hỏi thông tin, cung cấp thông tin, chào hỏi)\n\n"
        "QUAN TRỌNG: chỉ hỏi giá KHÔNG phải là gia_cao — phải có ý CHÊ đắt. "
        "Nếu phân vân giữa một nhãn và none, LUÔN chọn none.\n\n"
        f"{_FEW_SHOT}\n"
        f"TIN NHẮN CUỐI CỦA KHÁCH:\n{message}\n"
    )


def build_handle_prompt(objection_type: str, verbatim: dict | None = None) -> str:
    """The extra constraint block for the objection branch. Empty → no playbook."""
    play = OBJECTION_PLAYBOOK.get(objection_type)
    if not play:
        return ""
    lines = [
        f"Khách đang phản đối nhóm '{objection_type}'. Xử lý theo đúng kịch bản sau, "
        f"trả lời NGẮN, ấm áp, chỉ một ý chính:",
        f"CÁCH LÀM:\n{play['lam']}",
        f"CẤM:\n{play['cam']}",
    ]
    if objection_type == GIA_CAO and (verbatim or {}).get("Trả góp"):
        lines.append(f"Nội dung trả góp được phép trích NGUYÊN VĂN:\n\"{verbatim['Trả góp']}\"")
    return "\n\n".join(lines)
