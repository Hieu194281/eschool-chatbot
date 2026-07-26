"""`retrieve_kb` tool SCHEMA (for LLM binding).

Scope narrowed in schema v2: the store holds ONLY FAQ + Center rows. Course data
is always present in the system prompt, so calling this for a course question is
both useless and a latency cost — the description says so explicitly, because the
tool description is the only thing the model reads when deciding to call it.

The actual retrieval runs in the tool_exec node (it needs the structured hits to
feed grade_chunks), so this body is only exercised if some path calls it directly.
"""

from langchain_core.tools import tool

RETRIEVE_TOOL_NAME = "retrieve_kb"


@tool
def retrieve_kb(query: str) -> str:
    """Tra cứu câu hỏi thường gặp và thông tin chung của trung tâm (thủ tục nhập học,
    thanh toán, nội quy, chính sách chung, tiện ích, đường đi...).

    KHÔNG dùng tool này cho câu hỏi về khóa học (học phí, ưu đãi, lịch khai giảng,
    lịch học, sĩ số, giáo viên, đối tượng, lộ trình) — những thông tin đó ĐÃ CÓ SẴN
    trong khối [MỤC LỤC KHÓA] / [CHI TIẾT KHÓA] của ngữ cảnh, trả lời trực tiếp."""
    from ...kb import knowledge_base

    hits = knowledge_base.retrieve(query)
    if not hits:
        return "Không tìm thấy dữ liệu phù hợp trong kho kiến thức."
    return "\n---\n".join(h["text"] for h in hits)
