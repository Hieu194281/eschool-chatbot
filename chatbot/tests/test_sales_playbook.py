"""Sales playbook rendering + the LeadProfile↔@tool schema contract (H3)."""

from app.graph.prompts.sales_playbook import (
    ELICITATION,
    SALES_FORBIDDEN,
    STAGE_ACTIONS,
    next_elicitation,
    phone_reason,
    render_playbook,
)
from app.graph.sales_stage import ALL_STAGES, SalesStage

VERBATIM = {
    "Test đầu vào": "Test đầu vào miễn phí tại trung tâm, 30 phút.",
    "Cam kết gọi lại": "Tư vấn viên liên hệ trong giờ hành chính.",
    "Trả góp": "Hỗ trợ trả góp 0% qua thẻ.",
}


# ── elicitation ──────────────────────────────────────────────
def test_first_question_on_an_empty_profile():
    assert next_elicitation({})[0] == "lop"


def test_known_fields_are_skipped():
    assert next_elicitation({"lop": "7"})[0] == "tinh_trang"
    assert next_elicitation({"lop": "7", "tinh_trang": "yếu"})[0] == "muc_tieu"


def test_complete_profile_has_nothing_left_to_ask():
    full = {field: "x" for field, _ in ELICITATION}
    assert next_elicitation(full) is None


def test_none_profile_is_safe():
    assert next_elicitation(None)[0] == "lop"


# ── rendering ────────────────────────────────────────────────
def test_only_the_current_stage_action_is_injected():
    body = render_playbook({"sales_stage": SalesStage.MOI}, VERBATIM)
    assert STAGE_ACTIONS[SalesStage.MOI] in body
    assert STAGE_ACTIONS[SalesStage.DA_BAO_GIA] not in body
    assert STAGE_ACTIONS[SalesStage.CO_SDT] not in body


def test_every_stage_renders():
    for stage in ALL_STAGES:
        assert render_playbook({"sales_stage": stage}, VERBATIM)


def test_legacy_stage_value_still_renders():
    body = render_playbook({"sales_stage": "đã xin SĐT"}, VERBATIM)
    assert STAGE_ACTIONS[SalesStage.CO_SDT] in body


def test_known_fields_listed_so_bot_stops_re_asking():
    body = render_playbook({"sales_stage": SalesStage.MOI,
                            "lead_profile": {"lop": "7"}}, VERBATIM)
    assert "lop=7" in body
    assert next_elicitation({"lop": "7"})[1] in body


def test_no_elicitation_after_the_deal_is_booked():
    body = render_playbook({"sales_stage": SalesStage.DA_HEN_LICH,
                            "lead_profile": {}}, VERBATIM)
    assert ELICITATION[0][1] not in body
    assert "NGỪNG chào bán" in body


def test_forbidden_table_always_present():
    body = render_playbook({}, VERBATIM)
    for rule in SALES_FORBIDDEN:
        assert rule in body


def test_empty_state_does_not_crash():
    assert render_playbook({}, None)
    assert render_playbook(None, None)


# ── phone-ask reason ─────────────────────────────────────────
def test_reason_shown_only_at_da_bao_gia():
    quoted = render_playbook({"sales_stage": SalesStage.DA_BAO_GIA}, VERBATIM)
    early = render_playbook({"sales_stage": SalesStage.MOI}, VERBATIM)
    assert "Cớ xin SĐT" in quoted
    assert "Cớ xin SĐT" not in early


def test_no_reason_once_we_already_have_the_number():
    body = render_playbook({"sales_stage": SalesStage.DA_BAO_GIA,
                            "lead_profile": {"sdt": "0912345678"}}, VERBATIM)
    assert "Cớ xin SĐT" not in body


def test_weak_student_signal_picks_the_entry_test_reason():
    reason = phone_reason({"tinh_trang": "bé mất gốc từ lớp 6"}, VERBATIM)
    assert VERBATIM["Test đầu vào"] in reason


def test_free_slot_signal_picks_the_trial_hold_reason():
    reason = phone_reason({"tinh_trang": "khá", "lich_ranh": "tối T3, T5"}, VERBATIM)
    assert "giữ chỗ" in reason


def test_reason_quotes_center_verbatim_not_an_invented_promise():
    reason = phone_reason({}, VERBATIM)
    assert VERBATIM["Cam kết gọi lại"] in reason


def test_missing_center_rows_degrade_to_the_dataless_reason():
    reason = phone_reason({"tinh_trang": "mất gốc"}, {})
    assert "Zalo" in reason


# ── H3: LeadProfile ↔ @tool schema must not drift ────────────
def test_tool_schema_exposes_every_elicitation_field():
    from app.graph.tools.lead_tools import PROFILE_FIELDS, capture_lead

    schema_params = set(capture_lead.args.keys())
    assert set(PROFILE_FIELDS) <= schema_params, (
        "a LeadProfile field the LLM cannot write makes elicitation decorative"
    )
    assert {field for field, _ in ELICITATION} <= schema_params
    assert "khung_gio_tien" in schema_params
