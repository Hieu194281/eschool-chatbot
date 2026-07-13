"""Shadow gate: SHADOW_MODE=true → draft to Telegram, zero user sends."""

import app.integrations.telegram_notify as telegram_notify
from app.channel.shadow_gate import make_deliver_fn
from app.config import get_settings


class _Adapter:
    def __init__(self):
        self.sent = []

    async def send_text(self, uid, text):
        self.sent.append((uid, text))


async def test_shadow_mode_drafts_to_telegram(monkeypatch):
    monkeypatch.setenv("SHADOW_MODE", "true")
    get_settings.cache_clear()
    drafts = []

    async def fake_notify(text):
        drafts.append(text)

    monkeypatch.setattr(telegram_notify, "notify", fake_notify)
    adapter = _Adapter()
    deliver = make_deliver_fn(adapter)
    await deliver("psid-1", "dạ xin chào ạ")
    assert adapter.sent == []                 # ZERO user-facing sends
    assert drafts and "dạ xin chào ạ" in drafts[0]


async def test_live_mode_sends_to_user(monkeypatch):
    monkeypatch.setenv("SHADOW_MODE", "false")
    get_settings.cache_clear()
    adapter = _Adapter()
    deliver = make_deliver_fn(adapter)
    await deliver("psid-1", "hi")
    assert adapter.sent == [("psid-1", "hi")]
    get_settings.cache_clear()                # restore for other tests
