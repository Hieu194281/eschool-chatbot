"""Messenger Send API client (shared httpx.AsyncClient). typing + RESPONSE text,
message splitting, basic 429 backoff.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

_MAX_CHUNK = 1800   # Messenger limit ~2000; keep chunks small for readability


def split_message(text: str, limit: int = _MAX_CHUNK) -> list[str]:
    text = (text or "").strip()
    if len(text) <= limit:
        return [text] if text else []
    chunks, current = [], ""
    for word in text.split(" "):
        if len(current) + len(word) + 1 > limit:
            if current:
                chunks.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        chunks.append(current)
    return chunks


class MessengerSendClient:
    def __init__(self, client, page_access_token: str, api_version: str) -> None:
        self._client = client
        self._token = page_access_token
        self._url = f"https://graph.facebook.com/{api_version}/me/messages"

    async def _post(self, payload: dict) -> None:
        for attempt in range(2):
            resp = await self._client.post(
                self._url, params={"access_token": self._token}, json=payload, timeout=15.0
            )
            if resp.status_code == 429 and attempt == 0:
                logger.warning("Send API 429; backing off briefly")
                await asyncio.sleep(1.0)
                continue
            if resp.status_code >= 400:
                logger.error("Send API error %s: %s", resp.status_code, resp.text[:300])
            return

    async def send_typing(self, psid: str, on: bool) -> None:
        await self._post({"recipient": {"id": psid},
                          "sender_action": "typing_on" if on else "typing_off"})

    async def send_text(self, psid: str, text: str) -> None:
        for chunk in split_message(text):
            await self._post({
                "recipient": {"id": psid},
                "messaging_type": "RESPONSE",
                "message": {"text": chunk},
            })
