"""Provider registry. Multi-provider LLM dispatch.

Each provider client implements the same interface as ``AnthropicClient``:

    complete(system, messages, tools=None, budget=None, ...) -> LLMResponse
    complete_async(system, messages, tools=None, budget=None, ...) -> LLMResponse

Accepting Anthropic-format messages/tools and returning a
``maverick.llm.LLMResponse``. OpenAI/OpenRouter/Ollama/Gemini clients
translate the format on the fly.
"""
from __future__ import annotations

from typing import Any, Optional


def get_provider_client(name: str, api_key: Optional[str] = None) -> Any:
    """Lazy-import and instantiate the named provider client."""
    if name == "anthropic":
        from .anthropic_provider import AnthropicClient
        return AnthropicClient(api_key=api_key)
    if name == "openai":
        from .openai_provider import OpenAIClient
        return OpenAIClient(api_key=api_key)
    if name == "openrouter":
        from .openrouter_provider import OpenRouterClient
        return OpenRouterClient(api_key=api_key)
    if name == "ollama":
        from .ollama_provider import OllamaClient
        return OllamaClient()
    if name == "gemini":
        from .gemini_provider import GeminiClient
        return GeminiClient(api_key=api_key)
    raise ValueError(
        f"unknown provider {name!r}. Available: "
        "anthropic, openai, openrouter, ollama, gemini"
    )


KNOWN_PROVIDERS = ("anthropic", "openai", "openrouter", "ollama", "gemini")


__all__ = ["get_provider_client", "KNOWN_PROVIDERS"]
