"""Deterministic pricing-guard — the authoritative golden-rule gate.

Covers: exact-price pass, computed-discount reject, right-number-wrong-course
reject, name-collision fail-closed, price-without-course reject, 'miễn phí'
no-basis reject, percentage binding, schedule binding, concession rule, and the
fail-closed exception path.
"""

from app.graph.nodes.pricing_guard import GuardVerdict, evaluate_draft

COURSE_A = {
    "course_id": "IELTS01",
    "ten_khoa": "IELTS Cấp Tốc",
    "tu_khoa": ["ielts cap toc"],
    "facts": "Học phí: 5.000.000\nƯu đãi: giảm 10%\nKhai giảng: 05/08\nLịch học: 18h00-19h30",
}
COURSE_B = {
    "course_id": "TOEIC01",
    "ten_khoa": "TOEIC Nền Tảng",
    "tu_khoa": ["toeic nen tang"],
    "facts": "Học phí: 3.000.000",
}
T7 = {"course_id": "T7-MG", "ten_khoa": "Toán 7 Mất Gốc", "tu_khoa": [],
      "facts": "Học phí: 1.800.000"}
T9 = {"course_id": "T9-MG", "ten_khoa": "Toán 9 Mất Gốc", "tu_khoa": [],
      "facts": "Học phí: 2.400.000"}
V7 = {"course_id": "V7-MG", "ten_khoa": "Văn 7 Mất Gốc", "tu_khoa": [],
      "facts": "Học phí: 1.700.000"}


# ── money binding ────────────────────────────────────────────
def test_exact_price_passes():
    assert evaluate_draft("Dạ khóa IELTS Cấp Tốc học phí 5 triệu ạ.", [COURSE_A]).ok is True


def test_grouped_price_passes():
    assert evaluate_draft("Học phí khóa IELTS Cấp Tốc là 5.000.000 đồng ạ.", [COURSE_A]).ok is True


def test_computed_discount_rejected():
    # 5tr − 10% = 4tr5, not literally in the Sheet → fail closed.
    verdict = evaluate_draft("Dạ khóa IELTS Cấp Tốc còn 4tr5 thôi ạ.", [COURSE_A])
    assert verdict.ok is False and verdict.violations


def test_right_number_wrong_course_rejected():
    draft = "Dạ khóa TOEIC Nền Tảng học phí 5 triệu ạ."
    assert evaluate_draft(draft, [COURSE_A, COURSE_B]).ok is False


def test_correct_course_price_passes_multi():
    assert evaluate_draft("Dạ khóa TOEIC Nền Tảng học phí 3 triệu ạ.", [COURSE_A, COURSE_B]).ok


def test_wrong_price_for_colliding_course_name():
    # Success criterion: T7 quoted with T9's real price → must block.
    verdict = evaluate_draft("Dạ Toán 7 Mất Gốc học phí 2.400.000đ ạ.", [T7, T9])
    assert verdict.ok is False
    assert verdict.named_course_ids == ["T7-MG"]


def test_ambiguous_course_name_fails_closed():
    # T7 vs V7 differ only by a stopword subject → paraphrase fits both → block.
    verdict = evaluate_draft("Khóa mất gốc lớp 7 học phí 1.800.000đ ạ", [T7, V7])
    assert verdict.ok is False
    assert any("mập mờ" in v for v in verdict.violations)


def test_price_with_a_too_vague_course_reference_fails_closed():
    verdict = evaluate_draft("Khóa mất gốc học phí 1.800.000đ ạ", [T7, T9])
    assert verdict.ok is False
    assert any("không nêu rõ khóa" in v for v in verdict.violations)


def test_price_without_naming_a_course_rejected():
    verdict = evaluate_draft("Dạ học phí bên em 1.800.000đ ạ", [T7, T9])
    assert verdict.ok is False
    assert any("không nêu rõ khóa" in v for v in verdict.violations)


def test_empty_catalog_still_fails_closed_on_money():
    assert evaluate_draft("Học phí 5 triệu ạ", []).ok is False


def test_free_claim_without_basis_rejected():
    assert evaluate_draft("Dạ khóa IELTS Cấp Tốc đang miễn phí ạ.", [COURSE_A]).ok is False


def test_percent_binding():
    assert evaluate_draft("Khóa IELTS Cấp Tốc giảm 10% ạ", [COURSE_A]).ok is True
    assert evaluate_draft("Khóa IELTS Cấp Tốc giảm 20% ạ", [COURSE_A]).ok is False


