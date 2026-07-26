"""resolve_named: 4 tiers, name collisions across the full catalog, fail-closed."""

from app.graph.nodes.guard_matching import resolve_named

T7 = {"course_id": "T7-MG", "ten_khoa": "Toán 7 Mất Gốc",
      "tu_khoa": ["toan7 mat goc", "t7mg"], "facts": "Học phí: 1.800.000"}
T9 = {"course_id": "T9-MG", "ten_khoa": "Toán 9 Mất Gốc",
      "tu_khoa": ["toan9 mat goc"], "facts": "Học phí: 2.400.000"}
V7 = {"course_id": "V7-MG", "ten_khoa": "Văn 7 Mất Gốc",
      "tu_khoa": ["van7 mat goc"], "facts": "Học phí: 1.700.000"}
IELTS = {"course_id": "IELTS01", "ten_khoa": "IELTS Cấp Tốc",
         "tu_khoa": ["ielts cap toc"], "facts": "Học phí: 5.000.000"}
CATALOG = [T7, T9, IELTS]


def _ids(courses):
    return [c["course_id"] for c in courses]


# ── tier 1: course_id ────────────────────────────────────────
def test_tier1_course_id_literal():
    named, ambiguous = resolve_named("Khóa T7-MG học phí 1.800.000đ ạ", CATALOG)
    assert _ids(named) == ["T7-MG"] and ambiguous is False


def test_course_id_needs_a_boundary():
    # "T7-MGX" is a different id — a bare substring hit would mis-bind.
    named, _ = resolve_named("mã T7-MGX ạ", CATALOG)
    assert _ids(named) != ["T7-MG"]


# ── tier 2: exact ten_khoa ───────────────────────────────────
def test_tier2_exact_name_beats_collision():
    named, ambiguous = resolve_named("Dạ khóa Toán 9 Mất Gốc học phí 2.400.000 ạ", CATALOG)
    assert _ids(named) == ["T9-MG"] and ambiguous is False


def test_name_match_is_whitespace_insensitive():
    named, _ = resolve_named("khóa   toán 7   mất gốc ạ", CATALOG)
    assert _ids(named) == ["T7-MG"]


def test_two_courses_named_explicitly_is_not_ambiguous():
    named, ambiguous = resolve_named("Có Toán 7 Mất Gốc và Toán 9 Mất Gốc ạ", CATALOG)
    assert set(_ids(named)) == {"T7-MG", "T9-MG"} and ambiguous is False


# ── tier 3: alias ────────────────────────────────────────────
def test_tier3_alias_unaccented():
    named, ambiguous = resolve_named("khoa toan7 mat goc ha chi", CATALOG)
    assert _ids(named) == ["T7-MG"] and ambiguous is False


# ── tier 4: fuzzy + ambiguity ────────────────────────────────
def test_tier4_paraphrase_resolves_to_one():
    named, ambiguous = resolve_named("khóa mất gốc cho lớp 7 ạ", CATALOG)
    assert _ids(named) == ["T7-MG"] and ambiguous is False


def test_identical_significant_words_are_ambiguous():
    # "Toán 7 Mất Gốc" vs "Văn 7 Mất Gốc" — subject is a stopword, so both reduce
    # to {7, mất, gốc} and the paraphrase fits BOTH. Must not pick one.
    named, ambiguous = resolve_named("khóa mất gốc lớp 7 ạ", [T7, V7])
    assert named == [] and ambiguous is True


def test_partial_overlap_binds_nothing():
    # "mất gốc" without the grade misses the bar for every course → no binding.
    # Not flagged ambiguous, but any price in such a draft is still blocked upstream.
    named, ambiguous = resolve_named("bên em có khóa mất gốc ạ", CATALOG)
    assert named == [] and ambiguous is False


def test_no_course_mentioned_is_neither_named_nor_ambiguous():
    named, ambiguous = resolve_named("Dạ trung tâm mở cửa 8h-21h ạ", CATALOG)
    assert named == [] and ambiguous is False


def test_empty_inputs():
    assert resolve_named("", CATALOG) == ([], False)
    assert resolve_named("khóa Toán 7 Mất Gốc", []) == ([], False)


def test_subject_words_alone_do_not_bind():
    # "toán"/"lớp"/"khóa" are stopwords — a generic sentence must not bind a course.
    named, ambiguous = resolve_named("Dạ bên em có các khóa toán cho nhiều lớp ạ", CATALOG)
    assert named == [] and ambiguous is False
