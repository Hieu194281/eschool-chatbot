"""LangGraph brain: single channel-agnostic StateGraph (agent ⇄ tools,
Corrective-RAG, reflect-lite, deterministic pricing-guard).

NOTE: import builders from `app.graph.graph_builder` directly (not re-exported here)
so that importing a single node module (e.g. the pure pricing_guard) does NOT pull in
langgraph. Keeps deterministic-guard unit tests dependency-free.
"""
