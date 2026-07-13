"""Telegram resume webhook auth: forged/missing secret-token header → 403."""

import app.integrations.telegram_notify as telegram_notify
from app.config import get_settings

SECRET = "test-webhook-secret"   # matches conftest env default


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.webhook_telegram import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_missing_token_rejected():
    get_settings.cache_clear()
    resp = _client().post("/webhook/telegram", json={"message": {"text": "/resume messenger:1"}})
    assert resp.status_code == 403


def test_wrong_token_rejected():
    resp = _client().post(
        "/webhook/telegram",
        headers={"X-Telegram-Bot-Api-Secret-Token": "totally-wrong"},
        json={"message": {"text": "/resume messenger:1"}},
    )
    assert resp.status_code == 403


def test_valid_token_resumes(monkeypatch):
    cleared = []

    class FakeHM:
        async def clear(self, thread_id):
            cleared.append(thread_id)

    from app.handoff import handoff_manager as hm_mod
    hm_mod.set_handoff_manager(FakeHM())

    async def noop(text):
        pass

    monkeypatch.setattr(telegram_notify, "notify", noop)

    resp = _client().post(
        "/webhook/telegram",
        headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
        json={"message": {"text": "/resume messenger:1"}},
    )
    assert resp.status_code == 200
    assert resp.json()["resumed"] == "messenger:1"
    assert cleared == ["messenger:1"]
