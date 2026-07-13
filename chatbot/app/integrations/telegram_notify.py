"""Telegram notifier (raw httpx POST — no lib). Handoff summary, hot-lead ping, and
the KB-sync error sink all route here. HTML-escaped to avoid markup injection.
"""

from __future__ import annotations

import html
import logging

from ..config import get_settings

logger = logging.getLogger(__name__)


def _esc(value) -> str:
    return html.escape(str(value if value is not None else "—"))


def format_hot_lead(lead: dict) -> str:
    return (
        "🔥 <b>LEAD NÓNG</b>\n"
        f"Tên: {_esc(lead.get('ten'))}\n"
        f"SĐT: {_esc(lead.get('sdt'))}\n"
        f"Khóa: {_esc(lead.get('khoa_quan_tam'))}\n"
        f"Nhu cầu: {_esc(lead.get('nhu_cau'))}\n"
        f"Chat: {_esc(lead.get('chat_link'))}"
    )


def format_handoff(lead: dict, reason: str, chat_link: str, turns: str = "") -> str:
    msg = (
        "🙋 <b>CẦN TƯ VẤN VIÊN</b>\n"
        f"Lý do: {_esc(reason)}\n"
        f"Tên: {_esc(lead.get('ten'))}\n"
        f"SĐT: {_esc(lead.get('sdt'))}\n"
        f"Khóa: {_esc(lead.get('khoa_quan_tam'))}\n"
        f"Độ nóng: {_esc(lead.get('do_nong'))}\n"
        f"Chat: {_esc(chat_link)}"
    )
    if turns:
        msg += f"\n\n<i>{_esc(turns)}</i>"
    return msg


async def notify(text_html: str) -> None:
    """Send an HTML message to the configured tư-vấn-viên group. Non-fatal on error."""
    import httpx

    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.warning("Telegram not configured; skipping notify")
        return
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = {"chat_id": settings.telegram_chat_id, "text": text_html, "parse_mode": "HTML"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                logger.error("Telegram notify failed %s: %s", resp.status_code, resp.text[:200])
    except Exception:
        logger.exception("Telegram notify error (non-fatal)")


_main_loop = None


def set_main_loop(loop) -> None:
    """Capture the app's event loop so the KB scheduler THREAD can schedule sends."""
    global _main_loop
    _main_loop = loop


def notify_sync_errors(errors: list[str]) -> None:
    """Sync error-callback for the KB scheduler thread → schedule an async send on
    the captured main loop (thread-safe). Dropped with a log if no loop is set."""
    import asyncio

    if not errors:
        return
    text = "⚠️ <b>KB SYNC</b>\n" + "\n".join(_esc(e) for e in errors[:20])
    if _main_loop is not None and _main_loop.is_running():
        asyncio.run_coroutine_threadsafe(notify(text), _main_loop)
    else:
        logger.warning("No running loop for KB-sync alert; dropped: %s", text[:200])
