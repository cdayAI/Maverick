"""Browser-session providers.

Lets users drive Maverick agents using their existing consumer
chat subscriptions (ChatGPT Plus, Claude.ai, Kimi.com, ...) instead
of (or alongside) a paid API key.

Mechanism: the user signs into the provider in their normal browser,
copies the session cookie, and pastes it into Maverick. The agent
replays that cookie against the same internal endpoints the web UI
uses.

Limitations users must be aware of (surfaced in the wizard):
  - Consumer chat does NOT expose native tool-use for most providers.
    Session clients are best for roles that don't need tools:
    summarizer, writer, analyst, skill_distiller.
  - Cookies expire frequently (~1h for ChatGPT). Re-paste on expiry.
  - Programmatic use of consumer subscriptions is a gray area under
    each provider's ToS. Maverick only operates on the user's own
    account using their own session, and never bypasses CAPTCHA or
    rate limits.

Spec format in config.toml / model_for_role overrides:
    orchestrator = "chatgpt-session:gpt-4o"
    summarizer   = "chatgpt-session:gpt-4o-mini"
"""
from __future__ import annotations

from typing import Any


_SESSION_PROVIDERS = {
    "chatgpt-session": ("chatgpt", "openai-session"),
}


def _canonical(name: str) -> str:
    lower = (name or "").strip().lower()
    if lower in _SESSION_PROVIDERS:
        return lower
    for canon, aliases in _SESSION_PROVIDERS.items():
        if lower in aliases:
            return canon
    return lower


def is_session_provider(name: str) -> bool:
    """True if ``name`` (or one of its aliases) names a session provider."""
    return _canonical(name) in _SESSION_PROVIDERS


def get_session_client(name: str) -> Any:
    """Lazy-instantiate the named session client."""
    canon = _canonical(name)
    if canon == "chatgpt-session":
        from .chatgpt_session import ChatGPTSessionClient
        return ChatGPTSessionClient()
    raise ValueError(
        f"unknown session provider {name!r}. Available: "
        + ", ".join(KNOWN_SESSION_PROVIDERS)
    )


KNOWN_SESSION_PROVIDERS = tuple(_SESSION_PROVIDERS.keys())


__all__ = [
    "get_session_client", "is_session_provider", "KNOWN_SESSION_PROVIDERS",
]
