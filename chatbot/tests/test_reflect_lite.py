"""Reflect-lite deterministic first-line: forbidden-promise blocklist + strip."""

from app.graph.prompts.reflect_prompt import blocklist_hit, strip_blocklist


def test_blocklist_catches_known_promises():
    assert blocklist_hit("Bên em đảm bảo đậu nhé anh") is not None
    assert blocklist_hit("cam kết giỏi trong 3 tháng") is not None
    assert blocklist_hit("khóa này miễn phí 100%") is not None
    assert blocklist_hit("chắc chắn đậu luôn ạ") is not None


def test_blocklist_passes_clean_text():
    assert blocklist_hit("Dạ khóa học rất phù hợp với bé nhà mình ạ") is None


def test_strip_removes_offending_phrase():
    stripped = strip_blocklist("Bên em đảm bảo đậu, học phí ưu đãi ạ")
    assert "đảm bảo đậu" not in stripped
    assert "học phí ưu đãi" in stripped
