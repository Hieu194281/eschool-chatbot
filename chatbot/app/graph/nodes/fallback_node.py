"""fallback node — Corrective-RAG honest fallback (insufficient KB or loop cap).

Appends the canned honest line, flips the advisory handoff flag, then flows to
reflect_lite (cheap tone check on the canned line).

It does NOT set `sales_stage=HANDOFF`. That stage is absorbing, and a
corrective-RAG miss is routine — one of them would otherwise permanently kill
elicitation and tell every later prompt a human had taken over while the bot kept
answering. "We could not answer THIS turn" and "a human owns this thread" are
different facts; only the latter moves the stage.
"""

from ..prompts import HONEST_FALLBACK


def fallback_node(state: dict) -> dict:
    from langchain_core.messages import AIMessage

    return {"messages": [AIMessage(content=HONEST_FALLBACK)], "handoff": True}
