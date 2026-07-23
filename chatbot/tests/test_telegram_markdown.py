"""TelegramAdapter Markdown→HTML: bot xuất **đậm** (CommonMark) nhưng Telegram
không render → phải chuyển sang HTML (parse_mode=HTML). Test khoá hành vi + các
biên nguy hiểm (escape, dấu ** lẻ)."""

from app.channel.telegram_adapter import _md_to_telegram_html, _strip_md


def test_double_asterisk_becomes_bold():
    assert _md_to_telegram_html("**Khoá cơ bản:**") == "<b>Khoá cơ bản:</b>"
    assert _md_to_telegram_html("__đậm__") == "<b>đậm</b>"


def test_html_specials_escaped():
    assert _md_to_telegram_html("a < b & c > d") == "a &lt; b &amp; c &gt; d"


def test_escape_runs_before_bold():
    # & bên trong **...** vẫn được escape, thẻ <b> KHÔNG bị escape.
    assert _md_to_telegram_html("**a & b**") == "<b>a &amp; b</b>"


def test_unbalanced_asterisks_stay_literal():
    # ** lẻ (chưa đóng) → không match → giữ nguyên, không sinh HTML hỏng.
    assert _md_to_telegram_html("**chưa đóng") == "**chưa đóng"


def test_plain_text_unchanged():
    assert _md_to_telegram_html("Dạ em chào anh/chị ạ") == "Dạ em chào anh/chị ạ"


def test_strip_md_fallback():
    assert _strip_md("**x** __y__") == "x y"
