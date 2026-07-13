"""Parse + execute the Telegram `/resume <user>` command.

`parse_resume_target` is pure (unit-tested). `/resume messenger:PSID` or
`/resume PSID` (defaults to the messenger channel) both work.
"""

from __future__ import annotations


def parse_resume_target(text: str, default_channel: str = "messenger") -> str | None:
    """Return the thread_id to resume, or None if not a valid /resume command."""
    if not text:
        return None
    parts = text.strip().split()
    if not parts or parts[0].lower() != "/resume" or len(parts) < 2:
        return None
    target = parts[1].strip()
    if ":" in target:                      # already a full thread_id (channel:user)
        return target
    return f"{default_channel}:{target}"


async def execute_resume(handoff_manager, text: str) -> str | None:
    """Clear handoff for the parsed target. Returns the resumed thread_id or None."""
    thread_id = parse_resume_target(text)
    if thread_id is None:
        return None
    await handoff_manager.clear(thread_id)
    return thread_id
