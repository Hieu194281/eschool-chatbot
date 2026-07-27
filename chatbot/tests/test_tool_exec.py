"""tool_exec: doc_id dedupe (C1), MAX_RETRIEVED cap (C2), per-turn hits (H1)."""

from app.graph.nodes.tool_exec_node import (
    MAX_RETRIEVED,
    RETRIEVE_K,
    _merge_hits,
    route_after_tools,
    tool_exec_node,
)


def _hit(doc_id, text="t", course_id=""):
    return {"text": text, "source": "faq", "doc_id": doc_id, "course_id": course_id}


class _FakeKB:
    """Records the k it was called with and replays canned hits per call."""

    def __init__(self, batches=()):
        self.batches = list(batches)
        self.calls = []

    def retrieve(self, query, k=5):
        self.calls.append((query, k))
        return self.batches.pop(0) if self.batches else []


class _FakeAI:
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls


async def _run(monkeypatch, kb, state):
    """tool_exec imports `knowledge_base` from app.kb inside the function body."""
    import app.kb as kb_pkg

    monkeypatch.setattr(kb_pkg, "knowledge_base", kb)
    return await tool_exec_node(state)


def _retrieve_call(query="q", call_id="c1"):
    return {"name": "retrieve_kb", "args": {"query": query}, "id": call_id}


# ── _merge_hits (pure) ───────────────────────────────────────
def test_distinct_faq_hits_survive_empty_course_id():
    # The C1 bug: every centre-wide FAQ row has course_id="" — deduping on that
    # key collapsed 3 real hits into 1, silently.
    assert len(_merge_hits([], [_hit("faq:2"), _hit("faq:3"), _hit("faq:4")])) == 3


def test_same_doc_id_deduped_and_refreshed():
    merged = _merge_hits([_hit("faq:2", "old")], [_hit("faq:2", "new")])
    assert len(merged) == 1 and merged[0]["text"] == "new"


def test_cap_keeps_most_recent():
    existing = [_hit(f"faq:{i}") for i in range(MAX_RETRIEVED)]
    merged = _merge_hits(existing, [_hit("faq:new")])
    assert len(merged) == MAX_RETRIEVED
    assert merged[-1]["doc_id"] == "faq:new"
    assert merged[0]["doc_id"] == "faq:1"          # oldest dropped


def test_long_conversation_stays_capped():
    retrieved = []
    for turn in range(50):
        retrieved = _merge_hits(retrieved, [_hit(f"faq:{turn}")])
    assert len(retrieved) == MAX_RETRIEVED


# ── node behaviour ───────────────────────────────────────────
async def test_retrieve_sets_this_turn_and_routes_to_grade(monkeypatch):
    kb = _FakeKB([[_hit("faq:2"), _hit("faq:3")]])
    state = {"messages": [_FakeAI([_retrieve_call()])],
             "retrieved": [_hit("faq:99", "chunk từ lượt trước")]}
    out = await _run(monkeypatch, kb, state)

    assert [h["doc_id"] for h in out["retrieved_this_turn"]] == ["faq:2", "faq:3"]
    assert "faq:99" in [h["doc_id"] for h in out["retrieved"]]   # accumulation kept
    assert route_after_tools(out) == "grade_chunks"
    assert kb.calls[0][1] == RETRIEVE_K


async def test_two_retrieve_calls_in_one_turn_both_land_in_this_turn(monkeypatch):
    kb = _FakeKB([[_hit("faq:2")], [_hit("center:Giữ xe")]])
    state = {"messages": [_FakeAI([_retrieve_call("a", "c1"), _retrieve_call("b", "c2")])]}
    out = await _run(monkeypatch, kb, state)
    assert len(out["retrieved_this_turn"]) == 2
    assert len(out["messages"]) == 2


async def test_no_retrieve_routes_back_to_agent(monkeypatch):
    out = await _run(monkeypatch, _FakeKB(), {"messages": [_FakeAI([])]})
    assert route_after_tools(out) == "agent"
    assert "retrieved_this_turn" not in out


async def test_unknown_tool_still_gets_a_tool_message(monkeypatch):
    call = {"name": "nope", "args": {}, "id": "c9"}
    out = await _run(monkeypatch, _FakeKB(), {"messages": [_FakeAI([call])]})
    assert len(out["messages"]) == 1
    assert out["messages"][0].tool_call_id == "c9"
