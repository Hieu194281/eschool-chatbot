"""Assemble + compile the StateGraph; hold the compiled singleton.

Edges (see phase-03 diagram):
    START → agent
    agent      ─ tool_calls ─────────────→ tool_exec   (loop cap → fallback)
               ─ final text ─────────────→ reflect_lite
    tool_exec  ─ retrieved ───────────────→ grade_chunks
               ─ else ───────────────────→ agent
    grade      ─ sufficient ──────────────→ agent
               ─ insufficient ───────────→ fallback
    fallback   ──────────────────────────→ reflect_lite
    reflect    ─ ok / safest ─────────────→ pricing_guard
               ─ one fix ────────────────→ agent
    pricing_guard ───────────────────────→ END   (deterministic, last gate)

Checkpointer lifecycle (red-team #3) is handled by the caller (main.py lifespan),
which keeps the AsyncPostgresSaver context open for the whole app lifetime.
"""

from __future__ import annotations

import logging

from .nodes.agent_node import agent_node, route_after_agent
from .nodes.fallback_node import fallback_node
from .nodes.grade_node import grade_node, route_after_grade
from .nodes.pricing_guard import pricing_guard_node
from .nodes.reflect_node import reflect_node, route_after_reflect
from .nodes.tool_exec_node import route_after_tools, tool_exec_node
from .state import ConvState

logger = logging.getLogger(__name__)

_graph = None


def build_graph(checkpointer=None):
    """Build + compile the StateGraph. `checkpointer=None` → no persistence (tests)."""
    from langgraph.graph import END, START, StateGraph

    builder = StateGraph(ConvState)
    builder.add_node("agent", agent_node)
    builder.add_node("tool_exec", tool_exec_node)
    builder.add_node("grade_chunks", grade_node)
    builder.add_node("fallback", fallback_node)
    builder.add_node("reflect_lite", reflect_node)
    builder.add_node("pricing_guard", pricing_guard_node)

    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "agent", route_after_agent,
        {"tool_exec": "tool_exec", "reflect_lite": "reflect_lite", "fallback": "fallback"},
    )
    builder.add_conditional_edges(
        "tool_exec", route_after_tools,
        {"grade_chunks": "grade_chunks", "agent": "agent"},
    )
    builder.add_conditional_edges(
        "grade_chunks", route_after_grade,
        {"agent": "agent", "fallback": "fallback"},
    )
    builder.add_edge("fallback", "reflect_lite")
    builder.add_conditional_edges(
        "reflect_lite", route_after_reflect,
        {"pricing_guard": "pricing_guard", "agent": "agent"},
    )
    builder.add_edge("pricing_guard", END)

    return builder.compile(checkpointer=checkpointer)


def set_graph(graph) -> None:
    global _graph
    _graph = graph
    logger.info("Compiled graph registered")


def get_graph():
    if _graph is None:
        raise RuntimeError("Graph not built — call set_graph() in the app lifespan first.")
    return _graph
