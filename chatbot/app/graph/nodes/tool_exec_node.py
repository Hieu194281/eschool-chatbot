"""tool_exec node — executes ALL tool_calls in the last AIMessage.

Combines execution + the "post-tool" state-write fix (red-team #2): it applies each
state-mutating tool's `state_update` directly to ConvState channels, so
`handoff`/`sales_stage`/`lead_profile` really flip (no silent no-op). Every
tool_call gets a ToolMessage (else the next LLM call errors on a dangling call).

Routing: if any retrieve_kb ran → route to grade_chunks (Corrective-RAG); else back
to agent.
"""

from __future__ import annotations

from ..tools import RETRIEVE_K, RETRIEVE_TOOL_NAME, TOOL_IMPLS


def _merge_hits(existing: list[dict], hits: list[dict]) -> list[dict]:
    seen = {h.get("course_id") for h in existing}
    merged = list(existing)
    for h in hits:
        if h.get("course_id") not in seen:
            merged.append(h)
            seen.add(h.get("course_id"))
    return merged


def _format_hits(hits: list[dict]) -> str:
    if not hits:
        return "Không tìm thấy dữ liệu phù hợp trong kho kiến thức."
    return "\n---\n".join(h.get("text", "") for h in hits)


def _pricing_context(retrieved: list[dict]) -> str:
    lines = [
        f"Khóa {h.get('ten_khoa', '')} (id={h.get('course_id', '')}): {h.get('pricing', '')}"
        for h in retrieved
        if h.get("pricing")
    ]
    return "\n".join(lines)


async def tool_exec_node(state: dict) -> dict:
    from langchain_core.messages import ToolMessage
    from ...kb import knowledge_base

    messages = state.get("messages", [])
    last = messages[-1] if messages else None
    tool_calls = getattr(last, "tool_calls", None) or []

    out_messages = []
    update: dict = {}
    retrieved = list(state.get("retrieved") or [])
    did_retrieve = False

    for call in tool_calls:
        name = call.get("name", "")
        args = call.get("args", {}) or {}
        call_id = call.get("id", "")

        if name == RETRIEVE_TOOL_NAME:
            did_retrieve = True
            hits = knowledge_base.retrieve(args.get("query", ""), k=RETRIEVE_K)
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
    if did_retrieve:
        update["retrieved"] = retrieved
        update["pricing_context"] = _pricing_context(retrieved)
        update["route_hint"] = "grade"
    else:
        update["route_hint"] = "agent"
    return update


def route_after_tools(state: dict) -> str:
    return "grade_chunks" if state.get("route_hint") == "grade" else "agent"
