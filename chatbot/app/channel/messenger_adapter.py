"""MessengerAdapter — implements ChannelAdapter for Meta Messenger."""

from __future__ import annotations

import logging

from .adapter_interface import ChannelAdapter, InboundMessage
from .signature_verify import verify_signature

logger = logging.getLogger(__name__)


class MessengerAdapter(ChannelAdapter):
    channel = "messenger"

    def __init__(self, send_client, app_secret: str) -> None:
        self._send_client = send_client
        self._app_secret = app_secret

    def verify_signature(self, body: bytes, headers) -> bool:
        return verify_signature(body, headers.get("X-Hub-Signature-256"), self._app_secret)

    def parse_inbound(self, payload: dict) -> list[InboundMessage]:
        out: list[InboundMessage] = []
        for entry in payload.get("entry", []) or []:
            for event in entry.get("messaging", []) or []:
                sender = (event.get("sender") or {}).get("id")
                message = event.get("message")
                if not sender or not message or message.get("is_echo"):
                    continue
                text = message.get("text")
                if not text:                      # skip non-text (attachments) in Pha 1
                    logger.info("Skipping non-text event from %s", sender)
                    continue
                out.append(InboundMessage(
                    channel=self.channel,
                    user_id=str(sender),
                    text=text,
                    mid=message.get("mid", ""),
                    timestamp=event.get("timestamp", 0),
                ))
        return out

    async def send_text(self, user_id: str, text: str) -> None:
        await self._send_client.send_text(user_id, text)

    async def send_typing(self, user_id: str, on: bool) -> None:
        await self._send_client.send_typing(user_id, on)
