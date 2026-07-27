"""ConvState + LeadProfile — the full persisted conversation state.

The checkpointer (AsyncPostgresSaver) persists this ENTIRE dict per thread_id, so
there are NO custom load_memory/save_history nodes — memory is automatic.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class LeadProfile(TypedDict, total=False):
    ten: str | None
    sdt: str | None
    khoa_quan_tam: str | None
    nhu_cau: str | None
    do_nong: str          # "lạnh" | "ấm" | "nóng"
    # Elicitation fields — asked one per turn, only when still empty.
    # Adding a field here is HALF the change: the `capture_lead` @tool schema must
    # gain the same parameter or the LLM has no way to write it (plan review H3).
    lop: str | None
    tinh_trang: str | None
    muc_tieu: str | None
    co_so: str | None
    lich_ranh: str | None
    khung_gio_tien: str | None    # PII-adjacent: same retention/purge as sdt


class ConvState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    user_id: str
    channel: str                 # "messenger" (| "zalo" later)
    retrieved: list              # FAQ/Center hits only, capped: [{text, source, doc_id, course_id}]
    retrieved_this_turn: list    # transient: hits from THIS turn — what grade_chunks scores
    lead_profile: LeadProfile
    sales_stage: str             # SalesStage.* — see graph/sales_stage.py (single source)
    phone_asked_at: float        # epoch seconds the bot last asked for a SĐT (1-ask rule)
    reflect_count: int
    handoff: bool                # ADVISORY — nothing routes on it. The gate that actually
                                 # stops the bot is the handoff_status table.
    escalated: bool              # transient: THIS invoke wrote the handoff row, so the
                                 # dispatcher must still deliver this turn's goodbye
    _lead_error: str             # last Sheet upsert error (declared so the channel exists)
    tool_rounds: int             # agent↔tool loop guard
    route_hint: str              # transient routing signal set by tool_exec / reflect
    grade_sufficient: bool       # transient: Corrective-RAG grade result
    fix_hint: str                # transient: reflect→agent one-shot fix instruction
    objection_type: str          # transient: detect_objection label for THIS turn
    objection_count: dict        # persisted: {objection_type: times handled}
    objection_fix_done: bool     # transient: objection draft already repaired once (C3 guard)
