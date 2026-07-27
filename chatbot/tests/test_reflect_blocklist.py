"""Reflect blocklist: scarcity, urgency and invented call-back deadlines.

These are TONE violations, so they live here (repairable by stripping) rather than
in the fail-closed pricing_guard, which would discard the whole reply.
"""

import pytest

from app.graph.prompts.reflect_prompt import blocklist_hit, strip_blocklist

FORBIDDEN = [
    "Lớp chỉ còn 2 chỗ thôi ạ",
    "Bên em còn 3 suất cuối ạ",
    "Lớp sắp hết chỗ rồi ạ",
    "Anh/chị nhanh kẻo hết ạ",
    "Mình quyết sớm giúp em nhé",
    "Chị đăng ký ngay hôm nay nhé",
    "Em sẽ gọi lại trong 5 phút ạ",
    "Tư vấn viên sẽ gọi lại trong 30 phút nhé",
    "Chút nữa em gọi cho chị nhé",
    "Em đảm bảo đậu ạ",                    # pre-existing rule still enforced
]

ALLOWED = [
    "Dạ khóa này còn nhận học viên mới ạ",
    "Lớp học 18h00-19h30 các tối thứ 3 và 5 ạ",
    "Tư vấn viên sẽ liên hệ với mình ạ",
    "Anh/chị cho em xin khung giờ tiện để tư vấn viên gọi ạ",
    "Khóa này giúp con giảm áp lực học tập ạ",
]


@pytest.mark.parametrize("text", FORBIDDEN)
def test_forbidden_phrases_caught(text):
    assert blocklist_hit(text) is not None


@pytest.mark.parametrize("text", ALLOWED)
def test_legitimate_phrases_pass(text):
    assert blocklist_hit(text) is None


def test_strip_removes_only_the_offending_phrase():
    stripped = strip_blocklist("Dạ khóa IELTS học phí 5 triệu, lớp chỉ còn 2 chỗ thôi ạ")
    assert "chỗ" not in stripped
    assert "5 triệu" in stripped
