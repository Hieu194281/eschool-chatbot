"""detect_objection — graph ENTRY node. Flash-Lite classifier, fail-OPEN.

Runs on every inbound message (~+400ms). Accepted: the objection branch it enables
is SHORTER than the normal one (no retrieve, no grade, no second agent turn), so
conversations that need it get faster, not slower.

Fail-OPEN is the opposite of the pricing_guard's stance, deliberately: a classifier
that errors closed would block ordinary conversation, while a missed objection just
means the normal branch answers the question — which it does correctly anyway.

Escalation is decided HERE (and mirrored by the pure router) so the same predicate
drives both the `handoff` write and the edge choice. Two rules escalate:
- `so_sanh_cho_khac` — never generate a reply about a competitor.
- the same objection group a second time — a bot arguing in circles about price
  loses the lead and the goodwill; a human can still save it.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from ...common.metrics_logger import emit
from ...llm import lite_llm, with_retry
from ..prompts.objection_prompt import (
    NONE,
    OBJECTION_TYPES,
    SO_SANH_CHO_KHAC,
    build_detect_prompt,
)

logger = logging.getLogger(__name__)

# Second occurrence of a group escalates, so one prior generation is the trigger.
_REPEAT_LIMIT = 1

# Per-TURN counters. They live in a checkpointed dict, so without an explicit
# reset they accumulate for the life of the conversation: `tool_rounds` would trip
# its cap of 4 after four tool calls TOTAL and route every later turn straight to
# fallback, and `reflect_count`/`objection_fix_done` would spend their one repair
# on turn 1 and never allow another. Being the entry node, this is the one place
# that runs exactly once per turn.
_TURN_RESET_FIELDS = ("tool_rounds", "reflect_count", "objection_fix_done",
                      "fix_hint", "route_hint", "retrieved_this_turn")


def turn_reset() -> dict:
    """Fresh dict every call — a module-level literal would hand the SAME list
    object to every concurrent thread's `retrieved_this_turn`.

    `handoff`/`escalated` are cleared here too: they describe THIS turn. Left
    sticky, one routine honest-fallback would mark every later turn as escalated
    and the dispatcher would stop yielding to a human who takes over mid-invoke.
    """
    return {"tool_rounds": 0, "reflect_count": 0, "objection_fix_done": False,
            "fix_hint": "", "route_hint": "", "retrieved_this_turn": [],
            "handoff": False, "escalated": False}


class ObjectionResult(BaseModel):
    type: str = Field(description=f"Một trong: {', '.join(OBJECTION_TYPES)}")
    confidence: float = Field(default=1.0, description="Độ tự tin 0..1")


def _last_human_text(state: dict) -> str:
    for msg in reversed(state.get("messages", [])):
        if getattr(msg, "type", None) == "human":
            content = getattr(msg, "content", "")
            return content if isinstance(content, str) else str(content)
    return ""


def escalates(objection_type: str, counts: dict) -> bool:
    """Should this objection go straight to a human instead of a generated reply?"""
    if objection_type == SO_SANH_CHO_KHAC:
        return True
    return (counts or {}).get(objection_type, 0) >= _REPEAT_LIMIT


async def detect_objection_node(state: dict) -> dict:
    question = _last_human_text(state)
    if not question:
        return {"objection_type": NONE, **turn_reset()}

    try:
        llm = lite_llm().with_structured_output(ObjectionResult)
        result = await with_retry(lambda: llm.ainvoke(build_detect_prompt(question)))
        objection_type = result.type if result.type in OBJECTION_TYPES else NONE
    except Exception:
        logger.warning("detect_objection failed — treating as 'none'", exc_info=True)
        objection_type = NONE

    update = {"objection_type": objection_type, **turn_reset()}
    escalated = objection_type != NONE and escalates(objection_type,
                                                     state.get("objection_count"))
    if escalated:
        update.update(await _escalate(state, objection_type))
    emit(event="objection", objection_type=objection_type, escalated=escalated)
    return update


async def _escalate(state: dict, objection_type: str) -> dict:
    """Hand the thread to a real person — for real.

    Writes the handoff table AND fires Telegram, so "a human can still save it"
    is true rather than aspirational.

    The customer still receives this turn's honest-fallback line: the dispatcher
    skips its mid-invoke handoff check when the graph itself raised the flag
    (see `message_dispatcher._handle`). Without that, paging a human would also
    swallow the bot's own goodbye and the customer would just get silence.
    """
    from ..tools.lead_tools import run_handoff_to_human

    reason = f"khách phản đối nhóm '{objection_type}' — cần tư vấn viên"
    result = await run_handoff_to_human({"reason": reason}, state)
    return result.state_update


def route_after_detect(state: dict) -> str:
    objection_type = state.get("objection_type") or NONE
    if objection_type == NONE:
        return "agent"
    if escalates(objection_type, state.get("objection_count")):
        return "fallback"
    return "handle_objection"
