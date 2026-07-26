"""KnowledgeBase snapshot: catalog assembly, store scope, guard-facing readers."""

import app.kb.vector_store as vs_mod
from app.kb.center_faq_parser import parse_center_faq
from app.kb.course_parser import parse_courses
from app.kb.vector_store import CATALOG_INDEX_THRESHOLD, KnowledgeBase, _Snapshot

COURSE_COLS = ["course_id", "ten_khoa", "tu_khoa", "doi_tuong", "hoc_phi", "hinh_thuc"]


def _course(cid, ten, **over):
    row = {c: "" for c in COURSE_COLS}
    row.update({"course_id": cid, "ten_khoa": ten, "doi_tuong": "lớp 6",
                "hoc_phi": "5.000.000", "hinh_thuc": "Offline"})
    row.update(over)
    return row


class _FakeStore:
    def __init__(self, docs=()):
        self.docs = list(docs)

    def similarity_search(self, query, k=5):
        return self.docs[:k]


class _FakeDoc:
    def __init__(self, content, metadata):
        self.page_content = content
        self.metadata = metadata


def _kb(course_rows=(), center_rows=(), faq_rows=(), store=None):
    courses = parse_courses(list(course_rows))
    center_faq = parse_center_faq(list(center_rows), list(faq_rows))
    kb = KnowledgeBase()
    kb._snapshot = _Snapshot(
        store=store or _FakeStore(),
        facts_map=courses.facts_map,
        course_index=courses.course_index,
        course_blocks=courses.course_blocks,
        center_always=center_faq.always_text,
        verbatim_map=center_faq.verbatim_map,
        meta=courses.course_meta,
        version=(len(courses.course_blocks), 0),
    )
    return kb


# ── catalog assembly ─────────────────────────────────────────
def test_catalog_puts_index_before_details():
    kb = _kb([_course("C1", "Toán 6"), _course("C2", "Lý 7")])
    text = kb.get_catalog_text()
    assert text.index("[MỤC LỤC KHÓA]") < text.index("[CHI TIẾT KHÓA]")
    assert "C1  Toán 6 — lớp 6 — Offline" in text
    assert 'id=C1 "Toán 6"' in text


def test_catalog_sorted_by_course_id_for_cache_stability():
    unsorted_rows = [_course("C3", "C"), _course("C1", "A"), _course("C2", "B")]
    text = _kb(unsorted_rows).get_catalog_text()
    assert text.index("C1") < text.index("C2") < text.index("C3")
    assert text == _kb(list(reversed(unsorted_rows))).get_catalog_text()


def test_catalog_carries_verbatim_facts():
    kb = _kb([_course("C1", "Toán 6", hoc_phi="5.000.000đ")])
    assert "Học phí: 5.000.000đ" in kb.get_catalog_text()


def test_empty_kb_degrades_instead_of_crashing():
    kb = KnowledgeBase()
    assert kb.get_catalog_text() == "" and kb.get_center_always() == ""
    assert kb.get_all_courses() == [] and kb.retrieve("bất kỳ") == []
    assert kb.ready is False


# ── store scope ──────────────────────────────────────────────
def test_store_holds_only_faq_and_center_docs():
    center = [{"chu_de": "Giới thiệu", "noi_dung": "Từ 2015", "loai": "embed", "tu_khoa": ""}]
    faq = [{"cau_hoi": "Có giữ xe?", "tra_loi": "Có", "course_id": "", "tu_khoa": ""}]
    docs = parse_center_faq(center, faq).docs
    assert {d.metadata["source"] for d in docs} == {"center", "faq"}
    assert not any(d.metadata["source"] == "course" for d in docs)


def test_retrieve_returns_doc_id_for_dedupe():
    store = _FakeStore([_FakeDoc("Q: x\nA: y", {"source": "faq", "doc_id": "faq:2", "course_id": ""})])
    hit = _kb(store=store).retrieve("x")[0]
    assert hit["doc_id"] == "faq:2" and hit["source"] == "faq"
    assert "pricing" not in hit                 # facts are always-on now, not per-hit


# ── guard-facing readers (Phase 03 depends on these) ─────────
def test_get_all_courses_exposes_facts_and_keywords():
    kb = _kb([_course("C1", "Toán 6", tu_khoa="toan6, Toan Lop 6")])
    (course,) = kb.get_all_courses()
    assert course["course_id"] == "C1" and course["ten_khoa"] == "Toán 6"
    assert course["tu_khoa"] == ["toan6", "toan lop 6"]
    assert "5.000.000" in course["facts"]


def test_too_short_aliases_are_dropped_at_parse_time():
    # A 2-3 char alias ("t6", "anh") matches almost any draft, and the guard
    # treats an alias hit as CERTAIN — so it never reaches the guard.
    kb = _kb([_course("C1", "Toán 6", tu_khoa="t6, anh, 6, toan6")])
    assert kb.get_all_courses()[0]["tu_khoa"] == ["toan6"]


def test_center_always_and_verbatim_are_separate_channels():
    center = [
        {"chu_de": "Địa chỉ", "noi_dung": "12 Lê Lợi", "loai": "always", "tu_khoa": ""},
        {"chu_de": "Trả góp", "noi_dung": "0% qua thẻ", "loai": "verbatim", "tu_khoa": ""},
    ]
    kb = _kb(center_rows=center)
    assert "12 Lê Lợi" in kb.get_center_always()
    assert "0% qua thẻ" not in kb.get_center_always()
    assert kb.get_verbatim_map() == {"Trả góp": "0% qua thẻ"}
    assert KnowledgeBase().get_verbatim_map() == {}      # KB not ready → empty, not None


def test_get_facts_is_per_course():
    kb = _kb([_course("C1", "A", hoc_phi="1.000.000"), _course("C2", "B", hoc_phi="2.000.000")])
    assert "1.000.000" in kb.get_facts("C1")
    assert "2.000.000" not in kb.get_facts("C1")
    assert kb.get_facts("KHONG_CO") == ""


# ── growth threshold ─────────────────────────────────────────
def test_oversized_catalog_logs_actionable_warning(caplog):
    rows = [_course(f"C{i:03d}", f"Khóa {i}") for i in range(CATALOG_INDEX_THRESHOLD + 1)]
    kb = _kb(rows)
    with caplog.at_level("WARNING", logger=vs_mod.__name__):
        kb._log_stamp(doc_count=0, error_count=0)
    assert "CATALOG_MODE=index" in caplog.text


def test_normal_catalog_size_logs_no_warning(caplog):
    kb = _kb([_course("C1", "Toán 6")])
    with caplog.at_level("WARNING", logger=vs_mod.__name__):
        kb._log_stamp(doc_count=1, error_count=0)
    assert "CATALOG_MODE=index" not in caplog.text