def test_no_number_no_course_no_violation():
    assert evaluate_draft("Dạ khóa này phù hợp cho học sinh mất gốc ạ.", [COURSE_A]).ok is True


# ── review C1: per-sentence binding, no union of facts ───────
def test_two_courses_in_one_sentence_with_one_price_blocked():
    # Union-of-facts bug: TOEIC's price was accepted as IELTS's because both bound.
    draft = "Dạ khóa IELTS Cấp Tốc và khóa TOEIC Nền Tảng đều 3.000.000 ạ."
    verdict = evaluate_draft(draft, [COURSE_A, COURSE_B])
    assert verdict.ok is False


def test_one_price_per_sentence_each_correct_passes():
    draft = ("Dạ khóa IELTS Cấp Tốc học phí 5.000.000đ ạ. "
             "Khóa TOEIC Nền Tảng học phí 3.000.000đ ạ.")
    assert evaluate_draft(draft, [COURSE_A, COURSE_B]).ok is True


def test_one_price_per_sentence_one_wrong_is_blocked():
    draft = ("Dạ khóa IELTS Cấp Tốc học phí 5.000.000đ ạ. "
             "Khóa TOEIC Nền Tảng học phí 5.000.000đ ạ.")
    assert evaluate_draft(draft, [COURSE_A, COURSE_B]).ok is False


def test_price_inherits_the_single_course_named_earlier():
    draft = "Dạ khóa IELTS Cấp Tốc rất hợp với bé ạ. Học phí 5.000.000đ ạ."
    assert evaluate_draft(draft, [COURSE_A, COURSE_B]).ok is True


def test_substring_course_name_does_not_shadow_the_specific_one():
    base = {"course_id": "T9", "ten_khoa": "Toán 9", "tu_khoa": [],
            "facts": "Học phí: 2.000.000"}
    advanced = {"course_id": "T9NC", "ten_khoa": "Toán 9 Nâng Cao", "tu_khoa": [],
                "facts": "Học phí: 4.000.000"}
    # Naming the advanced course used to bind BOTH → the base price passed.
    assert evaluate_draft("Khóa Toán 9 Nâng Cao học phí 2.000.000 ạ", [base, advanced]).ok is False
    assert evaluate_draft("Khóa Toán 9 Nâng Cao học phí 4.000.000 ạ", [base, advanced]).ok is True


# ── review C2: prices written in words ───────────────────────
def test_word_numeral_price_is_checked_not_ignored():
    assert evaluate_draft("Dạ khóa IELTS Cấp Tốc học phí bốn triệu rưỡi ạ", [COURSE_A]).ok is False
    assert evaluate_draft("Dạ khóa IELTS Cấp Tốc học phí năm triệu ạ", [COURSE_A]).ok is True


def test_word_numeral_without_a_course_is_blocked():
    assert evaluate_draft("Dạ học phí bên em bốn triệu rưỡi ạ", [COURSE_A, COURSE_B]).ok is False


# ── review H4/H5: binding cannot be hijacked ─────────────────
def test_short_alias_cannot_bind_every_polite_sentence():
    from app.kb.course_parser import _split_keywords

    course = {"course_id": "S1", "ten_khoa": "Sinh Học 12",
              "tu_khoa": _split_keywords("anh, sinh12"), "facts": "Học phí: 7.000.000"}
    # "anh" is dropped at parse time, so this draft binds nothing → price blocked.
    assert evaluate_draft("Dạ anh cho em xin thông tin, học phí 7.000.000 ạ", [course]).ok is False


# ── review round 2 ───────────────────────────────────────────
def test_sentence_ending_in_a_digit_still_splits():
    from app.graph.nodes.pricing_guard import _segments

    # Requiring a non-digit BEFORE the "." meant a price-ending sentence never
    # split, silently reverting per-sentence binding to per-draft.
    assert _segments("Học phí 5.000.000. Khai giảng 05/08.") == \
        ["Học phí 5.000.000", "Khai giảng 05/08"]
    assert _segments("Học phí 1.800.000đ ạ") == ["Học phí 1.800.000đ ạ"]


