"""Deterministic pricing-guard — the AUTHORITATIVE golden-rule gate (red-team #1).

Runs LAST before send. The LLM prompt + reflect-lite are advisory; THIS is the
enforced guarantee, and it is fail-closed.

Algorithm (`evaluate_draft`, pure/deterministic → heavily unit-tested):
1. Resolve which course(s) the draft NAMES (by ten_khoa match; single-retrieved
   fallback). Price is bound to a course_id — NOT "appears anywhere in k=3 context",
   which would let a right-number-wrong-course price slip through.
2. Build the allowed set = canonical money values + percentages found in the NAMED
   courses' verbatim pricing strings (via the shared VN-numeral normalizer, so
   "4tr5" == "4.500.000").
3. Every money/percent token in the draft must be a member of the allowed set.
   A model-COMPUTED discount (e.g. 5tr−10%→"4tr5") is not literally in the Sheet →
   not in the allowed set → rejected automatically.
4. A "miễn phí"/free claim is allowed only if a named course's pricing literally
   says so.
Any violation → fail closed: the node replaces the draft with the honest-fallback
line and sets handoff. Never sends an unverified price.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ...common.message_content import content_to_text
from ...common.vn_numerals import iter_money_tokens
from ..prompts import HONEST_FALLBACK

_FREE_RE = re.compile(r"miễn\s*phí|mien\s*phi|\bfree\b", re.IGNORECASE)
_WORD_RE = re.compile(r"\w+", re.UNICODE)


@dataclass
class GuardVerdict:
    ok: bool
    violations: list = field(default_factory=list)
    named_course_ids: list = field(default_factory=list)


def _name_in_draft(ten_khoa: str, draft_lower: str) -> bool:
    tk = (ten_khoa or "").lower().strip()
    if not tk:
        return False
    if tk in draft_lower:
        return True
    words = [w for w in _WORD_RE.findall(tk) if len(w) >= 3]
    if not words:
        return False
    hits = sum(1 for w in words if w in draft_lower)
    return hits / len(words) >= 0.6


def _resolve_named(draft: str, retrieved: list[dict]) -> list[dict]:
    draft_lower = (draft or "").lower()
    named = [c for c in retrieved if _name_in_draft(c.get("ten_khoa", ""), draft_lower)]
    if not named and len(retrieved) == 1:
        return list(retrieved)          # single-candidate binding
    return named


def evaluate_draft(draft: str, retrieved: list[dict]) -> GuardVerdict:
    named = _resolve_named(draft, retrieved)
    allowed_money: set[int] = set()
    allowed_pct: set[int] = set()
    pricing_strings: list[str] = []
    for course in named:
        pricing = course.get("pricing", "") or ""
        pricing_strings.append(pricing)
        for tok in iter_money_tokens(pricing):
            (allowed_money if tok.kind == "money" else allowed_pct).add(tok.value)

    violations: list[str] = []
    for tok in iter_money_tokens(draft or ""):
        if tok.kind == "money" and tok.value not in allowed_money:
            violations.append(f"số tiền không thuộc KB khóa đang nói: '{tok.raw}' ({tok.value})")
        elif tok.kind == "pct" and tok.value not in allowed_pct:
            violations.append(f"phần trăm không có trong KB: '{tok.raw}'")

    if _FREE_RE.search(draft or "") and not any(_FREE_RE.search(p) for p in pricing_strings):
        violations.append("tuyên bố 'miễn phí' không có căn cứ trong KB")

    return GuardVerdict(
        ok=not violations,
        violations=violations,
        named_course_ids=[c.get("course_id", "") for c in named],
    )


def pricing_guard_node(state: dict) -> dict:
    """Graph node: verify the final draft; fail-closed to honest-fallback + handoff."""
    from langchain_core.messages import AIMessage

    messages = state.get("messages", [])
    last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    if last_ai is None or not getattr(last_ai, "content", None):
        return {}
    # Flatten to text FIRST — on Gemini, str(content) would leak the base64 thought
    # signature, whose "<digit>K" runs get parsed as bogus prices → false violations.
    draft = content_to_text(last_ai.content)

    verdict = evaluate_draft(draft, state.get("retrieved", []) or [])
    if verdict.ok:
        return {}

    safe = AIMessage(content=HONEST_FALLBACK, id=last_ai.id)   # replace by id
    return {"messages": [safe], "handoff": True, "sales_stage": "cần người"}
