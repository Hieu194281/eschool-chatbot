"""Corrective-RAG grade prompt (Flash-Lite sufficiency classifier)."""


def build_grade_prompt(question: str, chunks: list[str]) -> str:
    joined = "\n---\n".join(chunks) if chunks else "(không có dữ liệu)"
    return (
        "Bạn là bộ phân loại. Nhiệm vụ: quyết định NGỮ CẢNH dưới đây có ĐỦ thông tin để "
        "trả lời chính xác CÂU HỎI của khách hay không.\n"
        "- 'đủ' (sufficient=true) nếu ngữ cảnh chứa thông tin trực tiếp trả lời được câu hỏi.\n"
        "- 'thiếu' (sufficient=false) nếu ngữ cảnh không liên quan / thiếu dữ kiện cần thiết "
        "(đặc biệt là học phí/lịch mà ngữ cảnh không nêu).\n\n"
        f"CÂU HỎI:\n{question}\n\n"
        f"NGỮ CẢNH:\n{joined}\n"
    )
