"""TelegramAdapter — ChannelAdapter cho Telegram Bot API (đường vào = long-polling).

Đây là "adapter thứ 3" mà kiến trúc đã chừa sẵn (Messenger → Telegram): cùng ABC nên
dispatcher + graph KHÔNG đổi một dòng. Khác Messenger: tin vào bằng `getUpdates` (kéo)
thay vì webhook (đẩy) → `verify_signature` không dùng (polling tự tin cậy). Hai method
Telegram-riêng (`get_updates`, `delete_webhook`) phục vụ poller, gom mọi lời gọi Bot API
về một chỗ.
"""

from __future__ import annotations

import html
import logging
import re

import httpx

from .adapter_interface import ChannelAdapter, InboundMessage

logger = logging.getLogger(__name__)

_MAX_TG_LEN = 4096          # giới hạn độ dài 1 message của Telegram


def _md_to_telegram_html(text: str) -> str:
    """Chuyển Markdown cơ bản của LLM → HTML mà Telegram render được.

    HTML mode chỉ cần escape &<> (an toàn hơn MarkdownV2 phải escape .!-()...).
    Chỉ xử lý **đậm** / __đậm__ (thứ LLM hay xuất); ký tự khác giữ literal. Dấu ** lẻ
    (chưa đóng) không match → giữ nguyên, KHÔNG sinh thẻ HTML hỏng.
    """
    out = html.escape(text, quote=False)                    # & < >  (giữ nguyên dấu ')
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out, flags=re.S)
    out = re.sub(r"__(.+?)__", r"<b>\1</b>", out, flags=re.S)
    return out


def _strip_md(text: str) -> str:
    """Gỡ dấu Markdown → plain text (fallback khi Telegram từ chối parse HTML)."""
    return text.replace("**", "").replace("__", "")


class TelegramAdapter(ChannelAdapter):
    channel = "telegram"

    def __init__(self, http: httpx.AsyncClient, token: str) -> None:
        self._http = http
        self._base = f"https://api.telegram.org/bot{token}"

    # ── inbound ─────────────────────────────────────────────────────────────
    def verify_signature(self, body: bytes, headers) -> bool:
        return True                        # polling: không có chữ ký để verify

    def parse_inbound(self, payload: dict) -> list[InboundMessage]:
        """payload = 1 Telegram Update. CHỈ lấy tin TEXT từ chat RIÊNG 1-1
        (bỏ group/supergroup để không spam nhóm tư vấn viên)."""
        msg = payload.get("message") or {}
        chat = msg.get("chat") or {}
        if chat.get("type") != "private":
            return []
        chat_id = chat.get("id")
        text = (msg.get("text") or "").strip()
        if not chat_id or not text:
            return []
        return [InboundMessage(
            channel=self.channel,
            user_id=str(chat_id),
            text=text,
            mid=f"tg:{msg.get('message_id', '')}",   # namespace: tránh đụng mid Messenger
            timestamp=msg.get("date", 0),
        )]

    # ── outbound ────────────────────────────────────────────────────────────
    async def send_text(self, user_id: str, text: str) -> None:
        body = text[:_MAX_TG_LEN]
        try:                                    # render đậm/nghiêng qua HTML
            await self._post("sendMessage", chat_id=user_id,
                             text=_md_to_telegram_html(body), parse_mode="HTML")
        except httpx.HTTPStatusError:           # entity lỗi → gửi plain (đã gỡ **)
            await self._post("sendMessage", chat_id=user_id, text=_strip_md(body))

    async def send_typing(self, user_id: str, on: bool) -> None:
        if on:                             # Telegram chỉ có "bật" typing, tự tắt sau ~5s
            await self._post("sendChatAction", chat_id=user_id, action="typing")

    # ── Telegram-riêng (poller dùng) ────────────────────────────────────────
    async def get_updates(self, offset: int | None, timeout: int) -> list[dict]:
        params: dict = {"timeout": timeout}    # long-poll: server giữ tới `timeout` giây
        if offset is not None:
            params["offset"] = offset          # ack các update <= offset-1
        r = await self._http.get(f"{self._base}/getUpdates", params=params)
        r.raise_for_status()
        return r.json().get("result") or []

    async def delete_webhook(self, attempts: int = 3) -> None:
        # Telegram CẤM getUpdates khi webhook đang bật → gỡ + bỏ backlog cũ để poll sạch.
        # Best-effort + retry: kết nối TLS đầu tiên của client mới đôi khi rớt (cold-start).
        import asyncio

        for i in range(attempts):
            try:
                await self._post("deleteWebhook", drop_pending_updates=True)
                return
            except httpx.HTTPError:
                if i == attempts - 1:
                    raise
                await asyncio.sleep(1.0)

    async def _post(self, method: str, **payload) -> None:
        r = await self._http.post(f"{self._base}/{method}", json=payload)
        r.raise_for_status()
