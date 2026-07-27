"""Deterministic pricing-guard — the AUTHORITATIVE golden-rule gate (red-team #1).

Runs LAST before send. The LLM prompt + reflect-lite are advisory; THIS is the
enforced guarantee, and it is fail-closed.

Schema v2 changed its INPUT, not its job. Courses no longer arrive via
`state["retrieved"]` (they are in the system prompt now) — the guard reads the
WHOLE catalog from `knowledge_base.get_all_courses()`. That is a dict walk costing
0 tokens, so the guard sees every course regardless of catalog size or mode. Do
not "optimise" it to a subset: a guard that only knows some courses cannot detect
a right-number-wrong-course quote.

Algorithm (`evaluate_draft`, pure/deterministic → heavily unit-tested):
1. Bind the draft to course(s) — `resolve_named`, 4 tiers, ambiguity → no binding.
2. Nothing bound + the draft states money → block. The old
   "single retrieved candidate" fallback is GONE: with the full catalog in scope
   it could never fire correctly, and a silent never-fires branch is worse than
   an explicit block.
3. Run money, schedule and concession checks against the bound course's facts.
Any violation → replace the draft with the honest-fallback line and hand off.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

from ...common.message_content import content_to_text
from ...common.metrics_logger import emit
from ..prompts import HONEST_FALLBACK
from ..sales_stage import SalesStage, advance_stage, normalize_stage
from .guard_checks import Kind, Violation, check_concession, check_money, check_schedule, kinds_of
from .guard_matching import resolve_named

logger = logging.getLogger(__name__)

_MONEY_WITHOUT_COURSE = Violation(
    Kind.NO_COURSE, "báo giá mà không nêu rõ khóa — không xác định được con số thuộc khóa nào"
)
_AMBIGUOUS_COURSE = Violation(
    Kind.AMBIGUOUS, "tên khóa mập mờ, không xác định được con số thuộc khóa nào"
)
_MULTI_COURSE = Violation(
    Kind.AMBIGUOUS, "một câu nêu nhiều khóa kèm số liệu — không quy được số cho khóa nào"
)

# Sentence-ish spans. Binding per SENTENCE, not per draft, is what stops the
# allowed-price set from becoming the union of every course the reply mentions.
#
# Only a FOLLOWING digit blocks the split. A plain split on "." would cut
# "1.800.000" into "1." / "800." / "000" and every money token would vanish; but
# requiring a non-digit BEFORE it too was worse — "Học phí 5.000.000. Khai giảng
# 05/08." then never split at all, so per-sentence binding silently degraded back
# to per-draft on exactly the price-bearing replies it exists for.
_SEGMENT_SPLIT_RE = re.compile(r"[.!?;\n]+(?!\d)\s*", re.UNICODE)


def _segments(draft: str) -> list[str]:
    return [s for s in _SEGMENT_SPLIT_RE.split(draft) if s.strip()]


@dataclass
class GuardVerdict:
    ok: bool
    violations: list = field(default_factory=list)
    named_course_ids: list = field(default_factory=list)
    quoted_price: bool = False      # a VERIFIED price for a bound course went out


def _has_money(draft: str) -> bool:
    from ...common.vn_numerals import iter_money_tokens

    return any(True for _ in iter_money_tokens(draft))


def _check_segment(segment: str, courses: list[dict], context: list[dict],
                   context_ambiguous: bool) -> list:
    """Verify one sentence against the course THAT sentence names."""
    named, ambiguous = resolve_named(segment, courses)
    named_here = bool(named)
    if not named and len(context) == 1 and not context_ambiguous:
        named = context           # "Khóa X rất hợp. Học phí 1.8tr ạ." — inherit X

    if not named:
        if _has_money(segment):
            return [_AMBIGUOUS_COURSE if (ambiguous or context_ambiguous)
                    else _MONEY_WITHOUT_COURSE]
        # An unbound date may be centre opening hours or an FAQ answer — unlike
        # money, it does not have to belong to a course. Not a violation.
        return []

    if len(named) > 1:
        # e.g. "Khóa A và khóa B đều 3.000.000" — one of them is being quoted at
        # the other's price and there is no way to tell which.
        return [_MULTI_COURSE] if _has_money(segment) else []

    facts = [named[0].get("facts", "") or ""]
    violations = check_money(segment, facts)
    if named_here:
        # Schedule is checked ONLY where the sentence names the course itself.
        # On an inherited binding the date may just as well be centre hours, a
        # trial slot or a call-back window — all of which the CO_SDT and
        # DA_HEN_LICH playbook rungs tell the bot to say. Checking those against
        # one course's facts blocks the very replies the sales layer prescribes.
        violations += check_schedule(segment, facts)
    return violations


def evaluate_draft(draft: str, courses: list[dict]) -> GuardVerdict:
    """Verify `draft` against the full course catalog. Pure — no I/O, no LLM."""
    draft = draft or ""
    context, context_ambiguous = resolve_named(draft, courses)

    violations: list = []
    for segment in _segments(draft):
        violations += _check_segment(segment, courses, context, context_ambiguous)

    # Whole-draft: a concession is a claim about the offer, not about one sentence.
    # With no course bound there is no `Ưu đãi` cell that could justify it, so an
    # unbound concession is unjustified by definition.
    violations += check_concession(draft, [c.get("facts", "") or "" for c in context])

    return GuardVerdict(
        ok=not violations,
        violations=violations,
        named_course_ids=[c.get("course_id", "") for c in context],
        quoted_price=not violations and _has_money(draft) and bool(context),
    )


def pricing_guard_node(state: dict) -> dict:
    """Graph node: verify the final draft; fail-closed to honest-fallback + handoff."""
    from langchain_core.messages import AIMessage

    from ...kb import knowledge_base

    messages = state.get("messages", [])
    last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    if last_ai is None or not getattr(last_ai, "content", None):
        return {}
    # Flatten to text FIRST — on Gemini, str(content) would leak the base64 thought
    # signature, whose "<digit>K" runs get parsed as bogus prices → false violations.
    draft = content_to_text(last_ai.content)

    try:
        verdict = evaluate_draft(draft, knowledge_base.get_all_courses())
    except Exception:                       # a broken guard must not become an open gate
        logger.exception("pricing_guard raised — treating as violation (fail-closed)")
        verdict = GuardVerdict(
            False, [Violation(Kind.INTERNAL, "lỗi nội bộ khi kiểm tra số liệu")])

    # Block RATE is the go-live gate: a guard that silently rejects everything looks
    # exactly like a healthy one from the error logs.
    emit(event="guard", guard_blocked=not verdict.ok,
         violation_kinds=kinds_of(verdict.violations))

    if verdict.ok:
        # The only place that knows a price was BOTH quoted and verified — which
        # is the definition of the `da_bao_gia` rung, and therefore the only
        # honest trigger for the ask-for-phone step.
        if verdict.quoted_price:
            stage = advance_stage(state.get("sales_stage"), SalesStage.DA_BAO_GIA)
            if stage != normalize_stage(state.get("sales_stage")):
                return {"sales_stage": stage}
        return {}

    logger.warning("pricing_guard blocked a draft: %s", "; ".join(verdict.violations))
    safe = AIMessage(content=HONEST_FALLBACK, id=last_ai.id)   # replace by id
    # That line asks for a phone number, so it starts the once-per-24h clock —
    # otherwise a blocked turn would let the bot ask again immediately after.
    update = {"phone_asked_at": time.time()} if not (
        state.get("lead_profile") or {}).get("sdt") else {}
    # `sales_stage` is NOT set to HANDOFF here. That stage is absorbing, so a
    # single blocked draft — expected to happen a few % of the time — would
    # permanently disable elicitation and inject "a human has taken over" into
    # every later prompt while the bot keeps replying. Blocking degrades ONE turn;
    # only a real human takeover (`handoff_to_human`, objection escalation) owns
    # the thread.
    return {"messages": [safe], "handoff": True, **update}
