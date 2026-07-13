"""Cached Gemini chat clients.

- main:  Gemini 2.5 Flash, temp ~0.6 (agent — some warmth in sales talk).
- lite:  Gemini 2.5 Flash-Lite, temp 0 (grade + reflect — deterministic-ish).

Model IDs come from config, never hardcoded, so a rename is a .env change.
"""

from functools import lru_cache

from ..config import get_settings


@lru_cache
def main_llm():
    from langchain_google_genai import ChatGoogleGenerativeAI

    settings = get_settings()
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model_main,
        google_api_key=settings.google_api_key,
        temperature=0.6,
    )


@lru_cache
def lite_llm():
    from langchain_google_genai import ChatGoogleGenerativeAI

    settings = get_settings()
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model_lite,
        google_api_key=settings.google_api_key,
        temperature=0.0,
    )
