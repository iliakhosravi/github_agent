"""Pluggable LLM factory.

Swapping the model is a config change, not a code change:

    LLM_PROVIDER=anthropic
    LLM_MODEL=claude-sonnet-4-5

A request may also override it per call by passing {"provider": ..., "model": ...}
to /api/chat. Adding a new provider means one entry in `_BUILDERS`.
"""
from __future__ import annotations

import os
from typing import Any, Callable

from langchain_core.language_models.chat_models import BaseChatModel

from ..services.errors import ConfigError


def _openai(model: str, **kw: Any) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=model, **kw)


def _azure_openai(model: str, **kw: Any) -> BaseChatModel:
    from langchain_openai import AzureChatOpenAI

    return AzureChatOpenAI(azure_deployment=model, **kw)


def _anthropic(model: str, **kw: Any) -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    kw.setdefault("max_tokens", 8192)
    return ChatAnthropic(model=model, **kw)


def _google(model: str, **kw: Any) -> BaseChatModel:
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(model=model, **kw)


def _groq(model: str, **kw: Any) -> BaseChatModel:
    from langchain_groq import ChatGroq

    return ChatGroq(model=model, **kw)


def _ollama(model: str, **kw: Any) -> BaseChatModel:
    from langchain_ollama import ChatOllama

    base_url = os.getenv("OLLAMA_BASE_URL")
    if base_url:
        kw.setdefault("base_url", base_url)
    return ChatOllama(model=model, **kw)


_BUILDERS: dict[str, Callable[..., BaseChatModel]] = {
    "openai": _openai,
    "azure_openai": _azure_openai,
    "anthropic": _anthropic,
    "google": _google,
    "google_genai": _google,
    "groq": _groq,
    "ollama": _ollama,
}


def available_providers() -> list[str]:
    return sorted(_BUILDERS)


def build_llm(
    provider: str,
    model: str,
    *,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    **extra: Any,
) -> BaseChatModel:
    provider = (provider or "").strip().lower()
    builder = _BUILDERS.get(provider)
    if builder is None:
        raise ConfigError(
            f"Unknown LLM provider '{provider}'. Available: {', '.join(available_providers())}"
        )

    kwargs: dict[str, Any] = {"temperature": temperature, **extra}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens

    try:
        return builder(model, **kwargs)
    except ImportError as exc:
        raise ConfigError(
            f"Provider '{provider}' is selected but its package is not installed "
            f"({exc}). Install it, e.g. `pip install langchain-{provider.replace('_', '-')}`."
        ) from exc


def build_llm_from_config(config, overrides: dict | None = None) -> BaseChatModel:
    overrides = overrides or {}
    return build_llm(
        overrides.get("provider") or config["LLM_PROVIDER"],
        overrides.get("model") or config["LLM_MODEL"],
        temperature=float(
            overrides.get("temperature", config["LLM_TEMPERATURE"])
        ),
        max_tokens=overrides.get("max_tokens") or config["LLM_MAX_TOKENS"],
    )
