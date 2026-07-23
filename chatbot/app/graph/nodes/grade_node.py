"""grade_chunks node — Corrective-RAG sufficiency classifier (Flash-Lite)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...llm import lite_llm, with_retry
from ..prompts.grade_prompt import build_grade_prompt


class GradeResult(BaseModel):
    sufficient: bool = Field(description="Ngữ cảnh có đủ để trả lời câu hỏi không")
    reason: str = Field(default="", description="Lý do ngắn gọn")


def _last_human_text(state: dict) -> str:
    # Duck-type on `.type == "human"` (LangChain HumanMessage) to avoid importing
    # langchain here — keeps grade_node unit-testable with lightweight fakes.
    for msg in reversed(state.get("messages", [])):
        if getattr(msg, "type", None) == "human":
            content = getattr(msg, "content", "")
            return content if isinstance(content, str) else str(content)
    return ""


def _grade_chunks(retrieved: list[dict]) -> list[str]:
    """Grade context = mô tả (đã embed) + giá verbatim của khóa đó.

    Giá KHÔNG bao giờ được embed cho RAG (golden rule), nhưng bộ phân loại đủ/thiếu
    BẮT BUỘC phải thấy giá — nếu không, câu hỏi học phí bị chấm 'thiếu' oan rồi
    rẽ sang fallback (bot né dù giá đã có sẵn trong hit).
    """
    chunks = []
    for h in retrieved or []:
        text = h.get("text", "")
        pricing = h.get("pricing", "")
        chunks.append(f"{text}\n{pricing}".strip() if pricing else text)
    return chunks


async def grade_node(state: dict) -> dict:
    question = _last_human_text(state)
    chunks = _grade_chunks(state.get("retrieved") or [])
    llm = lite_llm().with_structured_output(GradeResult)
    result = await with_retry(lambda: llm.ainvoke(build_grade_prompt(question, chunks)))
    return {"grade_sufficient": bool(result.sufficient)}


def route_after_grade(state: dict) -> str:
    return "agent" if state.get("grade_sufficient") else "fallback"
