"""Maverick interactive installer.

A friendly, opinionated walk-through. Sets up:
  - deployment target
  - AI providers and per-role models
  - safety profile
  - sandbox backend
  - budget caps
  - API keys (stored in ~/.maverick/.env, referenced from config.toml via ${VAR})

Writes ~/.maverick/config.toml and ~/.maverick/.env. The agent reads from there.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel

try:
    import questionary
except ImportError:  # pragma: no cover
    questionary = None  # type: ignore

from . import models as catalog


CONFIG_DIR = Path.home() / ".maverick"
CONFIG_FILE = CONFIG_DIR / "config.toml"
ENV_FILE = CONFIG_DIR / ".env"

console = Console()


# ---------- prompt primitives (questionary if available, plain stdin otherwise) ----------

def _q_select(message: str, choices: list[str], default: str | None = None) -> str:
    if questionary is None:
        print(message)
        for i, c in enumerate(choices):
            marker = "*" if default == c else " "
            print(f"  {marker} {i+1}) {c}")
        while True:
            choice = input("> ").strip()
            if not choice and default:
                return default
            if choice.isdigit() and 1 <= int(choice) <= len(choices):
                return choices[int(choice) - 1]
    return questionary.select(message, choices=choices, default=default).ask()


def _q_text(message: str, default: str = "") -> str:
    if questionary is None:
        val = input(f"{message} [{default}]: ").strip()
        return val or default
    return questionary.text(message, default=default).ask()


def _q_checkbox(message: str, choices: list[str], default: list[str] | None = None) -> list[str]:
    if questionary is None:
        print(f"{message} (comma-separated numbers)")
        for i, c in enumerate(choices):
            marker = "*" if default and c in default else " "
            print(f"  {marker} {i+1}) {c}")
        raw = input("> ").strip()
        if not raw and default:
            return default
        picks = [c.strip() for c in raw.split(",")]
        return [choices[int(p) - 1] for p in picks if p.isdigit() and 1 <= int(p) <= len(choices)]
    return questionary.checkbox(message, choices=choices, default=default).ask()


def _q_confirm(message: str, default: bool = True) -> bool:
    if questionary is None:
        val = input(f"{message} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
        if not val:
            return default
        return val.startswith("y")
    return questionary.confirm(message, default=default).ask()


# ---------- wizard steps ----------

def welcome() -> None:
    console.print(Panel.fit(
        "[bold cyan]Welcome to Maverick.[/bold cyan]\n\n"
        "An AI agent you fully control — pick your models, your safety\n"
        "level, your deployment target. Privacy-first, safety by default.\n\n"
        "This wizard takes about 2 minutes. You can re-run it any time:\n"
        "  [bold]maverick init[/bold]",
        title="Maverick Installer",
        border_style="cyan",
    ))


def pick_deployment() -> str:
    pick = _q_select(
        "Where will Maverick run?",
        [
            "desktop  - This computer (recommended for first-time users)",
            "docker   - Local Docker container (isolated, easy to remove)",
            "vps      - Remote server you own (always-on)",
            "phone    - Phone companion (Maverick runs on desktop/VPS; talk to it from your phone)",
        ],
    )
    return pick.split()[0]


def pick_providers() -> list[str]:
    choices = []
    for prov_id, info in catalog.PROVIDERS.items():
        tag = "[ready]" if info["status"] == "ready" else "[v0.2]"
        choices.append(f"{prov_id:10} {tag} - {info['label']}")

    picks = _q_checkbox(
        "Which AI providers do you want to use? (API keys requested only for the ones you pick.)",
        choices,
        default=[choices[0]],
    )
    return [p.split()[0] for p in picks]


def pick_models_per_role(providers: list[str]) -> dict[str, str]:
    console.print()
    console.print(Panel.fit(
        "[bold]Per-role model assignment[/bold]\n\n"
        "Maverick is a swarm — different roles do different work. Heavy roles\n"
        "(orchestrator, revisor) benefit from a smart model; cheap roles\n"
        "(summarizer) can use a small one. Pick what you want for each.",
        border_style="cyan",
    ))

    role_models: dict[str, str] = {}
    for role, hint in catalog.ROLES:
        choices: list[str] = []
        for prov in providers:
            info = catalog.PROVIDERS.get(prov)
            if not info:
                continue
            tag = "" if info["status"] == "ready" else " [v0.2]"
            for m in info["models"]:
                choices.append(f"{prov}:{m['id']}{tag}  - {m['notes']}")
        choices.append("[skip - use default]")

        default_spec = catalog.default_for_role(role)
        default_choice = next((c for c in choices if c.startswith(default_spec)), choices[0])

        pick = _q_select(f"  {role}: {hint}", choices, default=default_choice)
        if pick.startswith("[skip"):
            continue
        role_models[role] = pick.split()[0]  # "provider:id"
    return role_models


def pick_safety() -> dict[str, Any]:
    pick = _q_select(
        "Safety profile (powered by Agent Shield):",
        [
            "strict     - Block on any medium+ threat. Best for sensitive use.",
            "balanced   - Block on high+ threats. Recommended default.",
            "permissive - Block only on critical threats. For research/experimentation.",
            "off        - No safety scanning. NOT recommended.",
        ],
        default="balanced   - Block on high+ threats. Recommended default.",
    )
    profile = pick.split()[0]
    threshold = {
        "strict": "medium",
        "balanced": "high",
        "permissive": "critical",
        "off": "critical",
    }[profile]
    return {
        "profile": profile,
        "block_threshold": threshold,
        "scan_input": profile != "off",
        "scan_tool_calls": profile != "off",
        "scan_output": profile != "off",
    }


def pick_budget() -> dict[str, float]:
    console.print()
    console.print("[dim]Budget caps prevent runaway costs. Conservative defaults:[/dim]")
    return {
        "max_dollars": float(_q_text("  Max $ per run", default="5.0")),
        "max_wall_seconds": float(_q_text("  Max wall-clock seconds per run", default="3600")),
        "max_tool_calls": int(_q_text("  Max tool calls per run", default="500")),
    }


def pick_sandbox() -> dict[str, Any]:
    pick = _q_select(
        "Sandbox backend (where the agent runs shell commands):",
        [
            "local  - Subprocess on this machine (fastest, least isolated)",
            "docker - Throwaway Docker container (recommended)",
            "ssh    - Remote machine [v0.2]",
        ],
        default="docker - Throwaway Docker container (recommended)",
    )
    backend = pick.split()[0]
    workdir = _q_text("  Workspace directory", default=str(Path.home() / "maverick-workspace"))
    return {"backend": backend, "workdir": workdir, "timeout": 60}


def collect_api_keys(providers: list[str]) -> dict[str, str]:
    keys: dict[str, str] = {}
    for prov in providers:
        info = catalog.PROVIDERS.get(prov, {})
        env_name = info.get("env")
        if not env_name:
            continue
        current = os.environ.get(env_name, "")
        masked = (current[:7] + "...") if current else "(none)"
        val = _q_text(f"  {env_name} [current: {masked}]", default=current)
        if val:
            keys[env_name] = val
    return keys


# ---------- write + verify ----------

def write_config(
    deployment: str,
    providers: list[str],
    role_models: dict[str, str],
    safety: dict[str, Any],
    budget: dict[str, float],
    sandbox: dict[str, Any],
    keys: dict[str, str],
) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if keys:
        ENV_FILE.write_text("\n".join(f"{k}={v}" for k, v in keys.items()) + "\n")
        os.chmod(ENV_FILE, 0o600)

    lines = [
        "# Maverick config. Regenerate with:  maverick init",
        "",
        "[deploy]",
        f'target = "{deployment}"',
        "",
    ]
    for prov in providers:
        info = catalog.PROVIDERS.get(prov, {})
        lines.append(f"[providers.{prov}]")
        env_name = info.get("env")
        if env_name:
            lines.append(f'api_key = "${{{env_name}}}"')
        if prov == "ollama":
            lines.append('base_url = "http://localhost:11434"')
        lines.append("")
    if role_models:
        lines.append("[models]")
        for role, spec in role_models.items():
            lines.append(f'{role} = "{spec}"')
        lines.append("")
    lines.append("[budget]")
    for k, v in budget.items():
        lines.append(f"{k} = {v}")
    lines.append("")
    lines.append("[safety]")
    for k, v in safety.items():
        if isinstance(v, bool):
            lines.append(f"{k} = {str(v).lower()}")
        else:
            lines.append(f'{k} = "{v}"')
    lines.append("")
    lines.append("[sandbox]")
    for k, v in sandbox.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            lines.append(f"{k} = {v}")
        else:
            lines.append(f'{k} = "{v}"')

    CONFIG_FILE.write_text("\n".join(lines) + "\n")
    console.print(f"[green]✓[/green] Wrote {CONFIG_FILE}")
    if keys:
        console.print(f"[green]✓[/green] Wrote {ENV_FILE} (chmod 600)")


def smoke_test() -> bool:
    console.print()
    console.print("[dim]Running smoke test...[/dim]")
    try:
        from maverick.config import load_config
        cfg = load_config()
        assert cfg.get("deploy", {}).get("target"), "deploy target missing"
        console.print("[green]✓[/green] Config readable")
    except Exception as e:
        console.print(f"[red]✗[/red] Config read failed: {e}")
        return False

    try:
        import maverick_shield  # noqa: F401
        console.print("[green]✓[/green] Maverick Shield available")
    except ImportError:
        console.print("[yellow]⚠[/yellow] maverick-shield not installed (safety will be disabled)")

    try:
        import anthropic  # noqa: F401
        console.print("[green]✓[/green] Anthropic SDK available")
    except ImportError:
        console.print("[yellow]⚠[/yellow] anthropic not installed; install with: pip install anthropic")

    return True


def run() -> int:
    welcome()
    deployment = pick_deployment()
    providers = pick_providers()
    if not providers:
        console.print("[red]No providers selected. Aborting.[/red]")
        return 1
    role_models = pick_models_per_role(providers)
    safety = pick_safety()
    budget = pick_budget()
    sandbox = pick_sandbox()
    keys = collect_api_keys(providers)

    console.print()
    if not _q_confirm("Write config and finish?", default=True):
        console.print("Aborted. Nothing written.")
        return 0

    write_config(deployment, providers, role_models, safety, budget, sandbox, keys)
    ok = smoke_test()
    if ok:
        console.print()
        console.print(Panel.fit(
            "[bold green]All set.[/bold green]\n\n"
            "Try:\n"
            '  [bold]maverick start "summarize the latest Anthropic announcements"[/bold]\n'
            "  [bold]maverick status[/bold]\n"
            "  [bold]maverick skills[/bold]",
            border_style="green",
        ))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
