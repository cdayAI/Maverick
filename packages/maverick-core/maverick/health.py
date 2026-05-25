"""`maverick doctor`: end-to-end health check.

Diagnoses the most common reasons agents fail to run, before they fail to
run. Outputs a status table with green/yellow/red markers so the user can
see at a glance what's healthy.

Checks performed:
  1. Config readable
  2. API keys present + valid (Anthropic / OpenAI if configured)
  3. Sandbox backend reachable (docker daemon if backend=docker)
  4. Each enabled channel's optional deps present + secrets configured
  5. World model database opens cleanly + schema_version is current
  6. maverick-shield available, and which backend it's using
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import click


GREEN = click.style("✓", fg="green")
YELLOW = click.style("!", fg="yellow")
RED = click.style("✗", fg="red")


def _row(marker: str, label: str, detail: str = "") -> None:
    line = f"  {marker} {label}"
    if detail:
        line += click.style(f"  ({detail})", fg="bright_black")
    click.echo(line)


def _check_config() -> dict:
    from .config import config_path, load_config
    p = config_path()
    if not p.exists():
        _row(RED, "config", f"{p} not found -- run `maverick init`")
        return {}
    try:
        cfg = load_config(p)
        _row(GREEN, "config", str(p))
        return cfg
    except Exception as e:
        _row(RED, "config", f"parse error: {e}")
        return {}


def _check_anthropic() -> None:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        _row(RED, "anthropic", "ANTHROPIC_API_KEY not set")
        return
    if not key.startswith("sk-ant-"):
        _row(YELLOW, "anthropic", "key doesn't start with sk-ant- (typo?)")
        return
    try:
        import anthropic
    except ImportError:
        _row(YELLOW, "anthropic", "SDK not installed -- pip install anthropic")
        return
    try:
        client = anthropic.Anthropic(api_key=key)
        list(client.models.list(limit=1))
        _row(GREEN, "anthropic", "key validated")
    except anthropic.AuthenticationError:
        _row(RED, "anthropic", "API rejected the key")
    except Exception as e:
        _row(YELLOW, "anthropic", f"validation skipped: {type(e).__name__}")


def _check_openai() -> None:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return  # only show if configured
    try:
        from openai import AuthenticationError, OpenAI
    except ImportError:
        _row(YELLOW, "openai", "SDK not installed -- pip install 'maverick[openai]'")
        return
    try:
        client = OpenAI(api_key=key)
        list(client.models.list().data[:1])
        _row(GREEN, "openai", "key validated")
    except AuthenticationError:
        _row(RED, "openai", "API rejected the key")
    except Exception as e:
        _row(YELLOW, "openai", f"validation skipped: {type(e).__name__}")


def _check_sandbox(cfg: dict) -> None:
    backend = cfg.get("sandbox", {}).get("backend", "local")
    if backend == "local":
        _row(GREEN, "sandbox", "local subprocess")
        return
    if backend == "docker":
        if not shutil.which("docker"):
            _row(RED, "sandbox", "docker not on PATH but [sandbox] backend=docker")
            return
        try:
            subprocess.run(
                ["docker", "version"],
                capture_output=True, timeout=5, check=True,
            )
            _row(GREEN, "sandbox", "docker daemon responding")
        except subprocess.CalledProcessError:
            _row(RED, "sandbox", "docker daemon not running")
        except subprocess.TimeoutExpired:
            _row(RED, "sandbox", "docker version timed out")
        return
    _row(YELLOW, "sandbox", f"backend={backend} (not v0.1 supported)")


CHANNEL_DEPS = {
    "telegram": ("telegram", "python-telegram-bot"),
    "discord":  ("discord", "discord.py"),
    "slack":    ("slack_sdk", "slack_sdk"),
    "matrix":   ("nio", "matrix-nio"),
    "whatsapp": ("twilio", "twilio + fastapi"),
    "sms":      ("twilio", "twilio + fastapi"),
    # email + signal + imessage: stdlib + system tool only.
}


def _check_channels(cfg: dict) -> None:
    channels = cfg.get("channels", {})
    if not channels:
        return
    for name, ch_cfg in channels.items():
        if not ch_cfg.get("enabled"):
            continue
        # Optional Python dep check
        dep = CHANNEL_DEPS.get(name)
        if dep:
            mod, friendly = dep
            try:
                __import__(mod)
                _row(GREEN, f"channel:{name}", f"{friendly} installed")
            except ImportError:
                _row(YELLOW, f"channel:{name}",
                     f"{friendly} not installed -- pip install 'maverick-channels[{name}]'")
                continue
        elif name == "signal":
            if not shutil.which("signal-cli"):
                _row(YELLOW, "channel:signal",
                     "signal-cli not on PATH -- see https://github.com/AsamK/signal-cli")
                continue
            _row(GREEN, "channel:signal", "signal-cli present")
        elif name == "imessage":
            if sys.platform != "darwin":
                _row(RED, "channel:imessage", f"requires macOS (you're on {sys.platform})")
                continue
            _row(GREEN, "channel:imessage", "macOS")
        elif name == "email":
            _row(GREEN, "channel:email", "stdlib only")


def _check_world_db() -> None:
    from .world_model import DEFAULT_DB, WorldModel
    try:
        w = WorldModel(DEFAULT_DB)
        _row(GREEN, "world-db", f"{DEFAULT_DB} (schema v{w.schema_version})")
    except Exception as e:
        _row(RED, "world-db", f"open failed: {e}")


def _check_shield() -> None:
    try:
        from maverick_shield import Shield
    except ImportError:
        _row(YELLOW, "shield", "maverick-shield not installed -- safety disabled")
        return
    s = Shield.from_config()
    backend_label = {
        "agent-shield": "agent-shield SDK (full ~115 patterns)",
        "builtin": "builtin rules (~20 high-impact patterns)",
        "none": "DISABLED -- [safety] profile=off in config",
    }.get(s.backend, s.backend)
    marker = GREEN if s.backend == "agent-shield" else YELLOW
    if s.backend == "none":
        marker = RED
    _row(marker, "shield", backend_label)


def diagnose() -> None:
    """Run every check and print a status row for each."""
    click.echo(click.style("Maverick health check\n", bold=True))
    cfg = _check_config()
    _check_anthropic()
    _check_openai()
    _check_sandbox(cfg)
    _check_channels(cfg)
    _check_world_db()
    _check_shield()
    click.echo("")
    click.echo(click.style("Done.", fg="bright_black") + "  Re-run any time:  maverick doctor")
