"""fallback node — Corrective-RAG honest fallback (insufficient KB or loop cap).

Appends the canned honest line, flips advisory handoff + sales_stage, then flows to
reflect_lite (cheap tone check on the canned line).
"""

from ..prompts import HONEST_FALLBACK


def fallback_node(state: dict) -> dict:
    from langchain_core.messages import AIMessage

    return {
        "messages": [AIMessage(content=HONEST_FALLBACK)],
        "handoff": True,
        "sales_stage": "cần người",
    }
