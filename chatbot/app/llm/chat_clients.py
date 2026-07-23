"""Cached chat clients via LangChain's provider-agnostic `init_chat_model`.

Switching LLM provider is an .env change, NOT a code change — the model id in
settings carries the provider prefix and init_chat_model picks the right class:

    LLM_MODEL_MAIN=openai:gpt-4o-mini              # OpenAI  (needs langchain-openai)
    LLM_MODEL_MAIN=google_genai:gemini-2.5-flash   # Gemini  (needs langchain-google-genai)
    LLM_MODEL_MAIN=anthropic:claude-...            # Claude  (needs langchain-anthropic)

Point at an OpenAI-COMPATIBLE gateway (ViRouter, OpenRouter, LiteLLM proxy, a
local vLLM server, …) by keeping the `openai:` provider and setting LLM_BASE_URL.
The part after `openai:` is sent verbatim as the gateway's `model` id.

- main:  agent — temp 0.6 (some warmth in sales talk).
- lite:  grade + reflect — temp 0 (deterministic-ish).

Nodes only ever see the abstract BaseChatModel (.bind_tools / .with_structured_output
/ .ainvoke), so they are provider-agnostic and never import a vendor class.
"""

from functools import lru_cache

from ..config import get_settings


def _build_client(model_id: str, temperature: float):
    """Provider-agnostic client. Adds base_url only when a gateway is configured."""
    from langchain.chat_models import init_chat_model

    settings = get_settings()
    kwargs = {
        "api_key": settings.llm_api_key or None,   # None → fall back to provider env var
        "temperature": temperature,
    }
    # base_url + Chat-Completions pin apply ONLY to the openai provider (gateways like
    # ViRouter). Other providers (google_genai, anthropic) reject these kwargs, so
    # gating on the prefix keeps provider-switching a pure .env change.
    if model_id.startswith("openai:") and settings.llm_base_url:   # OpenAI-compatible gateway
        kwargs["base_url"] = settings.llm_base_url
        # Gateways speak the Chat Completions API, not OpenAI's newer Responses API.
        # Without this, langchain may emit Responses-style function calls (`fc_…` ids)
        # the gateway can't pair with tool outputs → 400 "No tool output found".
        kwargs["use_responses_api"] = False
    return init_chat_model(model_id, **kwargs)


@lru_cache
def main_llm():
    return _build_client(get_settings().llm_model_main, temperature=0.6)


@lru_cache
def lite_llm():
    return _build_client(get_settings().llm_model_lite, temperature=0.0)
