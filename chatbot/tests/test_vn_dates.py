"""Date/time tokenizer — must not overlap with the money tokenizer (H2)."""

from app.common.vn_dates import DateToken, iter_date_tokens, token_allowed
from app.common.vn_numerals import iter_money_tokens


def _tokens(text):
    return list(iter_date_tokens(text))


def test_dd_mm_parsed():
    (tok,) = _tokens("khai giảng 05/08 ạ")
    assert (tok.kind, tok.day, tok.month, tok.year) == ("date", 5, 8, None)


def test_dd_mm_yyyy_parsed():
    (tok,) = _tokens("khai giảng 05/08/2026")
    assert (tok.day, tok.month, tok.year) == (5, 8, 2026)


def test_two_digit_year_expanded():
    (tok,) = _tokens("05/08/26")
    assert tok.year == 2026


def test_ngay_thang_form():
    (tok,) = _tokens("ngày 5 tháng 8")
    assert (tok.day, tok.month) == (5, 8)


def test_bare_ngay_has_unknown_month():
    (tok,) = _tokens("khai giảng ngày 12 ạ")
    assert (tok.day, tok.month) == (12, None)


def test_impossible_calendar_pair_ignored():
    assert _tokens("tỉ lệ 20/45") == []


def test_hour_forms_normalize_equal():
    (short,) = _tokens("18h")
    (padded,) = _tokens("18h00")
    (colon,) = _tokens("18:00")
    assert short.minutes == padded.minutes == colon.minutes == 18 * 60


def test_time_range_yields_two_tokens():
    toks = _tokens("18h-19h30")
    assert [t.minutes for t in toks] == [18 * 60, 19 * 60 + 30]


def test_short_bare_hour_is_a_duration_not_a_time():
    # "mỗi buổi 2h" is a length, not 02:00 — reading it as a time over-blocks.
    assert _tokens("mỗi buổi 2h") == []
    assert _tokens("mỗi buổi 2h30")[0].minutes == 150   # explicit minutes → real token


def test_h_starting_a_word_is_not_an_hour_marker():
    # "lớp 7 học" was read as 07:00 — blocked valid replies AND swallowed the "7"
    # that identifies the course.
    assert _tokens("lớp 7 học vào tối thứ 3") == []
    assert _tokens("9 học viên/lớp") == []
    assert _tokens("18h30")[0].minutes == 18 * 60 + 30   # digits after h still fine


# ── no interference with the money tokenizer ─────────────────
def test_price_is_not_read_as_a_date():
    assert _tokens("học phí 1.800.000đ") == []


def test_date_is_not_read_as_money():
    assert list(iter_money_tokens("khai giảng 05/08")) == []


def test_phone_number_is_neither():
    assert _tokens("0912345678") == []


# ── matching semantics ───────────────────────────────────────
def test_missing_year_is_a_wildcard_both_ways():
    kb = [DateToken("05/08/2026", "date", 5, 8, 2026)]
    assert token_allowed(DateToken("05/08", "date", 5, 8), kb) is True
    kb_no_year = [DateToken("05/08", "date", 5, 8)]
    assert token_allowed(DateToken("05/08/2026", "date", 5, 8, 2026), kb_no_year) is True


def test_different_year_rejected():
    kb = [DateToken("05/08/2026", "date", 5, 8, 2026)]
    assert token_allowed(DateToken("05/08/2027", "date", 5, 8, 2027), kb) is False


def test_date_never_matches_a_time():
    kb = [DateToken("18h00", "time", minutes=1080)]
    assert token_allowed(DateToken("05/08", "date", 5, 8), kb) is False


def test_empty_allowed_set_rejects():
    assert token_allowed(DateToken("05/08", "date", 5, 8), []) is False
