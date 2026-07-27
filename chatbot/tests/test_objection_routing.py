"""Objection branch: classification, escalation, C3 reflect-bounce destination."""

import app.graph.nodes.detect_objection as detect_mod
from app.graph.nodes.detect_objection import (
    ObjectionResult,
    detect_objection_node,
    escalates,
    route_after_detect,
)
from app.graph.nodes.handle_objection import _bumped_counts
from app.graph.nodes.reflect_node import route_after_reflect
from app.graph.prompts.objection_prompt import (
    GIA_CAO,
    NONE,
    OBJECTION_PLAYBOOK,
    OBJECTION_TYPES,
    SO_SANH_CHO_KHAC,
    build_handle_prompt,
)


class _FakeStructured:
    def __init__(self, result):
        self._result = result

    async def ainvoke(self, prompt):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _FakeLLM:
    def __init__(self, result):
        self._result = result

    def with_structured_output(self, model):
        return _FakeStructured(self._result)


class _Human:
    type = "human"

    def __init__(self, content):
        self.content = content


def _patch_llm(monkeypatch, result):
    monkeypatch.setattr(detect_mod, "lite_llm", lambda: _FakeLLM(result))


# ── classification ───────────────────────────────────────────
async def test_price_complaint_classified(monkeypatch):
    _patch_llm(monkeypatch, ObjectionResult(type=GIA_CAO))
    out = await detect_objection_node({"messages": [_Human("học phí mắc quá em ơi")]})
    assert out["objection_type"] == GIA_CAO
    assert out["escalated"] is False        # cleared, not merely absent
    assert route_after_detect(out) == "handle_objection"


async def test_plain_question_goes_down_the_normal_branch(monkeypatch):
    _patch_llm(monkeypatch, ObjectionResult(type=NONE))
    out = await detect_objection_node({"messages": [_Human("khai giảng khi nào em")]})
    assert route_after_detect(out) == "agent"


async def test_unknown_label_degrades_to_none(monkeypatch):
    _patch_llm(monkeypatch, ObjectionResult(type="bịa_ra"))
    out = await detect_objection_node({"messages": [_Human("gì đó")]})
    assert out["objection_type"] == NONE


async def test_classifier_error_fails_open(monkeypatch):
    # Opposite stance to pricing_guard on purpose: a broken classifier must not
    # block ordinary conversation.
    _patch_llm(monkeypatch, RuntimeError("gemini down"))
    out = await detect_objection_node({"messages": [_Human("học phí mắc quá")]})
    assert out["objection_type"] == NONE
    assert route_after_detect(out) == "agent"


async def test_no_human_message_is_none(monkeypatch):
    _patch_llm(monkeypatch, ObjectionResult(type=GIA_CAO))
    assert (await detect_objection_node({"messages": []}))["objection_type"] == NONE


# ── escalation ───────────────────────────────────────────────
async def test_competitor_comparison_never_generates_a_reply(monkeypatch):
    _patch_llm(monkeypatch, ObjectionResult(type=SO_SANH_CHO_KHAC))
    out = await detect_objection_node({"messages": [_Human("bên kia rẻ hơn")]})
    assert out["handoff"] is True
    assert route_after_detect(out) == "fallback"


async def test_same_objection_twice_escalates(monkeypatch):
    _patch_llm(monkeypatch, ObjectionResult(type=GIA_CAO))
    state = {"messages": [_Human("vẫn mắc quá em")], "objection_count": {GIA_CAO: 1}}
    out = await detect_objection_node(state)
    assert out["handoff"] is True
    assert route_after_detect({**state, **out}) == "fallback"


async def test_escalation_actually_notifies_a_human(monkeypatch):
    """`state["handoff"]` alone is inert — escalation must hit the real gate."""
    import app.graph.tools.lead_tools as lead_tools

    calls = []

    async def _fake_handoff(args, state):
        calls.append(args["reason"])
        return lead_tools.ToolResult("ok", {"handoff": True, "sales_stage": "handoff"})

    monkeypatch.setattr(lead_tools, "run_handoff_to_human", _fake_handoff)
    _patch_llm(monkeypatch, ObjectionResult(type=SO_SANH_CHO_KHAC))

    out = await detect_objection_node({"messages": [_Human("bên kia rẻ hơn")]})
    assert calls and SO_SANH_CHO_KHAC in calls[0]
    assert out["handoff"] is True and out["sales_stage"] == "handoff"


