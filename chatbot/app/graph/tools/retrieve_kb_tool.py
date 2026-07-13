"""`retrieve_kb` tool SCHEMA (for LLM binding).

The actual retrieval runs in the tool_exec node (it needs the structured hits to
build `pricing_context` and feed grade_chunks), so this body is only exercised if
some path calls it directly — it still returns a useful string.
"""

from langchain_core.tools import tool

RETRIEVE_TOOL_NAME = "retrieve_kb"


@tool
def retrieve_kb(query: str) -> str:
    """Tra cứu kho kiến thức khóa học của trung tâm (đối tượng, mục tiêu, lộ trình,
    lịch khai giảng, giáo viên, FAQ, chính sách, học phí/ưu đãi). Dùng tool này TRƯỚC
    khi trả lời bất kỳ câu hỏi nào về khóa học/học phí/lịch."""
    from ...kb import knowledge_base

    hits = knowledge_base.retrieve(query, k=3)
    if not hits:
        return "Không tìm thấy dữ liệu phù hợp trong kho kiến thức."
    return "\n---\n".join(h["text"] for h in hits)
