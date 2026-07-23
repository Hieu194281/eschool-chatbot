"""KnowledgeBase — in-memory vector store with a lock-free, atomically-swapped
snapshot (red-team #15).

Concurrency model:
- `rebuild()` runs OFF the event loop (BackgroundScheduler thread, or a thread
  executor on startup). The embedding network call happens while holding
  NO lock.
- The active KB is a single immutable `_Snapshot(store, pricing, meta, version)`.
  Publishing a rebuild is ONE attribute rebind (`self._snapshot = snap`), which is
  atomic under the GIL. Readers grab `self._snapshot` once and use it — so they
  never see a half-built store or a store/pricing desync, and never hold a lock
  across a network call.
- On rebuild failure the old snapshot keeps serving (last-good); the error is
  logged and routed to the error callback (Telegram in Phase 05).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..config import get_settings
from .course_parser import parse_courses
from .sheet_loader import load_courses

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Snapshot:
    store: object            # InMemoryVectorStore
    pricing: dict            # course_id -> verbatim pricing str
    meta: dict               # course_id -> {ten_khoa}
    version: tuple           # (row_count, doc_count) — logged as a stamp


class KnowledgeBase:
    def __init__(self) -> None:
        self._snapshot: _Snapshot | None = None
        self._embeddings = None
        self._error_callback = self._default_error_callback

    # ── setup ────────────────────────────────────────────────
    def set_error_callback(self, callback) -> None:
        """Phase 05 injects a Telegram notifier; default just logs."""
        self._error_callback = callback

    def _ensure_embeddings(self):
        if self._embeddings is None:
            from langchain.embeddings import init_embeddings

            settings = get_settings()
            # Provider-agnostic, same as the chat clients: the embed model id
            # carries the provider prefix (e.g. "openai:text-embedding-3-small").
            kwargs = {"api_key": settings.llm_api_key or None}
            # base_url applies ONLY to the openai provider (gateway like ViRouter);
            # other providers (google_genai, …) reject it. Gate on the prefix so
            # switching the embed provider stays a pure .env change.
            if settings.llm_embed_model.startswith("openai:") and settings.llm_base_url:
                kwargs["base_url"] = settings.llm_base_url
            self._embeddings = init_embeddings(settings.llm_embed_model, **kwargs)
        return self._embeddings

    @staticmethod
    def _default_error_callback(errors: list[str]) -> None:
        for line in errors:
            logger.warning("KB sync issue: %s", line)

    # ── rebuild (runs off the event loop) ────────────────────
    def rebuild(self) -> list[str]:
        """Full KB rebuild. Returns the list of validation errors (for alerting).

        Blocking/synchronous by design — call from a thread (scheduler / executor),
        never directly on the event loop.
        """
        try:
            from langchain_core.documents import Document
            from langchain_core.vectorstores import InMemoryVectorStore

            rows = load_courses()
            parsed = parse_courses(rows)
            documents = [
                Document(page_content=d.page_content, metadata=d.metadata)
                for d in parsed.docs
            ]
            store = InMemoryVectorStore(self._ensure_embeddings())
            if documents:
                store.add_documents(documents)     # ← embed network call, no lock held

            version = (len(rows), len(documents))
            self._snapshot = _Snapshot(store, parsed.pricing_map, parsed.course_meta, version)
            logger.info("KB rebuilt: rows=%d docs=%d errors=%d",
                        version[0], version[1], len(parsed.errors))
            if parsed.errors:
                self._safe_alert(parsed.errors)
            return parsed.errors
        except Exception as exc:                    # keep last-good snapshot serving
            logger.exception("KB rebuild failed; keeping last-good snapshot")
            self._safe_alert([f"KB sync thất bại: {exc}"])
            return [str(exc)]

    def _safe_alert(self, errors: list[str]) -> None:
        try:
            self._error_callback(errors)
        except Exception:
            logger.exception("KB error callback failed")

    # ── lock-free readers ────────────────────────────────────
    def retrieve(self, query: str, k: int = 3) -> list[dict]:
        snap = self._snapshot                        # atomic read
        if snap is None:
            return []
        hits = snap.store.similarity_search(query, k=k)
        results = []
        for hit in hits:
            cid = hit.metadata.get("course_id", "")
            results.append({
                "text": hit.page_content,
                "course_id": cid,
                "ten_khoa": hit.metadata.get("ten_khoa", ""),
                "pricing": snap.pricing.get(cid, ""),
            })
        return results

    def get_pricing(self, course_id: str) -> str:
        snap = self._snapshot
        return snap.pricing.get(course_id, "") if snap else ""

    def get_meta(self, course_id: str) -> dict:
        snap = self._snapshot
        return snap.meta.get(course_id, {}) if snap else {}

    @property
    def ready(self) -> bool:
        return self._snapshot is not None


# Module singleton (embeddings created lazily on first rebuild — safe to import).
knowledge_base = KnowledgeBase()
