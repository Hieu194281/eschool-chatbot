"""Agent tools: read-only `retrieve_kb` + state-mutating lead tools.

`ALL_TOOL_SCHEMAS` is what we bind to the LLM (schemas only). Execution happens in
the tool_exec node, which calls `TOOL_IMPLS` and applies the returned state update
— so state-mutating tools actually write ConvState channels (red-team #2), without
depending on a specific LangGraph Command-from-tool API version.
"""

from .lead_tools import (
    TOOL_IMPLS,
    ToolResult,
    book_trial,
    capture_lead,
    handoff_to_human,
)
from .retrieve_kb_tool import RETRIEVE_TOOL_NAME, retrieve_kb

ALL_TOOL_SCHEMAS = [retrieve_kb, capture_lead, book_trial, handoff_to_human]

__all__ = [
    "ALL_TOOL_SCHEMAS",
    "TOOL_IMPLS",
    "ToolResult",
    "RETRIEVE_TOOL_NAME",
    "retrieve_kb",
    "capture_lead",
    "book_trial",
    "handoff_to_human",
]
