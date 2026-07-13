"""VN-numeral normalizer — the canonicalization the pricing-guard relies on."""

from app.common.vn_numerals import money_values, percent_values


def test_million_forms_equivalent():
    assert money_values("5 triệu") == {5_000_000}
    assert money_values("5triệu") == {5_000_000}
    assert money_values("5tr") == {5_000_000}
    assert money_values("5 củ") == {5_000_000}


def test_compound_million_half():
    assert money_values("4tr5") == {4_500_000}
    assert money_values("4tr500") == {4_500_000}
    assert money_values("4 triệu rưỡi") == {4_500_000}
    assert money_values("4.5 triệu") == {4_500_000}


def test_thousand_forms():
    assert money_values("500k") == {500_000}
    assert money_values("500 nghìn") == {500_000}
    assert money_values("500 ngàn") == {500_000}


def test_grouped_and_bare():
    assert money_values("1.500.000") == {1_500_000}
    assert money_values("1,500,000") == {1_500_000}
    assert money_values("1500000") == {1_500_000}


def test_grouped_equals_compound():
    # Same value written two ways must normalize identically (guard correctness).
    assert money_values("4.500.000") == money_values("4tr5")


def test_non_money_numbers_ignored():
    # class level, session count, dates, years — NOT prices.
    assert money_values("lớp 6-9, 2 buổi/tuần, khai giảng 15/8 năm 2026") == set()


def test_phone_number_not_money():
    assert money_values("gọi 0987654321 nhé") == set()


def test_percentages():
    assert percent_values("giảm 10%") == {10}
    assert money_values("giảm 10%") == set()


def test_mixed_sentence():
    text = "Học phí 5 triệu, ưu đãi còn 4tr5, giảm 10%."
    assert money_values(text) == {5_000_000, 4_500_000}
    assert percent_values(text) == {10}
