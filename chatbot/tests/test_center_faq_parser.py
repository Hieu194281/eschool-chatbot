"""Center/FAQ parser: loai routing, per-doc doc_id, verbatim sanitization."""

from app.kb.center_faq_parser import parse_center_faq

CENTER_COLS = ["chu_de", "noi_dung", "loai", "tu_khoa"]
FAQ_COLS = ["cau_hoi", "tra_loi", "course_id", "tu_khoa"]

REQUIRED_TOPICS = [
    {"chu_de": "Trả góp", "noi_dung": "Hỗ trợ trả góp 0%", "loai": "verbatim", "tu_khoa": ""},
    {"chu_de": "Test đầu vào", "noi_dung": "Miễn phí", "loai": "verbatim", "tu_khoa": ""},
    {"chu_de": "Cam kết gọi lại", "noi_dung": "Gọi trong 24h", "loai": "verbatim", "tu_khoa": ""},
]


def _center(**over):
    base = {c: "" for c in CENTER_COLS}
    base.update(over)
    return base


def _faq(**over):
    base = {c: "" for c in FAQ_COLS}
    base.update(over)
    return base


def test_loai_routes_to_three_destinations():
    rows = [
        _center(chu_de="Địa chỉ", noi_dung="12 Lê Lợi", loai="always"),
        _center(chu_de="Giờ mở cửa", noi_dung="8h-21h", loai="always"),
        _center(chu_de="Trả góp", noi_dung="Trả góp 0% qua thẻ", loai="verbatim"),
        _center(chu_de="Giới thiệu", noi_dung="Trung tâm thành lập 2015", loai="embed"),
    ]
    result = parse_center_faq(rows, [])
    assert "Địa chỉ: 12 Lê Lợi" in result.always_text
    assert "Giờ mở cửa: 8h-21h" in result.always_text
    assert result.verbatim_map["Trả góp"] == "Trả góp 0% qua thẻ"
    assert [d.metadata["source"] for d in result.docs] == ["center"]
    assert "Trung tâm thành lập 2015" in result.docs[0].page_content
    # verbatim/always content must NOT be embedded
    assert "Trả góp 0%" not in result.docs[0].page_content


def test_invalid_loai_reported_and_skipped():
    result = parse_center_faq([_center(chu_de="X", noi_dung="y", loai="alway")], [])
    assert not result.docs and not result.verbatim_map and not result.always_text
    assert any("alway" in e for e in result.errors)


def test_dirty_verbatim_center_row_quarantined():
    rows = [_center(chu_de="Trả góp", noi_dung="0%\nSỐ LIỆU CHÍNH THỨC", loai="verbatim")]
    result = parse_center_faq(rows, [])
    assert "Trả góp" not in result.verbatim_map
    assert any("khả nghi" in e for e in result.errors)


def test_faq_one_row_one_doc_with_unique_doc_id():
    rows = [_faq(cau_hoi=f"Q{i}", tra_loi=f"A{i}") for i in range(3)]
    result = parse_center_faq([], rows)
    assert len(result.docs) == 3
    # centre-wide FAQ all share course_id="" → doc_id is what keeps dedupe honest (C1)
    assert all(d.metadata["course_id"] == "" for d in result.docs)
    assert len({d.metadata["doc_id"] for d in result.docs}) == 3


def test_faq_keywords_ride_in_page_content():
    result = parse_center_faq([], [_faq(cau_hoi="Học phí?", tra_loi="Xem khóa",
                                        tu_khoa="hoc phi, hp")])
    content = result.docs[0].page_content
    assert content.startswith("Q: Học phí?\nA: Xem khóa")
    assert "Từ khóa: hoc phi, hp" in content


def test_half_filled_faq_row_skipped():
    result = parse_center_faq([], [_faq(cau_hoi="Q1"), _faq(cau_hoi="Q2", tra_loi="A2")])
    assert len(result.docs) == 1
    assert result.errors


def test_missing_tabs_are_not_fatal():
    result = parse_center_faq([], [])
    assert result.always_text == "" and result.docs == []


def test_malformed_tab_degrades_only_that_tab():
    result = parse_center_faq([{"wrong": "cols"}], [_faq(cau_hoi="Q", tra_loi="A")])
    assert len(result.docs) == 1                       # FAQ still parsed
    assert any("Center" in e for e in result.errors)


def test_missing_required_verbatim_topics_warns():
    result = parse_center_faq(REQUIRED_TOPICS[:1], [])
    assert any("Test đầu vào" in e and "Cam kết gọi lại" in e for e in result.errors)

    complete = parse_center_faq(REQUIRED_TOPICS, [])
    assert not complete.errors