def test_id_and_alias_in_one_sentence_both_count():
    # Tier short-circuit resolved this to ONE course, so the multi-course block —
    # which works by counting — never fired.
    draft = "Dạ IELTS01 và khóa TOEIC Nền Tảng đều 5.000.000 ạ"
    assert evaluate_draft(draft, [COURSE_A, COURSE_B]).ok is False


def test_shadowed_name_kept_when_the_draft_names_it_separately():
    base = {"course_id": "T9", "ten_khoa": "Toán 9", "tu_khoa": [],
            "facts": "Học phí: 2.000.000"}
    advanced = {"course_id": "T9NC", "ten_khoa": "Toán 9 Nâng Cao", "tu_khoa": [],
                "facts": "Học phí: 4.000.000"}
    # Both named → un-attributable, must block (shadow-drop must not hide one).
    assert evaluate_draft("Toán 9 và Toán 9 Nâng Cao đều 4.000.000 ạ",
                          [base, advanced]).ok is False
    # Only the long name → shadow-drop still applies, correct price passes.
    assert evaluate_draft("Khóa Toán 9 Nâng Cao học phí 4.000.000 ạ",
                          [base, advanced]).ok is True


def test_compound_word_numerals_give_the_right_value():
    from app.common.vn_numerals import money_values

    # Matching only the trailing word turned "mười lăm triệu" into 5.000.000 —
    # a WRONG value that then passed against a course priced at 5tr.
    assert money_values("mười lăm triệu") == {15_000_000}
    assert money_values("hai mươi mốt triệu") == {21_000_000}
    assert money_values("một triệu tám") == {1_800_000}
    # Unaccented is the register Messenger actually uses; a missing spelling made
    # the whole phrase unmatchable, i.e. an INVISIBLE price.
    assert money_values("muoi lam trieu") == {15_000_000}
    assert money_values("bon trieu ruoi") == {4_500_000}
    assert money_values("ba tram nghin") == {300_000}
    assert money_values("một tỷ") == {1_000_000_000}


def test_ty_le_and_ti_mi_are_not_billions():
    from app.common.vn_numerals import money_values

    # "tỷ lệ đậu" is the single most common phrase in admissions talk and
    # "tỉ mỉ" is standard praise for a teacher — reading either as 1e9 would
    # honest-fallback ordinary sentences.
    for phrase in ("một tỷ lệ nhỏ học viên", "một tỉ lệ rất nhỏ",
                   "bốn tỷ lệ khác nhau", "hai tỉ mỉ"):
        assert money_values(phrase) == set(), phrase
    assert money_values("khóa này một tỷ đồng") == {1_000_000_000}
    course = {**COURSE_A, "facts": "Học phí: 5.000.000"}
    assert evaluate_draft("Khóa IELTS Cấp Tốc học phí mười lăm triệu ạ", [course]).ok is False


def test_centre_hours_after_a_course_sentence_are_not_blocked():
    # An inherited binding is a guess; checking a guessed course's schedule blocked
    # the exact lines the CO_SDT / DA_HEN_LICH rungs prescribe.
    draft = "Dạ khóa IELTS Cấp Tốc hợp lắm ạ. Trung tâm mở cửa 8h00-21h00 ạ."
    assert evaluate_draft(draft, [COURSE_A]).ok is True


def test_schedule_still_checked_when_the_sentence_names_the_course():
    assert evaluate_draft("Khóa IELTS Cấp Tốc khai giảng 12/08 ạ", [COURSE_A]).ok is False


def test_digits_from_a_price_cannot_name_a_course():
    course = {"course_id": "E9", "ten_khoa": "Lớp 9 Ôn Thi", "tu_khoa": [],
              "facts": "Học phí: 9.000.000"}
    # The "9" in 9.000.000 used to score a perfect name match → price laundered.
    assert evaluate_draft("Dạ chương trình này học phí 9.000.000 ạ", [course]).ok is False


# ── schedule binding ─────────────────────────────────────────
def test_matching_start_date_passes():
    assert evaluate_draft("Khóa IELTS Cấp Tốc khai giảng 05/08 ạ", [COURSE_A]).ok is True


def test_wrong_start_date_rejected():
    verdict = evaluate_draft("Khóa IELTS Cấp Tốc khai giảng 12/08 ạ", [COURSE_A])
    assert verdict.ok is False
    assert any("ngày/giờ" in v for v in verdict.violations)


