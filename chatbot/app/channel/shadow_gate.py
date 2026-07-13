"""Shadow-mode send gate (red-team #16 launch safety).

SHADOW_MODE=true → the drafted reply goes to the Telegram tư-vấn-viên group
(for a human to review/copy), and NOTHING is sent to the real user. Flip to false
for full auto-send. This is the single switch that guarantees zero user-facing sends
during the shadow dry-run.
"""

from __future__ import annotations

import html

from ..config import get_settings
from ..integrations import telegram_notify


def make_deliver_fn(adapter):
    """Return an async deliver(user_id, text) the dispatcher calls instead of send."""

    async def _deliver(user_id: str, text: str) -> None:
        if get_settings().shadow_mode:
            draft = f"📝 <b>[DRAFT → {html.escape(user_id)}]</b>\n{html.escape(text)}"
            await telegram_notify.notify(draft)
        else:
            await adapter.send_text(user_id, text)

    return _deliver
