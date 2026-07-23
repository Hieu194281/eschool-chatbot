"""TelegramPoller — vòng long-polling chạy như BACKGROUND TASK trong app lifespan.

Tương đương `webhook_messenger.process_events`, chỉ khác nguồn tin: getUpdates (kéo)
thay vì webhook (đẩy). Mỗi update đi qua ĐÚNG bộ máy như Messenger:
    rate-limit → dedupe → debounce → dispatcher(single-flight) → graph.

Xử lý tuần tự trong loop → không có 2 update chạy song song ngoài ý muốn; single-flight
theo thread_id vẫn do dispatcher đảm bảo.
"""

from __future__ import annotations

import asyncio
import logging

from .message_dispatcher import RATE_LIMIT_LINE

logger = logging.getLogger(__name__)

POLL_TIMEOUT = 25          # giây long-poll mỗi vòng getUpdates


class TelegramPoller:
    def __init__(self, adapter, dispatcher, dedupe, debounce, rate_limiter) -> None:
        self._adapter = adapter
        self._dispatcher = dispatcher
        self._dedupe = dedupe
        self._debounce = debounce
        self._rate_limiter = rate_limiter

    async def run(self) -> None:
        try:
            await self._adapter.delete_webhook()
        except Exception as exc:      # best-effort: nếu không có webhook thì getUpdates vẫn chạy
            logger.warning("deleteWebhook bỏ qua sau retry: %s", exc)
        logger.info("Telegram polling started — nhắn RIÊNG 1-1 cho bot để test")
        offset: int | None = None
        while True:
            try:
                updates = await self._adapter.get_updates(offset, POLL_TIMEOUT)
            except asyncio.CancelledError:
                logger.info("Telegram polling stopped")
                raise
            except Exception:
                logger.exception("getUpdates lỗi; thử lại sau 3s")
                await asyncio.sleep(3)
                continue
            for upd in updates:
                offset = upd["update_id"] + 1
                await self._ingest(upd)

    async def _ingest(self, update: dict) -> None:
        for msg in self._adapter.parse_inbound(update):
            if not self._rate_limiter.allow(msg.user_id):
                await self._dispatcher.deliver_text(msg.user_id, RATE_LIMIT_LINE)
                continue
            if self._dedupe.seen(msg.mid):
                continue
            self._debounce.add(msg.user_id, msg.text)
