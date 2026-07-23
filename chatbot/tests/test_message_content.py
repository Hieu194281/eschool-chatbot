"""content_to_text — flatten provider-specific message content to plain text.

Guards the Gemini list-content bug: content arrives as a list of blocks carrying a
base64 thought-signature that must NEVER leak into the text (it renders as garbage
to the customer and its '<digit>K' runs trip the pricing guard).
"""

from app.common.message_content import content_to_text


def test_string_passthrough():
    assert content_to_text("xin chào") == "xin chào"


def test_gemini_list_blocks_joined():
    content = [{"type": "text", "text": "Phần 1. "}, {"type": "text", "text": "Phần 2."}]
    assert content_to_text(content) == "Phần 1. Phần 2."


def test_signature_extras_dropped():
    content = [{"type": "text", "text": "Giá 5.000.000đ",
                "extras": {"signature": "AAA8K801kBBB"}}]
    out = content_to_text(content)
    assert out == "Giá 5.000.000đ"
    assert "8K" not in out and "signature" not in out


def test_none_and_empty():
    assert content_to_text(None) == ""
    assert content_to_text([]) == ""
