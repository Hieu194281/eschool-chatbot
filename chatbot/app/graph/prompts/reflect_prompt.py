"""Reflect-lite prompt + deterministic promise-phrase blocklist.

Scope is DEMOTED to forbidden-promise / tone ONLY. Number checking lives in the
deterministic pricing_guard. The regex blocklist is first-line (known phrases);
Flash-Lite catches paraphrases the regex misses.

Scarcity/urgency phrases and invented call-back deadlines live HERE rather than in
the fail-closed guard on purpose: they are a TONE problem, and reflect_lite has a
repair path (strip the phrase, keep the answer). Sending the honest-fallback
instead would throw away a perfectly good reply over one pushy clause.
"""

import re

# Known forbidden-promise phrases (first-line, deterministic).
_BLOCKLIST_PATTERNS = [
    r"đảm\s*bảo\s*(?:đậu|đỗ|giỏi|điểm)",
    r"cam\s*kết\s*(?:đậu|đỗ|giỏi|điểm)",
    r"chắc\s*chắn\s*(?:đậu|đỗ|giỏi|\d)",
    r"bao\s*(?:đậu|đỗ)",
    r"(?:đảm\s*bảo|cam\s*kết|chắc\s*chắn)\s*100\s*%",
    r"miễn\s*phí\s*100\s*%",
    r"100\s*%\s*(?:đậu|đỗ|giỏi)",
    # Scarcity — the centre has no "seats left" data and must never imply it.
    r"(?:chỉ\s*)?còn\s*\d+\s*(?:chỗ|suất|slot)",
    r"chỉ\s*còn\s*(?:vài|ít|mấy)\s*(?:chỗ|suất|slot)",
    r"sắp\s*(?:hết|đầy)\s*(?:chỗ|suất|lớp)?",
    r"nhanh\s*kẻo\s*(?:hết|muộn)",
    # Urgency / pressure.
    r"quyết\s*(?:định\s*)?sớm",
    r"gấp\s*lên",
    r"đăng\s*ký\s*ngay\s*(?:hôm\s*nay|bây\s*giờ)",
    r"(?:trong|ngay)\s*hôm\s*nay\s*(?:thôi|nhé|kẻo)",
    # Invented call-back deadlines — only Center["Cam kết gọi lại"] may state one.
    r"gọi\s*(?:lại\s*)?(?:cho\s*(?:anh|chị)\s*)?trong\s*(?:vòng\s*)?\d+\s*(?:phút|giờ|tiếng)",
    r"(?:em|tư\s*vấn\s*viên)\s*sẽ\s*gọi\s*(?:lại\s*)?(?:ngay\s*)?(?:trong\s*)?\d+\s*(?:phút|giờ|tiếng)",
    r"chút\s*nữa\s*(?:em\s*)?(?:sẽ\s*)?gọi",
]
_BLOCKLIST_RE = re.compile("|".join(_BLOCKLIST_PATTERNS), re.IGNORECASE)


def blocklist_hit(text: str) -> str | None:
    """Return the offending phrase if a known forbidden promise is present."""
    m = _BLOCKLIST_RE.search(text or "")
    return m.group(0) if m else None


def strip_blocklist(text: str) -> str:
    """Deterministically remove known forbidden-promise phrases from `text`."""
    return _BLOCKLIST_RE.sub("", text or "").strip()


def build_reflect_prompt(draft: str) -> str:
    return (
        "Bạn kiểm duyệt câu trả lời của tư vấn viên tuyển sinh. CHỈ xét về HỨA HẸN CẤM và GIỌNG ĐIỆU "
        "(KHÔNG kiểm tra con số học phí — đã có hệ thống khác lo).\n"
        "Vi phạm nếu câu trả lời: hứa 'đảm bảo đậu/giỏi/điểm cao', cam kết kết quả học tập, "
        "'miễn phí 100%', hoặc giọng điệu không phù hợp (thô lỗ, ép buộc).\n"
        "Nếu vi phạm: ok=false, liệt kê issues, và đưa fixed_reply đã sửa (giữ nguyên ý, bỏ phần vi phạm).\n"
        "Nếu ổn: ok=true.\n\n"
        f"CÂU TRẢ LỜI:\n{draft}\n"
    )
