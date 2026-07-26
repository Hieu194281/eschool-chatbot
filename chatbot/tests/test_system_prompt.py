"""build_system_prompt: fixed block order, graceful empty blocks, trust separation."""

from app.graph.prompts import SYSTEM_PROMPT, build_system_prompt


def _injected(prompt):
    """Only the dynamic tail — the static rules also NAME the block headers."""
    assert prompt.startswith(SYSTEM_PROMPT)      # static prefix drives Gemini caching
    return prompt[len(SYSTEM_PROMPT):]


def test_block_order_is_fixed():
    tail = _injected(build_system_prompt(catalog="[MỤC LỤC KHÓA]\nC1 …",
                                         center="Địa chỉ: 12 Lê Lợi",
                                         playbook="Bước 1 …"))
    assert tail.index("[THÔNG TIN TRUNG TÂM]") < tail.index("[MỤC LỤC KHÓA]")
    assert tail.index("[MỤC LỤC KHÓA]") < tail.index("[SALES PLAYBOOK]")


def test_kb_not_ready_still_builds():
    assert build_system_prompt() == SYSTEM_PROMPT


def test_empty_blocks_omitted_not_left_as_empty_headers():
    tail = _injected(build_system_prompt(catalog="[MỤC LỤC KHÓA]\nC1 …"))
    assert "[THÔNG TIN TRUNG TÂM]" not in tail
    assert "[SALES PLAYBOOK]" not in tail


def test_prompt_tells_agent_not_to_retrieve_for_courses():
    # The agent's only signal about scope is this text — assert it stays.
    assert "KHÔNG gọi tool `retrieve_kb` cho câu hỏi về khóa học" in SYSTEM_PROMPT
    assert "UNTRUSTED DATA" in SYSTEM_PROMPT
