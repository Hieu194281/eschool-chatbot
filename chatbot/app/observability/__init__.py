"""Observability wiring — bridge LangSmith settings into the process environment.

pydantic-settings loads `.env` into the `Settings` object, but LangChain's tracer
reads `os.environ` directly. This module copies the LangSmith keys across so tracing
turns on from `.env` alone (no manual `export`). Call `configure_langsmith()` once,
early — from the app lifespan and from any standalone script (playground, verify).
"""

import logging
import os

from ..config import get_settings

logger = logging.getLogger(__name__)


def configure_langsmith() -> bool:
    """Enable LangSmith tracing if turned on + a key is present. Returns True if on.

    No-op (returns False) when LANGSMITH_TRACING is false or the key is blank, so it
    is always safe to call — production stays untraced unless explicitly enabled.
    """
    settings = get_settings()
    if not (settings.langsmith_tracing and settings.langsmith_api_key):
        return False

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    if settings.langsmith_endpoint:
        os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint

    logger.info("LangSmith tracing ENABLED → project=%s", settings.langsmith_project)
    return True


__all__ = ["configure_langsmith"]
