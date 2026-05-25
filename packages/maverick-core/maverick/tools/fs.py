"""Filesystem tools backed by the sandbox.

v0.1.1 fix: ``read_file`` / ``list_dir`` no longer interpolate the
LLM-supplied path into a shell command. They use ``pathlib`` directly
and verify the resolved path stays inside the sandbox workdir.

``write_file`` already used pathlib; tightened the path-traversal
check to match.

The shell tool (`shell.py`) intentionally exposes shell execution —
that's its purpose. Shield's `scan_tool_call` chokepoint guards it.
"""
from __future__ import annotations

from pathlib import Path

from . import Tool


MAX_READ_BYTES = 8000


def _safe_resolve(sandbox, user_path: str) -> Path:
    """Resolve `user_path` relative to sandbox.workdir, refusing traversal.

    Raises ValueError if the resolved path escapes the workspace.
    """
    workdir = Path(sandbox.workdir).resolve()
    candidate = (workdir / user_path).resolve()
    try:
        candidate.relative_to(workdir)
    except ValueError as e:
        raise ValueError(
            f"path {user_path!r} escapes the workspace"
        ) from e
    return candidate


def read_file(sandbox) -> Tool:
    def fn(args: dict) -> str:
        try:
            target = _safe_resolve(sandbox, args["path"])
        except ValueError as e:
            return f"ERROR: {e}"
        if not target.exists():
            return f"ERROR: {target} not found"
        if not target.is_file():
            return f"ERROR: {target} is not a file"
        try:
            data = target.read_text(encoding="utf-8", errors="replace")
        except (PermissionError, OSError) as e:
            return f"ERROR: {e}"
        if len(data) > MAX_READ_BYTES:
            return data[:MAX_READ_BYTES] + f"\n... [truncated, total {len(data)} bytes]"
        return data

    return Tool(
        name="read_file",
        description="Read a file from the workspace.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Path to read."}},
            "required": ["path"],
        },
        fn=fn,
    )


def write_file(sandbox) -> Tool:
    def fn(args: dict) -> str:
        try:
            target = _safe_resolve(sandbox, args["path"])
        except ValueError as e:
            return f"ERROR: {e}"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(args["content"], encoding="utf-8")
        except (PermissionError, OSError) as e:
            return f"ERROR: {e}"
        return f"wrote {len(args['content'])} bytes to {target}"

    return Tool(
        name="write_file",
        description="Write content to a file in the workspace. Overwrites if it exists.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        fn=fn,
    )


def list_dir(sandbox) -> Tool:
    def fn(args: dict) -> str:
        try:
            target = _safe_resolve(sandbox, args.get("path", "."))
        except ValueError as e:
            return f"ERROR: {e}"
        if not target.exists():
            return f"ERROR: {target} not found"
        if not target.is_dir():
            return f"ERROR: {target} is not a directory"
        entries = []
        try:
            for entry in sorted(target.iterdir()):
                kind = "d" if entry.is_dir() else "-"
                entries.append(f"{kind} {entry.name}")
        except (PermissionError, OSError) as e:
            return f"ERROR: {e}"
        return "\n".join(entries) if entries else "(empty)"

    return Tool(
        name="list_dir",
        description="List files in a directory.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "default": "."}},
        },
        fn=fn,
    )
