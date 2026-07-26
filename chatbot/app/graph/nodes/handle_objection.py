"""handle_objection — Flash, playbook-constrained, NO tools bound.

No tools because the whole catalog (prose + verbatim facts) is already in the
system prompt: `lich_ban` can propose another slot and `gia_cao` can quote the
instalment line without a single retrieval round-trip. That is what makes this
branch shorter than the normal one.

It still exits through `reflect_lite → pricing_guard` like every other draft. This
is the node most likely to invent a discount, so it gets LESS latitude than the
agent, not a shortcut around the gate.

`objection_count` is incremented only on the FIRST generation for a turn. Counting
a reflect-bounce retry too would make one objection look like two and trip the
repeat-escalation on the spot.
"""

from __future__ import annotations

from ...llm import main_llm, with_retry
from ..prompts import build_system_prompt
from ..prompts.objection_prompt import NONE, build_handle_prompt
from ..prompts.sales_playbook import render_playbook


def _bumped_counts(state: dict, objection_type: str) -> dict:
    counts = dict(state.get("objection_count") or {})
    counts[objection_type] = counts.get(objection_type, 0) + 1
    return counts


async def handle_objection_node(state: dict) -> dict:
    from langchain_core.messages import SystemMessage

    from ...kb import knowledge_base

    objection_type = state.get("objection_type") or NONE
    verbatim = knowledge_base.get_verbatim_map()
    is_retry = bool(state.get("fix_hint"))

    msgs = [SystemMessage(content=build_system_prompt(
        catalog=knowledge_base.get_catalog_text(),
        center=knowledge_base.get_center_always(),
        playbook=render_playbook(state, verbatim),
    ))]
    instruction = build_handle_prompt(objection_type, verbatim)
    if instruction:
        msgs.append(SystemMessage(content=instruction))
    if is_retry:
        msgs.append(SystemMessage(
            content=f"Bản trước chưa đạt ({state['fix_hint']}). Viết lại, "
                    f"bỏ hẳn phần vi phạm, vẫn bám đúng kịch bản trên."
        ))
    msgs.extend(state.get("messages", []))

    ai = await with_retry(lambda: main_llm().ainvoke(msgs))     # no bind_tools

    update = {"messages": [ai], "fix_hint": ""}
    if is_retry:
        update["objection_fix_done"] = True      # one repair, then reflect gives up
    else:
        update["objection_count"] = _bumped_counts(state, objection_type)
    return update
