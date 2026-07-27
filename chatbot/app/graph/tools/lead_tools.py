"""State-mutating tools: schemas for the LLM + impl functions for tool_exec.

Ph03: impl bodies are STUBS that still write the correct ConvState channels (so
`handoff`/`sales_stage`/`lead_profile` actually flip — red-team #2). Ph05 replaces
the bodies with real Sheet/Telegram/handoff-table calls, keeping this same
`ToolResult(message, state_update)` contract.

Impls are async so Ph05 can await network I/O without changing the tool_exec node.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from langchain_core.tools import tool

from ...common.metrics_logger import emit
from ..sales_stage import SalesStage, derive_stage

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    message: str                              # ToolMessage content the agent reads
    state_update: dict = field(default_factory=dict)   # ConvState channels to write


# ── LLM-facing schemas (bind_tools) ──────────────────────────
@tool
def capture_lead(
    ten: str | None = None,
    sdt: str | None = None,
    khoa_quan_tam: str | None = None,
    nhu_cau: str | None = None,
    do_nong: str = "ấm",
    lop: str | None = None,
    tinh_trang: str | None = None,
    muc_tieu: str | None = None,
    co_so: str | None = None,
    lich_ranh: str | None = None,
    khung_gio_tien: str | None = None,
) -> str:
    """Lưu thông tin lead vào hệ thống. Gọi NGAY khi khách tiết lộ bất kỳ thông tin
    nào dưới đây — không cần đợi có đủ số điện thoại.

    - ten, sdt: tên và số điện thoại
    - khoa_quan_tam, nhu_cau: khóa đang quan tâm, nhu cầu chính
    - do_nong: "lạnh" | "ấm" | "nóng"
    - lop: bé đang học lớp mấy
    - tinh_trang: lực học hiện tại của bé
    - muc_tieu: mong muốn sau khóa học
    - co_so: cơ sở khách tiện đi
    - lich_ranh: buổi/ngày bé rảnh học
    - khung_gio_tien: khung giờ khách tiện nghe tư vấn viên gọi"""
    return "Đã lưu thông tin khách."


# Every LeadProfile field the LLM can write. Kept next to the @tool schema on
# purpose: adding a field to one and not the other silently disables elicitation
# (plan review H3).
PROFILE_FIELDS = (
    "ten", "sdt", "khoa_quan_tam", "nhu_cau", "do_nong",
    "lop", "tinh_trang", "muc_tieu", "co_so", "lich_ranh", "khung_gio_tien",
)


@tool
def book_trial(sdt: str, slot: str, khoa: str) -> str:
    """Đặt lịch học thử cho khách: số điện thoại, thời gian (slot), tên khóa."""
    return "Đã đặt lịch học thử."


@tool
def handoff_to_human(reason: str) -> str:
    """Chuyển cuộc trò chuyện cho tư vấn viên người thật. Gọi khi khách đòi gặp người,
    khiếu nại, hỏi ngoài phạm vi KB, hoặc lead nóng cần chốt tay."""
    return "Đã chuyển tư vấn viên."


# ── Impl functions executed by tool_exec (Ph05 real bodies) ──────────────────
def _thread_id(state: dict) -> str:
    return f"{state.get('channel', 'messenger')}:{state.get('user_id', '')}"


async def run_capture_lead(args: dict, state: dict) -> ToolResult:
    from datetime import datetime, timezone

    from ...integrations import telegram_notify
    from ...integrations.lead_sheet import get_lead_sheet

    profile = dict(state.get("lead_profile") or {})
    for key in PROFILE_FIELDS:
        if args.get(key):
            profile[key] = args[key]
    stage = derive_stage(profile, state.get("sales_stage"))
    channel_user_id = _thread_id(state)

    # PII/PDPD: consent recorded at capture (bot gives privacy notice before asking SĐT).
    lead = {
        "channel_user_id": channel_user_id,
        **{key: profile.get(key) for key in PROFILE_FIELDS if key != "do_nong"},
        "do_nong": profile.get("do_nong", "ấm"),
        "sales_stage": stage,
        "chat_link": channel_user_id,
        "consent": "yes" if profile.get("sdt") else "",
        "consent_at": datetime.now(timezone.utc).isoformat() if profile.get("sdt") else "",
    }
    # Presence only — the number itself never reaches the metrics log.
    emit(event="lead", stage=stage, has_phone=bool(profile.get("sdt")))
    try:
        await get_lead_sheet().upsert_lead(lead)
        if profile.get("do_nong") == "nóng":
            await telegram_notify.notify(telegram_notify.format_hot_lead(lead))
    except Exception as exc:  # non-fatal: never break the reply over a Sheet hiccup
        return ToolResult(
            "Dạ em đã ghi nhận thông tin của mình ạ.",
            {"lead_profile": profile, "sales_stage": stage, "_lead_error": str(exc)},
        )
    return ToolResult(
        "Dạ em đã lưu thông tin của mình rồi ạ.",
        {"lead_profile": profile, "sales_stage": stage},
    )


async def run_book_trial(args: dict, state: dict) -> ToolResult:
    from ...integrations.trial_sheet import get_trial_sheet

    trial = {
        "channel_user_id": _thread_id(state),
        "sdt": args.get("sdt", ""),
        "khoa": args.get("khoa", ""),
        "slot": args.get("slot", ""),
    }
    try:
        await get_trial_sheet().append_trial(trial)
    except Exception:
        pass  # non-fatal
    return ToolResult(
        "Dạ em đã ghi nhận lịch học thử, tư vấn viên sẽ xác nhận với mình sớm ạ.",
        {"sales_stage": SalesStage.DA_HEN_LICH},
    )


async def run_handoff_to_human(args: dict, state: dict) -> ToolResult:
    from ...handoff import get_handoff_manager
    from ...integrations import telegram_notify

    thread_id = _thread_id(state)
    reason = args.get("reason", "khách cần hỗ trợ trực tiếp")
    lead = dict(state.get("lead_profile") or {})
    owned = False
    try:
        await get_handoff_manager().set_active(thread_id, reason)   # authoritative gate
        owned = True
    except Exception:
        logger.exception("set_active failed for %s — thread NOT handed off", thread_id)
    try:
        await telegram_notify.notify(
            telegram_notify.format_handoff(lead, reason, thread_id)
        )
    except Exception:
        logger.warning("handoff Telegram notify failed for %s", thread_id)

    if not owned:
        # The row was never written, so no human owns this thread and nothing will
        # silence the bot. Claiming otherwise is the worse failure: `sales_stage`
        # HANDOFF is ABSORBING, so a transient DB blip would permanently park the
        # conversation in "a human took over" while the bot keeps answering and no
        # human is watching. Degrade to a normal turn instead — the next one retries.
        return ToolResult(
            "Dạ để em kết nối anh/chị với tư vấn viên hỗ trợ trực tiếp nhé ạ.",
            {"handoff": True},
        )
    # `escalated` means exactly "THIS invoke wrote the handoff row". The dispatcher
    # keys its TOCTOU exception on it — `handoff` alone would not do, because that
    # flag is also set advisorily by fallback/guard/reflect and is not cleared,
    # so after one routine honest-fallback every later turn would look escalated
    # and a human taking over mid-invoke would be talked over.
    return ToolResult(
        "Dạ để em kết nối anh/chị với tư vấn viên hỗ trợ trực tiếp nhé ạ.",
        {"handoff": True, "escalated": True, "sales_stage": SalesStage.HANDOFF},
    )


TOOL_IMPLS = {
    "capture_lead": run_capture_lead,
    "book_trial": run_book_trial,
    "handoff_to_human": run_handoff_to_human,
}
