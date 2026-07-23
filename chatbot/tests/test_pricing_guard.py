"""Deterministic pricing-guard — the authoritative golden-rule gate.

Covers: exact-price pass, promo-derived (computed discount) reject, right-number-
wrong-course reject (price↔course_id binding), 'miễn phí' no-basis reject, and
percentage binding.
"""

from app.graph.nodes.pricing_guard import evaluate_draft

COURSE_A = {
    "course_id": "IELTS01",
    "ten_khoa": "IELTS Cấp Tốc",
    "pricing": "Học phí: 5.000.000\nƯu đãi: giảm 10%",
}
COURSE_B = {
    "course_id": "TOEIC01",
    "ten_khoa": "TOEIC Nền Tảng",
    "pricing": "Học phí: 3.000.000",
}


def test_exact_price_passes():
    draft = "Dạ khóa IELTS Cấp Tốc học phí 5 triệu ạ."
    assert evaluate_draft(draft, [COURSE_A]).ok is True


def test_grouped_price_passes():
    draft = "Học phí khóa IELTS Cấp Tốc là 5.000.000 đồng ạ."
    assert evaluate_draft(draft, [COURSE_A]).ok is True


def test_computed_discount_rejected():
    # 5tr − 10% = 4tr5, which is NOT literally in the Sheet → must fail closed.
    draft = "Dạ khóa IELTS Cấp Tốc giảm 10% còn 4tr5 thôi ạ."
    verdict = evaluate_draft(draft, [COURSE_A])
    assert verdict.ok is False
    assert verdict.violations


def test_right_number_wrong_course_rejected():
    # Course A's price (5tr) quoted while NAMING course B → binding violation.
    draft = "Dạ khóa TOEIC Nền Tảng học phí 5 triệu ạ."
    verdict = evaluate_draft(draft, [COURSE_A, COURSE_B])
    assert verdict.ok is False


def test_correct_course_price_passes_multi():
    draft = "Dạ khóa TOEIC Nền Tảng học phí 3 triệu ạ."
    assert evaluate_draft(draft, [COURSE_A, COURSE_B]).ok is True


def test_free_claim_without_basis_rejected():
    draft = "Dạ khóa IELTS Cấp Tốc đang miễn phí ạ."
    assert evaluate_draft(draft, [COURSE_A]).ok is False


def test_percent_binding():
    # 10% is in course A's uu_dai → allowed; 20% is not → rejected.
    assert evaluate_draft("Khóa IELTS Cấp Tốc giảm 10% ạ", [COURSE_A]).ok is True
    assert evaluate_draft("Khóa IELTS Cấp Tốc giảm 20% ạ", [COURSE_A]).ok is False


def test_price_with_no_course_retrieved_fails_closed():
    # Bot states a price but nothing was retrieved → cannot bind → fail closed.
    assert evaluate_draft("Học phí 5 triệu ạ", []).ok is False


def test_no_price_no_violation():
    draft = "Dạ khóa này phù hợp cho học sinh mất gốc ạ."
    assert evaluate_draft(draft, [COURSE_A]).ok is True


# ── Node-level: Gemini list-content must be flattened before guarding ─────────
# Bug: Gemini returns content as a list of blocks with a base64 thought signature.
# str(content) leaks the signature, whose "<digit>K" runs parse as bogus prices →
# false fail-closed block. The node must flatten to text first (content_to_text).

def _gemini_content(text: str, signature: str):
    return [{"type": "text", "text": text, "extras": {"signature": signature}}]


def test_node_signature_not_a_false_violation():
    from langchain_core.messages import AIMessage

    from app.graph.nodes.pricing_guard import pricing_guard_node

    # signature carries "8K"/"801k"/"94K" — bogus money tokens on the OLD str() path
    content = _gemini_content("Dạ khóa IELTS Cấp Tốc học phí 5.000.000 ạ.",
                              "CqAG8K801k0KfooBar94Kbaz")
    state = {"messages": [AIMessage(content=content)], "retrieved": [COURSE_A]}
    assert pricing_guard_node(state) == {}          # verified price → no block


def test_node_still_blocks_real_violation_in_list_content():
    from langchain_core.messages import AIMessage

    from app.graph.nodes.pricing_guard import pricing_guard_node

    # computed discount 4tr5 (not in Sheet) inside list content → still fail closed
    content = _gemini_content("Dạ khóa IELTS Cấp Tốc giảm 10% còn 4tr5 ạ.", "Zz")
    state = {"messages": [AIMessage(content=content)], "retrieved": [COURSE_A]}
    assert pricing_guard_node(state).get("handoff") is True
