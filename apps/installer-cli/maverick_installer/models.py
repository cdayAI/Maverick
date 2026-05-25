"""Curated catalog of supported models per provider.

Updated whenever providers ship new models. Each entry has an id, a
notes string the wizard shows, and a status marker.

All four providers are now wired up (anthropic, openai, openrouter,
ollama). Picking any of them in the wizard generates a config that the
agent kernel actually dispatches to via the multi-provider LLM facade.
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
        "status": "ready",
        "label": "OpenAI",
        "env": "OPENAI_API_KEY",
        "models": [
            {"id": "gpt-4o",      "notes": "Multimodal, smart, balanced."},
            {"id": "gpt-4o-mini", "notes": "Cheaper, fast."},
            {"id": "o1",          "notes": "Long-form reasoning. Slow but deep."},
        ],
    },
    "openrouter": {
        "status": "ready",
        "label": "OpenRouter (200+ models via one API)",
        "env": "OPENROUTER_API_KEY",
        "models": [
            {"id": "auto",                       "notes": "OpenRouter picks for you."},
            {"id": "meta-llama/llama-3.3-70b",  "notes": "Open weight, strong general."},
            {"id": "google/gemini-pro-1.5",     "notes": "Long context."},
            {"id": "deepseek/deepseek-r1",      "notes": "Strong reasoning, cheap."},
        ],
    },
    "ollama": {
        "status": "ready",
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
