"""reflect_lite node — forbidden-promise / tone ONLY (numbers → pricing_guard).

Order: (1) deterministic blocklist for known promise phrases; (2) Flash-Lite for
paraphrases. On a violation, try a local fix (LLM `fixed_reply` or strip); if none,
bounce to the agent ONCE (reflect_count guard); on give-up, send the honest line.
Never loops.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...common.metrics_logger import emit
from ...llm import lite_llm, with_retry
from ..prompts import HONEST_FALLBACK
from ..prompts.reflect_prompt import blocklist_hit, build_reflect_prompt, strip_blocklist
from .phone_ask_gate import should_suppress, strip_phone_ask, wants_phone


class ReflectResult(BaseModel):
    ok: bool = Field(description="Câu trả lời có ổn (không hứa hẹn cấm, giọng phù hợp) không")
    issues: list[str] = Field(default_factory=list)
    fixed_reply: str | None = Field(default=None, description="Bản sửa nếu ok=false")


def _last_ai(state: dict):
    from langchain_core.messages import AIMessage

    return next((m for m in reversed(state.get("messages", [])) if isinstance(m, AIMessage)), None)


NEUTRAL_CONTINUATION = (
    "Dạ anh/chị cứ nhắn cho em nếu cần thêm thông tin gì về khóa học nhé ạ! 🌸"
)


def _apply_phone_gate(state: dict, draft: str) -> tuple[str, dict]:
    """Enforce the one-ask rule, and stamp the clock when an ask does go out.

    Runs AFTER the promise blocklist. Applied first, a stripped phone-ask used to
    short-circuit the whole node, so a draft carrying both a repeat ask and
    "cam kết đậu" shipped the forbidden promise — pricing_guard only checks numbers.
    """
    import time

    if not wants_phone(draft):
        return draft, {}
    now = time.time()
    if not should_suppress(state, now):
        emit(event="phone_ask", phone_asked=True, phone_suppressed=False)
        return draft, {"phone_asked_at": now}

    # `phone_suppressed` should trend to ~0: every hit is a turn where the model
    # tried to nag a customer who already declined.
    emit(event="phone_ask", phone_asked=False, phone_suppressed=True)
    stripped = strip_phone_ask(draft)
    # If the ask WAS the whole reply, re-sending it would defeat the rule exactly
    # where it matters most — send a neutral line instead.
    return (stripped or NEUTRAL_CONTINUATION), {}


def _result(state: dict, last_ai, text: str, raw: str, extra: dict) -> dict:
    """Apply the phone gate to the outgoing text and emit the right message update."""
    from langchain_core.messages import AIMessage

    gated, phone_update = _apply_phone_gate(state, text)
    update = {**extra, **phone_update}
    if gated != raw:
        update["messages"] = [AIMessage(content=gated, id=last_ai.id)]
    return update


async def reflect_node(state: dict) -> dict:
    last_ai = _last_ai(state)
    if last_ai is None or not getattr(last_ai, "content", None):
        return {"route_hint": "guard"}
    raw = last_ai.content if isinstance(last_ai.content, str) else str(last_ai.content)
    draft = raw

    hit = blocklist_hit(draft)
    if hit:
        ok, issues, fixed = False, [f"hứa hẹn cấm: '{hit}'"], strip_blocklist(draft)
    else:
        llm = lite_llm().with_structured_output(ReflectResult)
        result = await with_retry(lambda: llm.ainvoke(build_reflect_prompt(draft)))
        ok, issues, fixed = bool(result.ok), list(result.issues or []), result.fixed_reply

    if ok:
        return _result(state, last_ai, draft, raw, {"route_hint": "guard"})

    if fixed and fixed.strip() and fixed.strip() != draft.strip():
        return _result(state, last_ai, fixed.strip(), raw, {"route_hint": "guard"})

    if state.get("reflect_count", 0) == 0:
        # Bounced back for a rewrite — nothing was sent, so no phone-ask stamp.
        return {
            "reflect_count": 1,
            "route_hint": "fix",
            "fix_hint": "; ".join(issues) or "câu có hứa hẹn/giọng điệu chưa phù hợp",
        }

    # Give up safely — never send an unfixed forbidden promise. Routed through
    # `_result` so the canned line's own phone ask is gated and stamped like any
    # other: it is a real ask to the customer, and skipping it here let the bot
    # nag on consecutive turns.
    return _result(state, last_ai, HONEST_FALLBACK, raw,
                   {"route_hint": "guard", "handoff": True})


def route_after_reflect(state: dict) -> str:
    """Three destinations, not two (plan review C3).

    Bouncing an objection draft to `agent` sends it to a node that has tools bound
    and NO group playbook — the retry answers off-script while `objection_count`
    has already been spent. It has to go back to `handle_objection`, and only once
    (`objection_fix_done`), or the two nodes ping-pong.
    """
    from ..prompts.objection_prompt import NONE

    if state.get("route_hint") != "fix":
        return "pricing_guard"
    objection_type = state.get("objection_type") or NONE
    if objection_type != NONE and not state.get("objection_fix_done"):
        return "handle_objection"
    return "agent"
