"""reflect_lite node — forbidden-promise / tone ONLY (numbers → pricing_guard).

Order: (1) deterministic blocklist for known promise phrases; (2) Flash-Lite for
paraphrases. On a violation, try a local fix (LLM `fixed_reply` or strip); if none,
bounce to the agent ONCE (reflect_count guard); on give-up, send the honest line.
Never loops.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...llm import lite_llm, with_retry
from ..prompts import HONEST_FALLBACK
from ..prompts.reflect_prompt import blocklist_hit, build_reflect_prompt, strip_blocklist


class ReflectResult(BaseModel):
    ok: bool = Field(description="Câu trả lời có ổn (không hứa hẹn cấm, giọng phù hợp) không")
    issues: list[str] = Field(default_factory=list)
    fixed_reply: str | None = Field(default=None, description="Bản sửa nếu ok=false")


def _last_ai(state: dict):
    from langchain_core.messages import AIMessage

    return next((m for m in reversed(state.get("messages", [])) if isinstance(m, AIMessage)), None)


async def reflect_node(state: dict) -> dict:
    from langchain_core.messages import AIMessage

    last_ai = _last_ai(state)
    if last_ai is None or not getattr(last_ai, "content", None):
        return {"route_hint": "guard"}
    draft = last_ai.content if isinstance(last_ai.content, str) else str(last_ai.content)

    hit = blocklist_hit(draft)
    if hit:
        ok, issues, fixed = False, [f"hứa hẹn cấm: '{hit}'"], strip_blocklist(draft)
    else:
        llm = lite_llm().with_structured_output(ReflectResult)
        result = await with_retry(lambda: llm.ainvoke(build_reflect_prompt(draft)))
        ok, issues, fixed = bool(result.ok), list(result.issues or []), result.fixed_reply

    if ok:
        return {"route_hint": "guard"}

    if fixed and fixed.strip() and fixed.strip() != draft.strip():
        return {"messages": [AIMessage(content=fixed.strip(), id=last_ai.id)], "route_hint": "guard"}

    if state.get("reflect_count", 0) == 0:
        return {
            "reflect_count": 1,
            "route_hint": "fix",
            "fix_hint": "; ".join(issues) or "câu có hứa hẹn/giọng điệu chưa phù hợp",
        }

    # give up safely — never send an unfixed forbidden promise
    return {"messages": [AIMessage(content=HONEST_FALLBACK, id=last_ai.id)],
            "route_hint": "guard", "handoff": True}


def route_after_reflect(state: dict) -> str:
    return "agent" if state.get("route_hint") == "fix" else "pricing_guard"
