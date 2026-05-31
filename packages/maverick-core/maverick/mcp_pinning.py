"""TOFU pinning of MCP tool definitions -- rug-pull / drift detection.

External MCP servers advertise their tools at connect time (``tools/list``).
Maverick already shield-scans each tool's description + schema strings, so a
server can't ship a prompt-injection in plain sight (see ``mcp_tools``). The
remaining gap is a **rug pull**: a server advertises benign tools when the
operator first reviews/approves it, then silently changes a tool's schema or
behaviour in a later session -- the 2026 MCP advisory class.

This module pins each server's advertised tool set on first use (trust on
first use) and detects drift on every later load:

  - ``off``     -- no pinning (legacy behaviour).
  - ``warn``    -- pin on first use; on drift, still register the tools but
                   flag it (log + audit) so the operator notices.  *(default)*
  - ``enforce`` -- pin on first use; on drift, register ONLY the tools whose
                   definition matches the pin. Drifted/new tools are withheld
                   until the operator re-pins (``maverick mcp-repin``).

A fingerprint covers the tool name + description + canonicalised inputSchema,
so any change the model would *see* counts as drift. The pin store lives at
``~/.maverick/mcp_pins.json`` (chmod 600).
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

_VALID_MODES = ("off", "warn", "enforce")
# Off by default: pinning is opt-in (it writes a pin store and only matters for
# external MCP servers). The always-on description/schema injection scan in
# ``mcp_tools`` covers the common case; warn/enforce add rug-pull detection.
_DEFAULT_MODE = "off"


def _default_pins_path() -> Path:
    return Path.home() / ".maverick" / "mcp_pins.json"


def tool_fingerprint(spec: dict) -> str:
    """Stable hash of one tool's model-visible definition.

    Covers name + description + the full inputSchema (canonicalised with
    ``sort_keys`` so key order can't mask a change). Anything the model is
    shown is part of the fingerprint; anything else (server-internal fields)
    is ignored so benign metadata churn isn't flagged.
    """
    material = {
        "name": spec.get("name", ""),
        "description": spec.get("description", "") or "",
        "inputSchema": spec.get("inputSchema") or {},
    }
    blob = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def fingerprint_all(tools: list[dict]) -> dict[str, str]:
    """{tool_name: fingerprint} for an advertised tool list (unnamed skipped)."""
    out: dict[str, str] = {}
    for spec in tools or []:
        name = spec.get("name")
        if name:
            out[str(name)] = tool_fingerprint(spec)
    return out


@dataclass
class PinDecision:
    """Outcome of comparing a server's current tools against its pin."""
    allowed: set[str]
    drifted: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    first_use: bool = False
    mode: str = _DEFAULT_MODE

    @property
    def ok(self) -> bool:
        """True when nothing changed since the pin (or this is the baseline)."""
        return not (self.drifted or self.added or self.removed)


def evaluate(
    pinned: dict[str, str] | None,
    current: dict[str, str],
    *,
    mode: str = _DEFAULT_MODE,
) -> PinDecision:
    """Pure diff of ``current`` fingerprints against the ``pinned`` baseline.

    ``mode='enforce'`` withholds drifted + newly-added tools (only exact
    matches are allowed); ``'warn'`` allows everything but reports the diff;
    ``'off'`` allows everything and reports nothing.
    """
    if mode == "off":
        return PinDecision(allowed=set(current), mode="off")
    if pinned is None:
        # Trust on first use: the current set becomes the baseline.
        return PinDecision(allowed=set(current), first_use=True, mode=mode)
    drifted = sorted(n for n in current if n in pinned and current[n] != pinned[n])
    added = sorted(n for n in current if n not in pinned)
    removed = sorted(n for n in pinned if n not in current)
    if mode == "enforce":
        allowed = {n for n in current if n in pinned and current[n] == pinned[n]}
    else:
        allowed = set(current)
    return PinDecision(
        allowed=allowed, drifted=drifted, added=added, removed=removed,
        first_use=False, mode=mode,
    )


def load_pins(path: Path | None = None) -> dict[str, dict[str, str]]:
    path = path or _default_pins_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    # Shape: {server: {tool_name: fingerprint}}
    out: dict[str, dict[str, str]] = {}
    for server, tools in data.items():
        if isinstance(tools, dict):
            out[str(server)] = {str(k): str(v) for k, v in tools.items()}
    return out


def _save_pins(pins: dict[str, dict[str, str]], path: Path | None = None) -> None:
    path = path or _default_pins_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(pins, indent=2, sort_keys=True), encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:  # pragma: no cover - non-POSIX
            pass
    except OSError as e:  # pragma: no cover - disk full / RO fs
        log.warning("mcp_pinning: could not persist pins: %s", e)


def _mode() -> str:
    try:
        from .config import get_mcp
        m = str(get_mcp().get("tool_pinning") or _DEFAULT_MODE).strip().lower()
    except Exception:
        return _DEFAULT_MODE
    return m if m in _VALID_MODES else _DEFAULT_MODE


def _configured_path() -> Path:
    try:
        from .config import get_mcp
        p = get_mcp().get("pins_path")
        if p:
            return Path(p).expanduser()
    except Exception:
        pass
    return _default_pins_path()


def reconcile(
    server: str,
    tools: list[dict],
    *,
    mode: str | None = None,
    path: Path | None = None,
) -> PinDecision:
    """Compare ``server``'s advertised ``tools`` to its pin, recording the
    baseline on first use. Returns the :class:`PinDecision` the caller uses to
    gate registration. Never raises -- pinning must not break tool loading."""
    mode = (mode or _mode())
    if mode not in _VALID_MODES:
        mode = _DEFAULT_MODE
    if mode == "off":
        return PinDecision(allowed={s.get("name") for s in tools if s.get("name")},
                           mode="off")
    path = path or _configured_path()
    current = fingerprint_all(tools)
    try:
        pins = load_pins(path)
    except Exception:  # pragma: no cover - defensive
        pins = {}
    decision = evaluate(pins.get(server), current, mode=mode)
    if decision.first_use and current:
        pins[server] = current
        _save_pins(pins, path)
    return decision


def repin(server: str | None = None, *, path: Path | None = None) -> int:
    """Forget pins so the next load re-baselines (TOFU). With ``server``,
    only that server; otherwise all. Returns how many server pins were cleared."""
    path = path or _configured_path()
    pins = load_pins(path)
    if not pins:
        return 0
    if server is None:
        n = len(pins)
        _save_pins({}, path)
        return n
    if server in pins:
        del pins[server]
        _save_pins(pins, path)
        return 1
    return 0


__all__ = [
    "PinDecision",
    "tool_fingerprint",
    "fingerprint_all",
    "evaluate",
    "reconcile",
    "load_pins",
    "repin",
]
