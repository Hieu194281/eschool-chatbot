"""State-mutating tools: schemas for the LLM + impl functions for tool_exec.

Ph03: impl bodies are STUBS that still write the correct ConvState channels (so
`handoff`/`sales_stage`/`lead_profile` actually flip — red-team #2). Ph05 replaces
the bodies with real Sheet/Telegram/handoff-table calls, keeping this same
`ToolResult(message, state_update)` contract.

Impls are async so Ph05 can await network I/O without changing the tool_exec node.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.tools import tool


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
) -> str:
    """Lưu thông tin lead vào hệ thống: tên, số điện thoại (sdt), khóa quan tâm,
    nhu cầu, và độ nóng ("lạnh"/"ấm"/"nóng"). Gọi khi khách cung cấp SĐT hoặc thông
    tin liên hệ."""
    return "Đã lưu thông tin khách."


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
    for key in ("ten", "sdt", "khoa_quan_tam", "nhu_cau", "do_nong"):
        if args.get(key):
            profile[key] = args[key]
    stage = "đã xin SĐT" if profile.get("sdt") else state.get("sales_stage", "đang tư vấn")
    channel_user_id = _thread_id(state)

    # PII/PDPD: consent recorded at capture (bot gives privacy notice before asking SĐT).
    lead = {
        "channel_user_id": channel_user_id,
        "ten": profile.get("ten"),
        "sdt": profile.get("sdt"),
        "khoa_quan_tam": profile.get("khoa_quan_tam"),
        "nhu_cau": profile.get("nhu_cau"),
        "do_nong": profile.get("do_nong", "ấm"),
        "sales_stage": stage,
        "chat_link": channel_user_id,
        "consent": "yes" if profile.get("sdt") else "",
        "consent_at": datetime.now(timezone.utc).isoformat() if profile.get("sdt") else "",
    }
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
        {"sales_stage": "đã chốt"},
    )


async def run_handoff_to_human(args: dict, state: dict) -> ToolResult:
    from ...handoff import get_handoff_manager
    from ...integrations import telegram_notify

    thread_id = _thread_id(state)
    reason = args.get("reason", "khách cần hỗ trợ trực tiếp")
    lead = dict(state.get("lead_profile") or {})
    try:
        await get_handoff_manager().set_active(thread_id, reason)   # authoritative gate
        await telegram_notify.notify(
            telegram_notify.format_handoff(lead, reason, thread_id)
        )
    except Exception:
        pass  # advisory handoff below still stops the bot for this turn
    return ToolResult(
        "Dạ để em kết nối anh/chị với tư vấn viên hỗ trợ trực tiếp nhé ạ.",
        {"handoff": True, "sales_stage": "cần người"},
    )


TOOL_IMPLS = {
    "capture_lead": run_capture_lead,
    "book_trial": run_book_trial,
    "handoff_to_human": run_handoff_to_human,
}
