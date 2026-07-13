"""Reflect-lite prompt + deterministic promise-phrase blocklist.

Scope is DEMOTED to forbidden-promise / tone ONLY. Number checking lives in the
deterministic pricing_guard. The regex blocklist is first-line (known phrases);
Flash-Lite catches paraphrases the regex misses.
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
