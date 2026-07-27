"""The bot's own escalation must not silence the bot's own goodbye.

`_escalate` writes the handoff table DURING the invoke. The dispatcher's
mid-invoke TOCTOU check then saw an active handoff and dropped the reply — so
escalating paged a human AND left the customer staring at nothing. `state["handoff"]`
is the signal that tells the two cases apart, and this is where it is read.
"""

from app.channel.message_dispatcher import MessageDispatcher
from app.channel.rate_limiter import RateLimiter


class _FakeAdapter:
    channel = "messenger"

    def __init__(self):
        self.sent = []

    async def send_text(self, user_id, text):
        self.sent.append(text)

    async def send_typing(self, user_id, on):
        pass


class _AlwaysActiveGate:
    """Handoff is active by send time — as it is right after self-escalation."""

    def __init__(self):
        self.before_send_calls = 0

    async def before_invoke(self, thread_id, user_id):
        return False                       # not active when the turn started

    async def before_send(self, thread_id):
        self.before_send_calls += 1
        return True


def _dispatcher(monkeypatch, reply, self_escalated, gate):
    delivered = []

    async def deliver(uid, text):
        delivered.append(text)

    disp = MessageDispatcher(_FakeAdapter(), RateLimiter(1000, 10000, 50),
                             deliver_fn=deliver, handoff_gate=gate)

    async def _fake_invoke(thread_id, user_id, text):
        return reply, self_escalated

    monkeypatch.setattr(disp, "_invoke_graph", _fake_invoke)
    return disp, delivered


async def test_self_escalated_reply_is_still_delivered(monkeypatch):
    gate = _AlwaysActiveGate()
    disp, delivered = _dispatcher(monkeypatch, "Dạ để em kết nối tư vấn viên ạ.",
                                  True, gate)
    await disp.on_flush("u1", "bên kia rẻ hơn")
    assert delivered == ["Dạ để em kết nối tư vấn viên ạ."]
    assert gate.before_send_calls == 0      # not even consulted — we know why it flipped


async def test_human_takeover_mid_invoke_still_drops_the_reply(monkeypatch):
    gate = _AlwaysActiveGate()
    disp, delivered = _dispatcher(monkeypatch, "Dạ khóa này học phí 5 triệu ạ.",
                                  False, gate)
    await disp.on_flush("u1", "học phí bao nhiêu")
    assert delivered == []                  # a real human owns the thread now
    assert gate.before_send_calls == 1


async def test_no_gate_configured_delivers_normally(monkeypatch):
    disp, delivered = _dispatcher(monkeypatch, "Dạ vâng ạ.", False, None)
    await disp.on_flush("u1", "chào em")
    assert delivered == ["Dạ vâng ạ."]


async def test_stale_flag_from_an_earlier_turn_does_not_grant_the_bypass():
    """The bypass must key on THIS turn's escalation, not a sticky flag.

    `handoff` is set advisorily by fallback/guard/reflect and would otherwise
    stay True for the rest of the conversation, so after one routine
    honest-fallback the bot would talk over every human takeover thereafter.
    """
    from app.graph.nodes.detect_objection import turn_reset

    stale = {"handoff": True, "escalated": True}
    fresh = {**stale, **turn_reset()}
    assert fresh["escalated"] is False and fresh["handoff"] is False


def test_only_real_escalation_sets_the_bypass_flag():
    import inspect

    from app.graph.tools import lead_tools

    # `escalated` is written at exactly one site — the one that writes the
    # handoff row. Any other writer would re-open the stale-flag hole.
    sources = [inspect.getsource(fn) for fn in
               (lead_tools.run_handoff_to_human, lead_tools.run_capture_lead,
                lead_tools.run_book_trial)]
    assert sum('"escalated": True' in src for src in sources) == 1
    assert '"escalated": True' in inspect.getsource(lead_tools.run_handoff_to_human)
