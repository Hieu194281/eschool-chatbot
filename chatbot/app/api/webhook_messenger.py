"""Messenger webhook: GET verify (hub.challenge) + POST handler.

POST flow (red-team #7): read raw body → verify HMAC synchronously → schedule
processing via FastAPI `BackgroundTasks` (drained on graceful shutdown, NOT a bare
create_task) → return 200 immediately. Never block on graph/LLM.

Residual crash-loss window: a hard crash between the 200 ACK and the debounce flush
loses the buffered fragment (Meta won't redeliver). A durable inbound queue is the
Pha-2 upgrade — documented in the runbook.
"""

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import PlainTextResponse, Response

from ..config import get_settings
from ..channel.message_dispatcher import RATE_LIMIT_LINE

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/webhook/messenger")
async def verify(request: Request):
    params = request.query_params
    settings = get_settings()
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == settings.verify_token:
        return PlainTextResponse(params.get("hub.challenge", ""))
    return Response(status_code=403)


@router.post("/webhook/messenger")
async def receive(request: Request, background: BackgroundTasks):
    body = await request.body()
    app = request.app
    adapter = app.state.adapter
    if not adapter.verify_signature(body, request.headers):
        logger.warning("Rejected webhook POST: bad/missing signature")
        return Response(status_code=403)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return Response(status_code=400)
    background.add_task(process_events, app, payload)     # drained on shutdown
    return Response(status_code=200)


async def process_events(app, payload: dict) -> None:
    adapter = app.state.adapter
    dedupe = app.state.dedupe
    debounce = app.state.debounce
    rate_limiter = app.state.rate_limiter
    dispatcher = app.state.dispatcher

    for msg in adapter.parse_inbound(payload):
        if not rate_limiter.allow(msg.user_id):
            await dispatcher.deliver_text(msg.user_id, RATE_LIMIT_LINE)   # no graph spend
            continue
        if dedupe.seen(msg.mid):
            continue
        debounce.add(msg.user_id, msg.text)
