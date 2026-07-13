"""Handoff gating + resume: authoritative table gate, TOCTOU re-check, auto-resume."""

from .handoff_manager import (
    HandoffManager,
    get_handoff_manager,
    set_handoff_manager,
    should_auto_resume,
)

__all__ = [
    "HandoffManager",
    "should_auto_resume",
    "get_handoff_manager",
    "set_handoff_manager",
]
