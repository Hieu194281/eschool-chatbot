"""Telegram webhook — `/resume <user>` from the tư-vấn-viên group (red-team #8).

AUTH: verify `X-Telegram-Bot-Api-Secret-Token` == TELEGRAM_WEBHOOK_SECRET
(constant-time) BEFORE parsing the body. The body `chat_id` is attacker-controlled
and is NOT the auth boundary. Register with setWebhook(secret_token=...).
"""

import hmac
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from ..config import get_settings
from ..handoff import get_handoff_manager
from ..handoff.resume_command import execute_resume
from ..integrations import telegram_notify

logger = logging.getLogger(__name__)
router = APIRouter()


def _secret_ok(header_value: str) -> bool:
    configured = get_settings().telegram_webhook_secret
    if not configured:
        return False                       # unconfigured secret → reject all
    return hmac.compare_digest((header_value or "").encode(), configured.encode())


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    if not _secret_ok(request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")):
        logger.warning("Rejected Telegram webhook: bad/missing secret token")
        return Response(status_code=403)

    update = await request.json()
    text = ((update.get("message") or {}).get("text")) or ""
    if not text.strip().startswith("/resume"):
        return JSONResponse({"ok": True})

    thread_id = await execute_resume(get_handoff_manager(), text)
    if thread_id:
        await telegram_notify.notify(f"✅ Đã tiếp tục bot cho <code>{thread_id}</code>")
        return JSONResponse({"ok": True, "resumed": thread_id})
    return JSONResponse({"ok": True, "resumed": None})
