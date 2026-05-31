"""Build maverick Tool objects from an MCPClient's discovered tools.

External MCP server tools become `mcp_<server>__<tool>` in the agent's
tool registry. The agent calls them just like any other tool; under
the hood we route to the MCPClient and return the response text.

Kept in its own module to avoid a circular import between tools/ and
mcp_client.
"""
from __future__ import annotations

import logging

from .mcp_client import MCPClient
from .tools import Tool

log = logging.getLogger(__name__)


def tools_from_mcp(client: MCPClient) -> list[Tool]:
    """Return a Tool per MCP-exposed tool, namespaced by server.

    Two layers defend the agent's tool catalog from a hostile MCP server:

    1. **Injection scan** (Tier 0). Descriptions + inputSchema string leaves
       are rendered into the catalog verbatim, so each is run through
       ``Shield.scan_input``; tools that fail are dropped with a warning.
    2. **Rug-pull / drift detection** (``mcp_pinning``). The server's tool set
       is pinned on first use; if a tool's definition later changes, it is
       flagged (``warn``) or withheld (``enforce``) -- a server can't quietly
       swap a tool's schema/behaviour after the operator approved it.
    """
    out: list[Tool] = []
    shield = _try_shield()
    decision = _pin_decision(client)
    for spec in client.tools:
        name = spec.get("name")
        if not name:
            continue
        if name not in decision.allowed:
            # enforce mode withholding a drifted/new tool (warn/off never gets
            # here -- their `allowed` is the full set).
            log.warning(
                "mcp tool %s.%s withheld: definition drifted from its pin "
                "(enforce mode). Re-approve with `maverick mcp-repin %s`.",
                client.spec.name, name, client.spec.name,
            )
            continue
        if not _spec_passes_shield(name, spec, shield):
            log.warning(
                "mcp tool %s.%s rejected by Shield; not registering",
                client.spec.name, name,
            )
            continue
        prefixed = f"mcp_{client.spec.name}__{name}"
        out.append(_build_tool(client, prefixed, name, spec))
    return out


def _pin_decision(client: MCPClient):
    """Reconcile the server's advertised tools against its pin; log + audit
    any drift. Best-effort: pinning must never break tool loading."""
    try:
        from .mcp_pinning import reconcile
        decision = reconcile(client.spec.name, client.tools)
    except Exception as e:  # pragma: no cover - defensive
        log.warning("mcp_pinning: reconcile failed for %s (allowing): %s",
                    client.spec.name, e)
        from .mcp_pinning import PinDecision
        return PinDecision(
            allowed={s.get("name") for s in client.tools if s.get("name")},
            mode="off",
        )
    if decision.first_use and client.tools:
        log.info("mcp %s: pinned %d tool definition(s) on first use",
                 client.spec.name, len(decision.allowed))
    if not decision.ok:
        log.warning(
            "mcp %s: tool-set DRIFT since pin (mode=%s) drifted=%s added=%s "
            "removed=%s", client.spec.name, decision.mode,
            decision.drifted, decision.added, decision.removed,
        )
        try:
            from .audit import record
            record(
                "mcp_tool_drift",
                server=client.spec.name,
                mode=decision.mode,
                drifted=decision.drifted,
                added=decision.added,
                removed=decision.removed,
            )
        except Exception:  # pragma: no cover - audit is best-effort
            pass
    return decision



def _try_shield():
    try:
        from maverick_shield import Shield  # type: ignore
        return Shield.from_config()
    except ImportError:
        return None


def _collect_schema_strings(node, out: list[str]) -> None:
    """Walk a JSON Schema dict and collect every string leaf.

    A hostile MCP server can put attack text in description / title /
    enum / examples inside nested properties; the agent sees those
    verbatim. Shield must inspect the full string-leaf set, not just
    the top-level description field.
    """
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str) and k in (
                "description", "title", "default", "pattern", "format",
            ):
                out.append(v)
            elif isinstance(v, (dict, list)):
                _collect_schema_strings(v, out)
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, str):
                out.append(item)
            else:
                _collect_schema_strings(item, out)


def _spec_passes_shield(name: str, spec: dict, shield) -> bool:
    if shield is None:
        return True
    description = spec.get("description", "") or ""
    parts: list[str] = [f"tool: {name}", f"description: {description}"]
    schema = spec.get("inputSchema") or {}
    leaves: list[str] = []
    _collect_schema_strings(schema, leaves)
    parts.extend(f"schema_text: {leaf}" for leaf in leaves)
    payload = "\n".join(parts)
    try:
        v = shield.scan_input(payload)
        return bool(v.allowed)
    except Exception:  # pragma: no cover
        return True


def _build_tool(client: MCPClient, prefixed: str, original: str, spec: dict) -> Tool:
    description = spec.get("description", "") or "(no description)"
    schema = spec.get("inputSchema") or {"type": "object", "properties": {}}

    async def fn(args: dict) -> str:
        try:
            return await client.call_tool(original, args)
        except Exception as e:
            log.exception("mcp tool %s failed", prefixed)
            return f"ERROR: {type(e).__name__}: {e}"

    return Tool(
        name=prefixed,
        description=f"[mcp:{client.spec.name}] {description}",
        input_schema=schema,
        fn=fn,
    )
