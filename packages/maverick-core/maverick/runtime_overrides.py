"""Dashboard-owned runtime overrides.

The dashboard's permissions page lets a user disable a tool with one
click. Writing that into ``config.toml`` would clobber the user's
hand-tuned, comment-annotated, wizard-generated file. Instead the
dashboard owns a separate ``~/.maverick/runtime-overrides.toml`` that
the kernel unions into the deny-list at registry-build time.

Only a small, well-defined surface lives here today:

    [security]
    denied_tools = ["computer", "browser"]

``tool_acl.resolve_lists`` reads ``denied_tools`` and unions it with
the config + channel + user deny-lists, so a disable takes effect on
the next goal with no restart. config.toml is never touched.
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

OVERRIDES_PATH = Path.home() / ".maverick" / "runtime-overrides.toml"


def _tomllib():
    try:
        import tomllib  # 3.11+
    except ModuleNotFoundError:  # Python 3.10
        import tomli as tomllib  # type: ignore[no-redef]
    return tomllib


def _load() -> dict:
    if not OVERRIDES_PATH.exists():
        return {}
    try:
        with open(OVERRIDES_PATH, "rb") as f:
            return _tomllib().load(f)
    except (OSError, ValueError) as e:
        log.warning("runtime_overrides: cannot read %s: %s", OVERRIDES_PATH, e)
        return {}


def denied_tools() -> set[str]:
    """Tools the dashboard has disabled. Unioned into the ACL deny-list."""
    sec = (_load().get("security") or {})
    return set(sec.get("denied_tools") or [])


def _write_denied(names: set[str]) -> None:
    """Serialise the overlay. Only the [security] denied_tools list today.

    Hand-rolled TOML (no tomli-w dependency) since the shape is fixed:
    one table, one string-list. Atomic write at 0o600.
    """
    import os
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    rendered = ", ".join(f'"{n}"' for n in sorted(names))
    body = (
        "# Dashboard-managed overrides. Edit via the dashboard's\n"
        "# permissions page, not by hand (the dashboard rewrites this\n"
        "# file). Your config.toml is never touched by the dashboard.\n\n"
        "[security]\n"
        f"denied_tools = [{rendered}]\n"
    )
    fd = os.open(OVERRIDES_PATH, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
    finally:
        try:
            os.chmod(OVERRIDES_PATH, 0o600)
        except OSError:
            pass


def disable_tool(name: str) -> set[str]:
    """Add ``name`` to the overlay deny-list. Returns the new set."""
    current = denied_tools()
    current.add(name)
    _write_denied(current)
    return current


def enable_tool(name: str) -> set[str]:
    """Remove ``name`` from the overlay deny-list. Returns the new set.

    Note: this only clears a dashboard-set override. If a tool is
    denied in config.toml itself, re-enabling requires editing config.
    """
    current = denied_tools()
    current.discard(name)
    _write_denied(current)
    return current


__all__ = ["denied_tools", "disable_tool", "enable_tool", "OVERRIDES_PATH"]
