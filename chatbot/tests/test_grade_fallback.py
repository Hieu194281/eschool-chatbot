"""Corrective-RAG: insufficient chunks → grade says false → routes to fallback."""

import app.graph.nodes.grade_node as grade_node_mod
from app.graph.nodes.grade_node import (
    GradeResult, _grade_chunks, grade_node, route_after_grade,
)


def test_route_after_grade_pure():
    assert route_after_grade({"grade_sufficient": True}) == "agent"
    assert route_after_grade({"grade_sufficient": False}) == "fallback"


def test_grade_chunks_include_pricing():
    # Bug: pricing is never embedded, so the grader must be handed it alongside the
    # description — else a priced question is wrongly judged 'insufficient'.
    chunks = _grade_chunks([{"text": "Khóa IELTS mô tả", "pricing": "Học phí: 8.900.000"}])
    assert "8.900.000" in chunks[0]
    assert "Khóa IELTS mô tả" in chunks[0]


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
    out = await grade_node({"messages": [], "retrieved": [{"text": "thông tin không liên quan"}]})
    assert out["grade_sufficient"] is False
    assert route_after_grade(out) == "fallback"


async def test_sufficient_context_routes_agent(monkeypatch):
    monkeypatch.setattr(grade_node_mod, "lite_llm",
                        lambda: _FakeLLM(GradeResult(sufficient=True, reason="ok")))
    out = await grade_node({"messages": [], "retrieved": [{"text": "học phí 5tr"}]})
    assert route_after_grade(out) == "agent"
