"""Knowledge-base layer: Sheet sync → validate → in-context catalog + vector store.

Exposes the singleton `knowledge_base`. Golden rule enforced here at the data
layer: the 9 verbatim columns (học phí, ưu đãi, khai giảng, …) are injected
word-for-word under a trust marker and are NEVER embedded.
"""

from .center_faq_parser import CenterFaqResult, parse_center_faq
from .course_parser import KbSchemaError, ParseResult, parse_courses
from .sheet_loader import KbRows, load_kb
from .vector_store import KnowledgeBase, knowledge_base

__all__ = [
    "KnowledgeBase",
    "knowledge_base",
    "KbRows",
    "load_kb",
    "KbSchemaError",
    "ParseResult",
    "parse_courses",
    "CenterFaqResult",
    "parse_center_faq",
]
