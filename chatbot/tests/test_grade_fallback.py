"""Corrective-RAG: insufficient chunks → grade says false → routes to fallback."""

import app.graph.nodes.grade_node as grade_node_mod
from app.graph.nodes.grade_node import GradeResult, grade_node, route_after_grade


def test_route_after_grade_pure():
    assert route_after_grade({"grade_sufficient": True}) == "agent"
    assert route_after_grade({"grade_sufficient": False}) == "fallback"


class _FakeStructured:
    def __init__(self, result):
        self._result = result

    async def ainvoke(self, prompt):
        return self._result


class _FakeLLM:
    def __init__(self, result):
        self._result = result

    def with_structured_output(self, model):
        return _FakeStructured(self._result)


async def test_insufficient_context_routes_fallback(monkeypatch):
    monkeypatch.setattr(grade_node_mod, "lite_llm",
                        lambda: _FakeLLM(GradeResult(sufficient=False, reason="no pricing")))
    out = await grade_node({"messages": [],
                            "retrieved_this_turn": [{"text": "thông tin không liên quan"}]})
    assert out["grade_sufficient"] is False
    assert route_after_grade(out) == "fallback"


async def test_sufficient_context_routes_agent(monkeypatch):
    monkeypatch.setattr(grade_node_mod, "lite_llm",
                        lambda: _FakeLLM(GradeResult(sufficient=True, reason="ok")))
    out = await grade_node({"messages": [], "retrieved_this_turn": [{"text": "học phí 5tr"}]})
    assert route_after_grade(out) == "agent"


async def test_stale_chunks_cannot_vouch_for_this_turn(monkeypatch):
    """H1: last turn's chunks sit in `retrieved` but must not be graded."""
    monkeypatch.setattr(grade_node_mod, "lite_llm",
                        lambda: _FakeLLM(GradeResult(sufficient=True, reason="stale hit")))
    out = await grade_node({"messages": [],
                            "retrieved": [{"text": "chunk lượt trước"}],
                            "retrieved_this_turn": []})
    assert out["grade_sufficient"] is False        # no LLM call, no false "sufficient"
    assert route_after_grade(out) == "fallback"
