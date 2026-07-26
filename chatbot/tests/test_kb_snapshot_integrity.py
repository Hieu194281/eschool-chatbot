"""KB snapshot invariants: verbatim never embedded, no course docs, atomic swap.

These are the properties the whole golden rule rests on. They hold today by
construction — this file makes a future refactor that breaks one of them fail
loudly instead of shipping a bot that quotes a hallucinated price.
"""

import threading

from app.kb.center_faq_parser import parse_center_faq
from app.kb.course_parser import parse_courses
from app.kb.vector_store import KnowledgeBase, _Snapshot

COURSE_COLS = ["course_id", "ten_khoa", "tu_khoa", "doi_tuong", "muc_tieu",
               "hoc_phi", "uu_dai", "khai_giang", "si_so", "hinh_thuc", "co_so"]

SECRETS = ("5.000.000", "giảm 10%", "05/08", "12 học viên", "Quận 1")


def _course(cid="C1"):
    row = {c: "" for c in COURSE_COLS}
    row.update({"course_id": cid, "ten_khoa": f"Khóa {cid}", "doi_tuong": "lớp 6",
                "muc_tieu": "lấy lại căn bản", "hoc_phi": "5.000.000",
                "uu_dai": "giảm 10%", "khai_giang": "05/08", "si_so": "12 học viên",
                "hinh_thuc": "Offline", "co_so": "Quận 1"})
    return row


def _snapshot(store=None, course_rows=(), center_rows=(), faq_rows=()):
    courses = parse_courses(list(course_rows))
    center_faq = parse_center_faq(list(center_rows), list(faq_rows))
    return _Snapshot(
        store=store, facts_map=courses.facts_map, course_index=courses.course_index,
        course_blocks=courses.course_blocks, center_always=center_faq.always_text,
        verbatim_map=center_faq.verbatim_map, meta=courses.course_meta,
        version=(len(courses.course_blocks), len(center_faq.docs)),
    )


class _FakeStore:
    def __init__(self, docs=()):
        self.docs = list(docs)

    def similarity_search(self, query, k=5):
        return self.docs[:k]


def test_no_document_in_the_store_comes_from_a_course():
    center = [{"chu_de": "Giới thiệu", "noi_dung": "Từ 2015", "loai": "embed", "tu_khoa": ""}]
    faq = [{"cau_hoi": "Giữ xe?", "tra_loi": "Có", "course_id": "", "tu_khoa": ""}]
    docs = parse_center_faq(center, faq).docs
    assert docs and all(d.metadata["source"] in ("faq", "center") for d in docs)


def test_verbatim_values_never_reach_an_embedded_document():
    center = [{"chu_de": "Học phí", "noi_dung": "Xem từng khóa", "loai": "embed", "tu_khoa": ""}]
    faq = [{"cau_hoi": "Học phí?", "tra_loi": "Tùy khóa", "course_id": "", "tu_khoa": ""}]
    embedded = " ".join(d.page_content for d in parse_center_faq(center, faq).docs)
    course_docs = " ".join(d.page_content for d in parse_courses([_course()]).docs)
    for secret in SECRETS:
        assert secret not in embedded
        assert secret not in course_docs


def test_facts_map_and_catalog_stay_in_sync():
    kb = KnowledgeBase()
    kb._snapshot = _snapshot(_FakeStore(), [_course("C1"), _course("C2")])
    catalog = kb.get_catalog_text()
    for course in kb.get_all_courses():
        assert course["facts"] in catalog          # guard and prompt see the same text


def test_reader_never_observes_a_half_built_snapshot():
    """The swap is one attribute rebind — readers see the old or new KB, never a mix."""
    kb = KnowledgeBase()
    kb._snapshot = _snapshot(_FakeStore(), [_course("C1")])
    old, new = kb._snapshot, _snapshot(_FakeStore(), [_course("C2")])
    seen, stop = [], threading.Event()

    def reader():
        while not stop.is_set():
            snap = kb._snapshot
            # course_blocks and facts_map must always describe the SAME courses.
            seen.append(set(snap.course_blocks) == set(snap.facts_map))

    thread = threading.Thread(target=reader)
    thread.start()
    for _ in range(200):
        kb._snapshot = new
        kb._snapshot = old
    stop.set()
    thread.join()

    assert seen and all(seen)


def test_kb_not_ready_returns_empty_not_none():
    kb = KnowledgeBase()
    assert kb.get_catalog_text() == ""
    assert kb.get_center_always() == ""
    assert kb.get_facts("C1") == ""
    assert kb.get_all_courses() == []
    assert kb.get_verbatim_map() == {}
    assert kb.get_meta("C1") == {}
    assert kb.retrieve("gì đó") == []
