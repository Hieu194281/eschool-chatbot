"""Flatten a LangChain message `.content` to plain text (provider-agnostic).

Providers differ in the shape of `AIMessage.content`:
- OpenAI  → a plain `str`.
- Gemini 2.5 → a LIST of content blocks, e.g.
    [{"type": "text", "text": "...", "extras": {"signature": "<base64>"}}]
  where `extras.signature` is a base64 "thought signature".

Any consumer that treats content as text (reply extraction, pricing_guard) MUST
flatten first. Using `str(content)` on the list leaks the raw repr — and worse,
the base64 signature contains `<digit>K` runs that the money tokenizer parses as
bogus prices (e.g. "8K" → 8000), causing FALSE pricing-guard violations.
"""

from __future__ import annotations


def content_to_text(content) -> str:
    """Return only the human-readable text of a message content (no signatures)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts).strip()
    return str(content) if content else ""
