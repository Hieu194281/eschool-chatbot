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


class ConvState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    user_id: str
    channel: str                 # "messenger" (| "zalo" later)
    retrieved: list              # [{text, course_id, ten_khoa, pricing}]
    pricing_context: str         # verbatim official pricing block for this turn
    lead_profile: LeadProfile
    sales_stage: str             # mới | đang tư vấn | đã xin SĐT | đã chốt | cần người
    reflect_count: int
    handoff: bool                # ADVISORY (authoritative gate = handoff_status table)
    tool_rounds: int             # agent↔tool loop guard
    route_hint: str              # transient routing signal set by tool_exec / reflect
    grade_sufficient: bool       # transient: Corrective-RAG grade result
    fix_hint: str                # transient: reflect→agent one-shot fix instruction