def test_year_omitted_in_draft_still_matches():
    course = {**COURSE_A, "facts": "Học phí: 5.000.000\nKhai giảng: 05/08/2026"}
    assert evaluate_draft("Khóa IELTS Cấp Tốc khai giảng 05/08 ạ", [course]).ok is True


def test_hour_shorthand_matches_padded_kb_value():
    assert evaluate_draft("Khóa IELTS Cấp Tốc học 18h-19h30 ạ", [COURSE_A]).ok is True


def test_duration_is_not_read_as_a_clock_time():
    # "2h" here means 2 hours long, not 02:00 — must not be checked as a time.
    assert evaluate_draft("Khóa IELTS Cấp Tốc mỗi buổi 2h ạ", [COURSE_A]).ok is True


def test_date_without_a_named_course_is_not_blocked():
    # Could be centre opening hours or an FAQ — warn territory, not block.
    assert evaluate_draft("Dạ trung tâm mở cửa 8h00-21h00 ạ", [COURSE_A]).ok is True


# ── concession rule ──────────────────────────────────────────
def test_invented_concession_rejected():
    verdict = evaluate_draft("Để em xin ưu đãi riêng cho chị nhé", [COURSE_A])
    assert verdict.ok is False
    assert any("nhượng bộ" in v for v in verdict.violations)


def test_reading_the_real_uu_dai_passes():
    assert evaluate_draft("Khóa IELTS Cấp Tốc đang giảm 10% ạ", [COURSE_A]).ok is True


def test_special_price_offer_rejected():
    assert evaluate_draft("Khóa IELTS Cấp Tốc em để giá đặc biệt cho chị ạ", [COURSE_A]).ok is False


# ── node-level fail-closed ───────────────────────────────────
def _guard(monkeypatch, kb, state):
    import app.graph.nodes.pricing_guard as guard_mod
    import app.kb as kb_pkg

    monkeypatch.setattr(kb_pkg, "knowledge_base", kb)
    return guard_mod.pricing_guard_node(state)


class _KB:
    def __init__(self, courses):
        self._courses = courses

    def get_all_courses(self):
        return list(self._courses)


class _ExplodingKB:
    def get_all_courses(self):
        raise RuntimeError("snapshot corrupt")


def test_guard_exception_is_treated_as_violation(monkeypatch):
    from langchain_core.messages import AIMessage

    out = _guard(monkeypatch, _ExplodingKB(),
                 {"messages": [AIMessage(content="Học phí 5 triệu")]})
    assert out["handoff"] is True
    assert out["messages"][0].content != "Học phí 5 triệu"


def test_blocking_does_not_sink_the_sales_stage(monkeypatch):
    # HANDOFF is absorbing. A blocked draft is a degraded TURN, not a human
    # takeover — writing it here would permanently kill elicitation.
    from langchain_core.messages import AIMessage

    out = _guard(monkeypatch, _KB([COURSE_A]),
                 {"messages": [AIMessage(content="Khóa IELTS Cấp Tốc học phí 9 triệu ạ")],
                  "sales_stage": "da_ro_nhu_cau"})
    assert out["handoff"] is True
    assert "sales_stage" not in out


def test_verified_price_advances_to_da_bao_gia(monkeypatch):
    from langchain_core.messages import AIMessage

    state = {"messages": [AIMessage(content="Dạ khóa IELTS Cấp Tốc học phí 5 triệu ạ.")],
             "sales_stage": "da_ro_nhu_cau"}
    assert _guard(monkeypatch, _KB([COURSE_A]), state) == {"sales_stage": "da_bao_gia"}


def test_clean_draft_without_a_price_leaves_state_untouched(monkeypatch):
    from langchain_core.messages import AIMessage

    state = {"messages": [AIMessage(content="Dạ khóa IELTS Cấp Tốc phù hợp với bé ạ.")],
             "sales_stage": "da_ro_nhu_cau"}
    assert _guard(monkeypatch, _KB([COURSE_A]), state) == {}


def test_stage_never_regresses_from_a_later_rung(monkeypatch):
    from langchain_core.messages import AIMessage

    state = {"messages": [AIMessage(content="Dạ khóa IELTS Cấp Tốc học phí 5 triệu ạ.")],
             "sales_stage": "co_sdt"}
    assert _guard(monkeypatch, _KB([COURSE_A]), state) == {}


def test_verdict_defaults():
    assert GuardVerdict(True).violations == []
