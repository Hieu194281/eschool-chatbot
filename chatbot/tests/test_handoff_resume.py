"""Handoff gate + auto-resume + /resume parsing."""

from datetime import datetime, timedelta, timezone

from app.handoff.handoff_manager import HandoffManager, should_auto_resume
from app.handoff.resume_command import parse_resume_target


# ── pure: /resume parsing ────────────────────────────────────
def test_parse_resume_full_thread_id():
    assert parse_resume_target("/resume messenger:123") == "messenger:123"


def test_parse_resume_bare_psid_defaults_channel():
    assert parse_resume_target("/resume 123") == "messenger:123"


def test_parse_resume_rejects_non_command():
    assert parse_resume_target("hello") is None
    assert parse_resume_target("/resume") is None


# ── pure: auto-resume decision ───────────────────────────────
def test_auto_resume_after_24h_silence():
    now = datetime.now(timezone.utc)
    assert should_auto_resume(now - timedelta(hours=25), None, now, 24) is True


def test_no_auto_resume_when_recent():
    now = datetime.now(timezone.utc)
    assert should_auto_resume(now - timedelta(hours=1), None, now, 24) is False


def test_no_auto_resume_when_human_recent():
    now = datetime.now(timezone.utc)
    assert should_auto_resume(now - timedelta(hours=25), now - timedelta(hours=1), now, 24) is False


# ── async: the gate ──────────────────────────────────────────
async def test_gate_skips_bot_when_active(fake_handoff_store):
    hm = HandoffManager(fake_handoff_store, 24)
    await hm.set_active("messenger:1", "khách đòi gặp người")
    assert await hm.before_invoke("messenger:1", "1") is True       # skip bot
    assert await hm.before_send("messenger:1") is True              # TOCTOU: drop reply


async def test_gate_proceeds_when_inactive(fake_handoff_store):
    hm = HandoffManager(fake_handoff_store, 24)
    assert await hm.before_invoke("messenger:2", "2") is False
    assert await hm.before_send("messenger:2") is False


async def test_gate_auto_resumes_after_silence(fake_handoff_store):
    hm = HandoffManager(fake_handoff_store, 24)
    await hm.set_active("messenger:3", "x")
    # simulate the last user + human activity as 25h ago (genuine silence)
    old = datetime.now(timezone.utc) - timedelta(hours=25)
    fake_handoff_store.rows["messenger:3"]["last_user_ts"] = old
    fake_handoff_store.rows["messenger:3"]["last_human_ts"] = old
    assert await hm.before_invoke("messenger:3", "3") is False       # auto-resumed
    assert await hm.is_active("messenger:3") is False
