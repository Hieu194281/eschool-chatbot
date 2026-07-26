"""`run_handoff_to_human` must not claim a takeover it failed to perform.

`sales_stage=handoff` is ABSORBING and `escalated` grants the dispatcher's
send-anyway bypass. Writing either when `set_active` threw parks the thread in
"a human took over" while no human owns it, nothing silences the bot, and no
later turn can climb out — a transient DB blip becomes permanent.
"""

import app.graph.tools.lead_tools as lead_tools


class _OkManager:
    def __init__(self):
        self.calls = []

    async def set_active(self, thread_id, reason):
        self.calls.append((thread_id, reason))


class _BrokenManager:
    async def set_active(self, thread_id, reason):
        raise RuntimeError("postgres down")


def _patch(monkeypatch, manager, notify_ok=True):
    import app.handoff as handoff_pkg
    from app.integrations import telegram_notify

    monkeypatch.setattr(handoff_pkg, "get_handoff_manager", lambda: manager)

    sent = []

    async def _notify(text):
        if not notify_ok:
            raise RuntimeError("telegram down")
        sent.append(text)

    monkeypatch.setattr(telegram_notify, "notify", _notify)
    return sent


STATE = {"channel": "messenger", "user_id": "psid-1", "lead_profile": {"ten": "Chị A"}}


async def test_successful_handoff_claims_ownership(monkeypatch):
    manager = _OkManager()
    sent = _patch(monkeypatch, manager)

    result = await lead_tools.run_handoff_to_human({"reason": "khách đòi gặp người"}, STATE)

    assert manager.calls == [("messenger:psid-1", "khách đòi gặp người")]
    assert result.state_update["escalated"] is True
    assert result.state_update["sales_stage"] == "handoff"
    assert result.state_update["handoff"] is True
    assert sent                                   # a human was actually told


async def test_failed_set_active_does_not_claim_ownership(monkeypatch):
    _patch(monkeypatch, _BrokenManager())

    result = await lead_tools.run_handoff_to_human({"reason": "khiếu nại"}, STATE)

    update = result.state_update
    assert update["handoff"] is True              # advisory only
    assert "escalated" not in update              # no send-anyway bypass
    assert "sales_stage" not in update            # must NOT park in the absorbing stage
    assert result.message                         # customer still gets a reply


async def test_telegram_failure_alone_still_counts_as_a_takeover(monkeypatch):
    manager = _OkManager()
    _patch(monkeypatch, manager, notify_ok=False)

    result = await lead_tools.run_handoff_to_human({"reason": "lead nóng"}, STATE)

    # The row IS written, so the thread genuinely is handed off; a missed Telegram
    # ping is a notification problem, not an ownership one.
    assert manager.calls
    assert result.state_update["escalated"] is True
    assert result.state_update["sales_stage"] == "handoff"
