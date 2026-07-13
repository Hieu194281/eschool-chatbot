"""Knowledge-base layer: Sheet sync → validate → embed → atomic snapshot.

Exposes the singleton `knowledge_base`. Golden rule enforced here at the data
layer: học phí/ưu đãi live in structured columns, injected VERBATIM, NEVER embedded.
"""

from .vector_store import KnowledgeBase, knowledge_base

__all__ = ["KnowledgeBase", "knowledge_base"]
