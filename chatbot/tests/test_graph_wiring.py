"""The graph actually compiles, and every conditional edge names a real node.

Until langgraph was installed in the test env, `build_graph()` ran in production
only: a typo in a destination map (all rewired this plan — new entry node, 3-way
reflect map) would have shipped silently.
"""

import pytest

pytest.importorskip("langgraph")

from app.graph.graph_builder import build_graph  # noqa: E402
from app.graph.nodes.detect_objection import route_after_detect  # noqa: E402
from app.graph.nodes.reflect_node import route_after_reflect  # noqa: E402
from app.graph.prompts.objection_prompt import GIA_CAO, NONE, SO_SANH_CHO_KHAC  # noqa: E402

EXPECTED_NODES = {"detect_objection", "handle_objection", "agent", "tool_exec",
                  "grade_chunks", "fallback", "reflect_lite", "pricing_guard"}


@pytest.fixture(scope="module")
def graph():
    return build_graph(checkpointer=None)


def test_graph_compiles(graph):
    assert graph is not None


def test_every_node_is_registered(graph):
    assert EXPECTED_NODES <= set(graph.get_graph().nodes)


def test_entry_is_the_objection_detector(graph):
    edges = graph.get_graph().edges
    starts = {e.target for e in edges if e.source == "__start__"}
    assert starts == {"detect_objection"}


def test_every_router_destination_is_a_real_node(graph):
    nodes = set(graph.get_graph().nodes)
    destinations = {
        route_after_detect({"objection_type": NONE}),
        route_after_detect({"objection_type": GIA_CAO}),
        route_after_detect({"objection_type": SO_SANH_CHO_KHAC}),
        route_after_reflect({"route_hint": "guard"}),
        route_after_reflect({"route_hint": "fix"}),
        route_after_reflect({"route_hint": "fix", "objection_type": GIA_CAO}),
    }
    assert destinations <= nodes


def _outgoing(graph):
    outgoing = {}
    for edge in graph.get_graph().edges:
        outgoing.setdefault(edge.source, set()).add(edge.target)
    return outgoing


def test_the_guard_is_the_only_door_to_end(graph):
    """DOMINANCE, not reachability: no path may reach END around the guard.

    'Can reach the guard' is not the property that matters — 'cannot reach END
    without it' is. The guard is the only enforced check on prices.
    """
    predecessors = {
        edge.source for edge in graph.get_graph().edges if edge.target == "__end__"
    }
    assert predecessors == {"pricing_guard"}


def test_no_reply_producer_short_circuits_to_end(graph):
    outgoing = _outgoing(graph)
    for producer in ("handle_objection", "fallback", "agent", "reflect_lite"):
        assert "__end__" not in outgoing.get(producer, set())


def test_every_producer_can_still_reach_the_guard(graph):
    """Complements dominance: the guard must also not be unreachable."""
    outgoing = _outgoing(graph)
    for producer in ("handle_objection", "fallback", "agent"):
        seen, stack = set(), [producer]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(outgoing.get(node, ()))
        assert "pricing_guard" in seen, f"{producer} cannot reach the guard"
