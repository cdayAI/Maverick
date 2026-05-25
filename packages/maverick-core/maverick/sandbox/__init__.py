"""Execution backends.

Local (subprocess) and Docker (throwaway containers) today; SSH and
remote services next.

The agent never instantiates a backend directly — always go through
``build_sandbox()`` so the [sandbox] config section is the single
source of truth.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from .local import LocalBackend, ExecResult
from .docker import DockerBackend

__all__ = ["LocalBackend", "DockerBackend", "ExecResult", "build_sandbox"]


Sandbox = Union[LocalBackend, DockerBackend]


def build_sandbox(
    workdir: Optional[Union[str, Path]] = None,
    backend: Optional[str] = None,
) -> Sandbox:
    """Construct the configured sandbox backend.

    Reads ``[sandbox]`` from ``~/.maverick/config.toml``; either argument
    overrides the corresponding config value.
    """
    try:
        from ..config import get_sandbox
        cfg = get_sandbox()
    except Exception:
        cfg = {}

    chosen = backend or cfg.get("backend", "local")
    wd = Path(workdir or cfg.get("workdir", str(Path.cwd()))).expanduser()
    timeout = float(cfg.get("timeout", 60))

    if chosen == "docker":
        image = cfg.get("image", "python:3.12-slim")
        return DockerBackend(workdir=wd, image=image, timeout=timeout)
    if chosen == "ssh":
        raise NotImplementedError("SSH backend is planned for v0.2.")
    return LocalBackend(workdir=wd, timeout=timeout)