async def test_no_escalation_no_handoff_call(monkeypatch):
    import app.graph.tools.lead_tools as lead_tools

    async def _boom(args, state):                      # pragma: no cover
        raise AssertionError("must not escalate an ordinary objection")

    monkeypatch.setattr(lead_tools, "run_handoff_to_human", _boom)
    _patch_llm(monkeypatch, ObjectionResult(type=GIA_CAO))
    out = await detect_objection_node({"messages": [_Human("mắc quá em")],
                                       "handoff": True, "escalated": True})
    # Stale flags from an earlier turn must be cleared, not inherited.
    assert out["handoff"] is False and out["escalated"] is False


async def test_entry_node_resets_per_turn_counters(monkeypatch):
    """Without this, `tool_rounds` caps the CONVERSATION, not the turn."""
    _patch_llm(monkeypatch, ObjectionResult(type=NONE))
    stale = {"messages": [_Human("khai giảng khi nào")], "tool_rounds": 4,
             "reflect_count": 1, "objection_fix_done": True, "fix_hint": "cũ",
             "route_hint": "fix", "retrieved_this_turn": [{"text": "cũ"}]}
    out = await detect_objection_node(stale)
    assert out["tool_rounds"] == 0
    assert out["reflect_count"] == 0
    assert out["objection_fix_done"] is False
    assert out["fix_hint"] == "" and out["route_hint"] == ""
    assert out["retrieved_this_turn"] == []


async def test_counters_reset_even_without_a_human_message(monkeypatch):
    _patch_llm(monkeypatch, ObjectionResult(type=NONE))
    out = await detect_objection_node({"messages": [], "tool_rounds": 4})
    assert out["tool_rounds"] == 0


def test_objection_count_is_NOT_reset_per_turn():
    # It is the repeat detector — resetting it would make escalation impossible.
    from app.graph.nodes.detect_objection import turn_reset

    assert "objection_count" not in turn_reset()


def test_turn_reset_does_not_share_mutable_state():
    """A module-level literal would hand the SAME list to every concurrent turn."""
    from app.graph.nodes.detect_objection import turn_reset

    first, second = turn_reset(), turn_reset()
    first["retrieved_this_turn"].append({"text": "lượt A"})
    assert second["retrieved_this_turn"] == []


def test_a_different_group_does_not_inherit_the_count():
    assert escalates("suy_nghi", {GIA_CAO: 1}) is False
    assert escalates(GIA_CAO, {GIA_CAO: 1}) is True
    assert escalates(GIA_CAO, None) is False


def test_count_increments_only_for_its_own_group():
    assert _bumped_counts({"objection_count": {GIA_CAO: 1}}, "suy_nghi") \
        == {GIA_CAO: 1, "suy_nghi": 1}


# ── C3: reflect bounce destination ───────────────────────────
def test_ok_draft_always_goes_to_the_guard():
    assert route_after_reflect({"route_hint": "guard", "objection_type": GIA_CAO}) \
        == "pricing_guard"


def test_objection_draft_bounces_back_to_its_own_node():
    # The C3 bug: this used to land on `agent` — tools bound, no group playbook.
    assert route_after_reflect({"route_hint": "fix", "objection_type": GIA_CAO}) \
        == "handle_objection"


def test_objection_repair_happens_at_most_once():
    state = {"route_hint": "fix", "objection_type": GIA_CAO, "objection_fix_done": True}
    assert route_after_reflect(state) == "agent"


def test_normal_draft_still_bounces_to_agent():
    assert route_after_reflect({"route_hint": "fix"}) == "agent"
    assert route_after_reflect({"route_hint": "fix", "objection_type": NONE}) == "agent"


# ── playbook content ─────────────────────────────────────────
def test_price_playbook_forbids_inventing_a_discount():
    body = build_handle_prompt(GIA_CAO, {"Trả góp": "Trả góp 0% qua thẻ"})
    assert "không giảm giá" in body.lower()
    assert "xin sếp" in body
    assert "Trả góp 0% qua thẻ" in body      # quoted verbatim, not paraphrased


def test_price_playbook_without_center_row_still_renders():
    assert build_handle_prompt(GIA_CAO, {})


def test_competitor_group_has_no_generation_playbook():
    assert SO_SANH_CHO_KHAC not in OBJECTION_PLAYBOOK
    assert build_handle_prompt(SO_SANH_CHO_KHAC) == ""
    assert build_handle_prompt(NONE) == ""


def test_every_generating_group_has_do_and_dont():
    generating = set(OBJECTION_TYPES) - {NONE, SO_SANH_CHO_KHAC}
    assert set(OBJECTION_PLAYBOOK) == generating
    for play in OBJECTION_PLAYBOOK.values():
        assert play["lam"] and play["cam"]
