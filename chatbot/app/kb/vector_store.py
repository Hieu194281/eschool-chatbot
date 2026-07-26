"""KnowledgeBase — in-context course catalog + FAQ/Center vector store, published
as a single lock-free, atomically-swapped snapshot (red-team #15).

Schema v2 split:
- Courses (prose + verbatim facts) live in the SYSTEM PROMPT, not the vector store.
  Retrieval can no longer miss a course, at any catalog size.
- The vector store holds ONLY FAQ rows + `Center.loai=embed` rows.

Concurrency model (unchanged):
- `rebuild()` runs OFF the event loop (BackgroundScheduler thread, or a thread
  executor on startup). The Gemini embedding network call happens holding NO lock.
- The active KB is one immutable `_Snapshot`. Publishing is ONE attribute rebind,
  atomic under the GIL — readers never see a half-built store or a catalog/facts
  desync. Every new field MUST live inside the snapshot for that reason.
- On rebuild failure the old snapshot keeps serving (last-good).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..config import get_settings
from .catalog_assembler import (
    CATALOG_INDEX_THRESHOLD,           # noqa: F401 — re-exported for callers/tests
    build_catalog_text,
    warn_if_oversized,
)
from .center_faq_parser import parse_center_faq
from .course_parser import parse_courses
from .sheet_loader import load_kb

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Snapshot:
    store: object                                    # InMemoryVectorStore
    facts_map: dict = field(default_factory=dict)    # cid -> verbatim facts
    course_index: dict = field(default_factory=dict) # cid -> 1-line index entry
    course_blocks: dict = field(default_factory=dict)# cid -> detail block
    center_always: str = ""
    verbatim_map: dict = field(default_factory=dict) # chu_de -> verbatim str
    meta: dict = field(default_factory=dict)         # cid -> {ten_khoa, tu_khoa}
    version: tuple = ()                              # (courses, docs) — logged stamp


class KnowledgeBase:
    def __init__(self) -> None:
        self._snapshot: _Snapshot | None = None
        self._embeddings = None
        self._error_callback = self._default_error_callback

    # ── setup ────────────────────────────────────────────────
    def set_error_callback(self, callback) -> None:
        self._error_callback = callback

    def _ensure_embeddings(self):
        if self._embeddings is None:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            settings = get_settings()
            self._embeddings = GoogleGenerativeAIEmbeddings(
                model=settings.gemini_embed_model,
                google_api_key=settings.google_api_key,
            )
        return self._embeddings

    @staticmethod
    def _default_error_callback(errors: list[str]) -> None:
        for line in errors:
            logger.warning("KB sync issue: %s", line)

    # ── rebuild (runs off the event loop) ────────────────────
    def rebuild(self) -> list[str]:
        """Full KB rebuild. Returns validation errors (for alerting).

        Blocking/synchronous by design — call from a thread, never the event loop.
        """
        try:
            from langchain_core.documents import Document
            from langchain_core.vectorstores import InMemoryVectorStore

            rows = load_kb()
            courses = parse_courses(rows.courses)
            center_faq = parse_center_faq(rows.center, rows.faq)

            # ONLY FAQ + Center embed docs — course text never reaches the store.
            documents = [
                Document(page_content=d.page_content, metadata=d.metadata)
                for d in center_faq.docs
            ]
            store = InMemoryVectorStore(self._ensure_embeddings())
            if documents:
                store.add_documents(documents)   # ← embed network call, no lock held

            self._snapshot = _Snapshot(
                store=store,
                facts_map=courses.facts_map,
                course_index=courses.course_index,
                course_blocks=courses.course_blocks,
                center_always=center_faq.always_text,
                verbatim_map=center_faq.verbatim_map,
                meta=courses.course_meta,
                version=(len(courses.course_blocks), len(documents)),
            )
            errors = rows.errors + courses.errors + center_faq.errors
            self._log_stamp(len(documents), len(errors))
            if errors:
                self._safe_alert(errors)
            return errors
        except Exception as exc:                  # keep last-good snapshot serving
            logger.exception("KB rebuild failed; keeping last-good snapshot")
            self._safe_alert([f"KB sync thất bại: {exc}"])
            return [str(exc)]

    def _log_stamp(self, doc_count: int, error_count: int) -> None:
        n_courses = len(self._snapshot.course_blocks)
        approx_tokens = len(self.get_catalog_text()) // 4      # rough, for trend only
        logger.info("KB rebuilt: courses=%d catalog_tokens≈%d docs=%d errors=%d",
                    n_courses, approx_tokens, doc_count, error_count)
        warn_if_oversized(logger, n_courses)

    def _safe_alert(self, errors: list[str]) -> None:
        try:
            self._error_callback(errors)
        except Exception:
            logger.exception("KB error callback failed")

    # ── lock-free readers ────────────────────────────────────
    def retrieve(self, query: str, k: int = 5) -> list[dict]:
        """FAQ + Center hits only. Course questions are answered from the prompt."""
        snap = self._snapshot                     # atomic read
        if snap is None:
            return []
        return [
            {
                "text": hit.page_content,
                "source": hit.metadata.get("source", ""),
                "doc_id": hit.metadata.get("doc_id", ""),
                "course_id": hit.metadata.get("course_id", ""),
            }
            for hit in snap.store.similarity_search(query, k=k)
        ]

    def get_catalog_text(self) -> str:
        snap = self._snapshot
        if snap is None:
            return ""
        return build_catalog_text(snap.course_index, snap.course_blocks)

    def get_center_always(self) -> str:
        snap = self._snapshot
        return snap.center_always if snap else ""

    def get_facts(self, course_id: str) -> str:
        snap = self._snapshot
        return snap.facts_map.get(course_id, "") if snap else ""

    def get_all_courses(self) -> list[dict]:
        """Every course with its verbatim facts — the guard's allowed-set source.

        A dict walk over in-memory data: 0 tokens, no similarity search, so the
        guard sees the WHOLE catalog regardless of catalog mode or size.
        """
        snap = self._snapshot
        if snap is None:
            return []
        return [
            {
                "course_id": cid,
                "ten_khoa": snap.meta.get(cid, {}).get("ten_khoa", ""),
                "tu_khoa": snap.meta.get(cid, {}).get("tu_khoa", []),
                "facts": facts,
            }
            for cid, facts in snap.facts_map.items()
        ]

    def get_verbatim_map(self) -> dict:
        """Centre-level text the sales layer quotes word-for-word (Phase 04/05)."""
        snap = self._snapshot
        return dict(snap.verbatim_map) if snap else {}

    def get_meta(self, course_id: str) -> dict:
        snap = self._snapshot
        return snap.meta.get(course_id, {}) if snap else {}

    @property
    def ready(self) -> bool:
        return self._snapshot is not None


# Module singleton (embeddings created lazily on first rebuild — safe to import).
knowledge_base = KnowledgeBase()
