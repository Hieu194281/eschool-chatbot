"""handle_objection: no tools bound, playbook injected, count/retry bookkeeping,
and the guard still catching a self-invented discount end-to-end.
"""

import app.graph.nodes.handle_objection as handle_mod
from app.graph.nodes.handle_objection import handle_objection_node
from app.graph.nodes.pricing_guard import evaluate_draft
from app.graph.prompts.objection_prompt import GIA_CAO, LICH_BAN

COURSE = {
    "course_id": "T7-MG", "ten_khoa": "Toán 7 Mất Gốc", "tu_khoa": [],
    "facts": "Học phí: 1.800.000\nƯu đãi: giảm 10%",
}


class _FakeKB:
    def get_catalog_text(self):
        return "[MỤC LỤC KHÓA]\nT7-MG  Toán 7 Mất Gốc"

    def get_center_always(self):
        return "Địa chỉ: 12 Lê Lợi"

    def get_verbatim_map(self):
        return {"Trả góp": "Hỗ trợ trả góp 0% qua thẻ tín dụng."}


class _FakeLLM:
    """Records the messages it was asked to complete; refuses to be bound to tools."""

    def __init__(self):
        self.seen = None

    def bind_tools(self, schemas):                     # pragma: no cover
        raise AssertionError("handle_objection must not bind tools")

    async def ainvoke(self, msgs):
        self.seen = msgs
        return _FakeAI("Dạ em hiểu ạ.")


class _FakeAI:
    type = "ai"

    def __init__(self, content):
        self.content = content


class _Human:
    type = "human"

    def __init__(self, content):
        self.content = content


async def _run(monkeypatch, state):
    import app.kb as kb_pkg

    llm = _FakeLLM()
    monkeypatch.setattr(kb_pkg, "knowledge_base", _FakeKB())
    monkeypatch.setattr(handle_mod, "main_llm", lambda: llm)
    out = await handle_objection_node(state)
    return out, llm


async def test_catalog_and_playbook_reach_the_prompt(monkeypatch):
    state = {"messages": [_Human("mắc quá em")], "objection_type": GIA_CAO}
    out, llm = await _run(monkeypatch, state)

    system_text = "\n".join(m.content for m in llm.seen if getattr(m, "type", "") != "human")
    assert "[MỤC LỤC KHÓA]" in system_text          # no retrieval needed
    assert "Địa chỉ: 12 Lê Lợi" in system_text
    assert "gia_cao" in system_text
    assert "Hỗ trợ trả góp 0% qua thẻ tín dụng." in system_text
    assert [m.content for m in out["messages"]] == ["Dạ em hiểu ạ."]


async def test_conversation_history_is_passed_through(monkeypatch):
    state = {"messages": [_Human("lịch trùng mất em")], "objection_type": LICH_BAN}
    _, llm = await _run(monkeypatch, state)
    assert any(getattr(m, "type", "") == "human" for m in llm.seen)


async def test_first_pass_increments_the_count(monkeypatch):
    out, _ = await _run(monkeypatch, {"messages": [_Human("mắc quá")],
                                      "objection_type": GIA_CAO})
    assert out["objection_count"] == {GIA_CAO: 1}
    assert "objection_fix_done" not in out


async def test_retry_repairs_without_double_counting(monkeypatch):
    state = {"messages": [_Human("mắc quá")], "objection_type": GIA_CAO,
             "objection_count": {GIA_CAO: 1}, "fix_hint": "hứa hẹn cấm"}
    out, llm = await _run(monkeypatch, state)

    assert "objection_count" not in out            # a bounce is not a new objection
    assert out["objection_fix_done"] is True
    assert out["fix_hint"] == ""
    assert any("chưa đạt" in m.content for m in llm.seen if hasattr(m, "content"))


# ── the branch is NOT exempt from the guard ──────────────────
def test_self_invented_discount_is_blocked_by_the_guard():
    draft = "Dạ khóa Toán 7 Mất Gốc em xin ưu đãi riêng còn 1.500.000đ cho chị ạ"
    verdict = evaluate_draft(draft, [COURSE])
    assert verdict.ok is False
    assert len(verdict.violations) >= 2            # both the price and the concession


def test_quoting_the_real_uu_dai_passes_the_guard():
    draft = "Dạ khóa Toán 7 Mất Gốc học phí 1.800.000đ, đang giảm 10% ạ"
    assert evaluate_draft(draft, [COURSE]).ok is True


def test_objection_branch_has_no_retrieved_and_guard_still_works():
    # The objection branch never retrieves, so `retrieved` is empty. The guard
    # reads the catalog from the KB snapshot, so that must not matter.
    assert evaluate_draft("Dạ khóa Toán 7 Mất Gốc học phí 1.800.000đ ạ", [COURSE]).ok
