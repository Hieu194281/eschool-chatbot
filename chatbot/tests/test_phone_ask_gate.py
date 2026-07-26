"""One-ask-for-phone rule — enforced on state, not on prompt wording."""

from app.graph.nodes.phone_ask_gate import (
    ASK_WINDOW_SECONDS,
    should_suppress,
    strip_phone_ask,
    wants_phone,
)

NOW = 1_800_000_000.0


def test_detects_the_common_phrasings():
    for text in ["Anh/chị cho em xin số điện thoại nhé",
                 "Chị để lại SĐT giúp em ạ",
                 "Em gửi qua Zalo cho mình nhé",
                 "Cho em xin số liên hệ ạ"]:
        assert wants_phone(text) is True


def test_ordinary_reply_is_not_an_ask():
    assert wants_phone("Dạ khóa này học 18h00-19h30 ạ") is False


def test_first_ask_is_allowed():
    assert should_suppress({}, NOW) is False


def test_second_ask_within_the_window_is_suppressed():
    state = {"phone_asked_at": NOW - 60, "lead_profile": {}}
    assert should_suppress(state, NOW) is True


def test_ask_allowed_again_after_the_window():
    state = {"phone_asked_at": NOW - ASK_WINDOW_SECONDS - 1, "lead_profile": {}}
    assert should_suppress(state, NOW) is False


def test_nothing_to_suppress_once_the_number_is_known():
    state = {"phone_asked_at": NOW - 60, "lead_profile": {"sdt": "0912345678"}}
    assert should_suppress(state, NOW) is False


def test_strip_keeps_the_useful_half_of_the_reply():
    draft = ("Dạ khóa Toán 7 học 18h00-19h30 ạ. "
             "Anh/chị cho em xin số điện thoại để em gửi lịch nhé!")
    stripped = strip_phone_ask(draft)
    assert "18h00-19h30" in stripped
    assert "số điện thoại" not in stripped


def test_strip_can_empty_a_reply_that_was_only_an_ask():
    assert strip_phone_ask("Cho em xin số điện thoại nhé!") == ""


def test_strip_handles_newline_separated_sentences():
    stripped = strip_phone_ask("Dạ vâng ạ\nChị để lại SĐT giúp em\nEm cảm ơn ạ")
    assert "SĐT" not in stripped and "Em cảm ơn" in stripped


# ── ordering inside reflect_node ─────────────────────────────
async def test_forbidden_promise_is_still_caught_when_the_ask_is_stripped(monkeypatch):
    """The gate used to short-circuit reflect, shipping the promise unchecked."""
    from langchain_core.messages import AIMessage

    import app.graph.nodes.reflect_node as reflect_mod

    draft = "Dạ bên em cam kết đậu ạ. Anh/chị cho em xin số điện thoại nhé!"
    state = {"messages": [AIMessage(content=draft)],
             "phone_asked_at": NOW - 60, "lead_profile": {}}

    monkeypatch.setattr(reflect_mod, "time", __import__("time"), raising=False)
    out = await reflect_mod.reflect_node(state)

    sent = out["messages"][0].content
    assert "cam kết đậu" not in sent          # blocklist ran
    assert "số điện thoại" not in sent        # gate ran too


async def test_ask_only_reply_becomes_a_neutral_line(monkeypatch):
    from langchain_core.messages import AIMessage

    import app.graph.nodes.reflect_node as reflect_mod

    state = {"messages": [AIMessage(content="Cho em xin số điện thoại nhé!")],
             "phone_asked_at": NOW - 60, "lead_profile": {}}

    class _FakeStructured:
        async def ainvoke(self, prompt):
            return reflect_mod.ReflectResult(ok=True)

    class _FakeLLM:
        def with_structured_output(self, model):
            return _FakeStructured()

    monkeypatch.setattr(reflect_mod, "lite_llm", lambda: _FakeLLM())
    out = await reflect_mod.reflect_node(state)

    sent = out["messages"][0].content
    assert sent == reflect_mod.NEUTRAL_CONTINUATION   # not the nag re-sent
    assert "phone_asked_at" not in out
