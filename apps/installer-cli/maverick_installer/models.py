"""Curated catalog of supported models per provider.

Updated whenever providers ship new models. Each entry has an id, a
notes string the wizard shows, and a status marker.

The wizard surfaces every entry but warns clearly when a provider is
not yet wired up in the agent loop (status='planned').
"""

ROLES: list[tuple[str, str]] = [
    ("orchestrator",    "Plans, decomposes, verifies. Wants the smartest model."),
    ("researcher",      "Searches, gathers info. Workhorse role."),
    ("coder",           "Writes and tests code. Wants strong code performance."),
    ("writer",          "Drafts long prose. Quality matters."),
    ("analyst",         "Synthesizes findings. Reasoning-heavy."),
    ("revisor",         "Second-pass review when verify fails. Smart model."),
    ("summarizer",      "Cheap distillation. Tiny model is fine."),
    ("skill_distiller", "Turns trajectories into reusable skills."),
]


# status: "ready" (works today) | "planned" (config accepted, agent will fall back)
PROVIDERS: dict[str, dict] = {
    "anthropic": {
        "status": "ready",
        "label": "Anthropic Claude",
        "env": "ANTHROPIC_API_KEY",
        "models": [
            {"id": "claude-opus-4-7",   "notes": "Smartest, slowest, most expensive. Best for orchestrator/revisor."},
            {"id": "claude-sonnet-4-6", "notes": "Balanced. Recommended workhorse."},
            {"id": "claude-haiku-4-5",  "notes": "Fast and cheap. Good for summarizer."},
        ],
    },
    "openai": {
        "status": "planned",
        "label": "OpenAI",
        "env": "OPENAI_API_KEY",
        "models": [
            {"id": "gpt-4o",      "notes": "Multimodal, smart, balanced."},
            {"id": "gpt-4o-mini", "notes": "Cheaper, fast."},
            {"id": "o1",          "notes": "Long-form reasoning. Slow but deep."},
        ],
    },
    "openrouter": {
        "status": "planned",
        "label": "OpenRouter (200+ models via one API)",
        "env": "OPENROUTER_API_KEY",
        "models": [
            {"id": "auto",                       "notes": "OpenRouter picks for you."},
            {"id": "meta-llama/llama-3.3-70b",  "notes": "Open weight, strong general."},
        ],
    },
    "ollama": {
        "status": "planned",
        "label": "Ollama (local, free, private)",
        "env": None,
        "models": [
            {"id": "llama3.3:70b",         "notes": "Local, free, requires beefy machine."},
            {"id": "qwen2.5-coder:32b",    "notes": "Local, code-focused."},
            {"id": "phi3:14b",             "notes": "Local, small, fast."},
        ],
    },
}


def default_for_role(role: str) -> str:
    """Return the recommended (provider, model-id) default for a role."""
    return {
        "orchestrator":    "anthropic:claude-opus-4-7",
        "researcher":      "anthropic:claude-sonnet-4-6",
        "coder":           "anthropic:claude-sonnet-4-6",
        "writer":          "anthropic:claude-sonnet-4-6",
        "analyst":         "anthropic:claude-sonnet-4-6",
        "revisor":         "anthropic:claude-opus-4-7",
        "summarizer":      "anthropic:claude-haiku-4-5",
        "skill_distiller": "anthropic:claude-sonnet-4-6",
    }[role]
