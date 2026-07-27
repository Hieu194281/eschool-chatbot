"""tool_exec node — executes ALL tool_calls in the last AIMessage.

Combines execution + the "post-tool" state-write fix (red-team #2): it applies each
state-mutating tool's `state_update` directly to ConvState channels, so
`handoff`/`sales_stage`/`lead_profile` really flip (no silent no-op). Every
tool_call gets a ToolMessage (else the next LLM call errors on a dangling call).

Routing: if any retrieve_kb ran → route to grade_chunks (Corrective-RAG); else back
to agent.
"""

from __future__ import annotations

from ...common.metrics_logger import emit

# `..tools` pulls in langchain at import time; keeping it function-local (same as
# the rest of the nodes) is what lets the pure merge/cap logic be unit-tested
# without the heavy deps installed.

# `retrieved` is CHECKPOINTED, so an uncapped merge grows without bound across a
# long conversation. The old ~20-course_id key capped it by accident; deduping on
# doc_id (correctly) removes that accident, so cap it on purpose.
MAX_RETRIEVED = 8

# FAQ/Center-only store → more, smaller docs than the old course-centric one.
RETRIEVE_K = 5


def _merge_hits(existing: list[dict], hits: list[dict]) -> list[dict]:
    """Dedupe on `doc_id`, newest occurrence wins, keep the most recent MAX_RETRIEVED.

    NOT on `course_id`: centre-wide FAQ rows all carry `course_id=""`, so that key
    would silently collapse every distinct FAQ hit into one (plan review C1).
    """
    fresh_ids = {h.get("doc_id") for h in hits}
    # Entries with no doc_id are v1 checkpoint leftovers — course chunks carrying
    # v1 prices. Drop them rather than let them ride in the UNTRUSTED block.
    kept = [h for h in existing if h.get("doc_id") and h.get("doc_id") not in fresh_ids]
    return (kept + list(hits))[-MAX_RETRIEVED:]


def _format_hits(hits: list[dict]) -> str:
    if not hits:
        return "Không tìm thấy dữ liệu phù hợp trong kho kiến thức."
    return "\n---\n".join(h.get("text", "") for h in hits)


async def tool_exec_node(state: dict) -> dict:
    from langchain_core.messages import ToolMessage
    from ...kb import knowledge_base
    from ..tools import RETRIEVE_TOOL_NAME, TOOL_IMPLS

    messages = state.get("messages", [])
    last = messages[-1] if messages else None
    tool_calls = getattr(last, "tool_calls", None) or []

    out_messages = []
    update: dict = {}
    retrieved = list(state.get("retrieved") or [])
    this_turn: list[dict] = []
    did_retrieve = False

    for call in tool_calls:
        name = call.get("name", "")
        args = call.get("args", {}) or {}
        call_id = call.get("id", "")

        if name == RETRIEVE_TOOL_NAME:
            did_retrieve = True
            hits = knowledge_base.retrieve(args.get("query", ""), k=RETRIEVE_K)
            this_turn.extend(hits)
            retrieved = _merge_hits(retrieved, hits)
            out_messages.append(ToolMessage(content=_format_hits(hits), tool_call_id=call_id))
        elif name in TOOL_IMPLS:
            result = await TOOL_IMPLS[name](args, {**state, **update})
            out_messages.append(ToolMessage(content=result.message, tool_call_id=call_id))
            update.update(result.state_update)
        else:
            out_messages.append(ToolMessage(content=f"Tool '{name}' không hỗ trợ.", tool_call_id=call_id))

    update["messages"] = out_messages
    update["tool_rounds"] = state.get("tool_rounds", 0) + 1
    emit(event="tools",
         tool_names=[c.get("name", "") for c in tool_calls],
         retrieved_count=len(this_turn))
    if did_retrieve:
        update["retrieved"] = retrieved
        # Graded separately from the accumulated field: grading the accumulation
        # lets last turn's chunks vouch for this turn's question (plan review H1).
        update["retrieved_this_turn"] = this_turn
        update["route_hint"] = "grade"
    else:
        update["route_hint"] = "agent"
    return update


def route_after_tools(state: dict) -> str:
    return "grade_chunks" if state.get("route_hint") == "grade" else "agent"
