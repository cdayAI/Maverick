"""Execution backends.

Local (subprocess), Docker (throwaway containers), SSH (remote host
via system ssh binary). All implement ``.exec(cmd) -> ExecResult``
so the agent loop is backend-agnostic.

The agent never instantiates a backend directly -- always go through
``build_sandbox()`` so the [sandbox] config section is the single
source of truth.
"""
from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
from typing import Optional, Union

from .devcontainer import DevcontainerBackend
from .docker import DockerBackend
from .firecracker import FirecrackerBackend
from .kubernetes import KubernetesBackend
from .local import ExecResult, LocalBackend
from .podman import PodmanBackend
from .ssh import SSHBackend

__all__ = [
    "LocalBackend",
    "DockerBackend",
    "PodmanBackend",
    "DevcontainerBackend",
    "KubernetesBackend",
    "FirecrackerBackend",
    "SSHBackend",
    "ExecResult",
    "build_sandbox",
]

log = logging.getLogger(__name__)

Sandbox = Union[
    LocalBackend, DockerBackend, PodmanBackend, DevcontainerBackend,
    KubernetesBackend, FirecrackerBackend, SSHBackend,
]

_LOCAL_WARNING_EMITTED = False


def _warn_local_unsandboxed() -> None:
    """Warn (once per process) that the agent will run model-generated shell
    directly on the host with no container isolation.

    The local backend executes ``shell=True`` commands on this machine, so a
    prompt-injected agent gets host code execution. The Shield is the only
    screen, and it is fail-open (optional dependency) -- escalate the message
    when it isn't installed. Suppress with MAVERICK_SUPPRESS_SANDBOX_WARNING=1
    (e.g. when the operator has deliberately accepted host execution, or for
    quiet test runs). The wizard already defaults real installs to a container
    backend when one is available; this catches CLI / embedder / hand-edited
    configs that land on the unisolated default.
    """
    global _LOCAL_WARNING_EMITTED
    if _LOCAL_WARNING_EMITTED:
        return
    if os.environ.get("MAVERICK_SUPPRESS_SANDBOX_WARNING") == "1":
        _LOCAL_WARNING_EMITTED = True
        return
    _LOCAL_WARNING_EMITTED = True
    shield_present = importlib.util.find_spec("maverick_shield") is not None
    msg = (
        "sandbox backend is 'local': model-generated shell runs directly on "
        "this host with NO container isolation. A prompt-injected agent can "
        "execute arbitrary code here. For untrusted goals, set [sandbox] "
        "backend = \"docker\" (or podman) in ~/.maverick/config.toml."
    )
    if not shield_present:
        msg += (
            " maverick-shield is NOT installed, so tool calls are not screened "
            "either (fail-open). This is the least-protected configuration."
        )
    log.warning("%s Silence with MAVERICK_SUPPRESS_SANDBOX_WARNING=1.", msg)


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
        full_cfg = None
        try:
            from ..config import load_config
            full_cfg = load_config().get("sandbox", {})
        except Exception:
            full_cfg = {}
    except Exception:
        cfg = {}
        full_cfg = {}

    chosen = backend or cfg.get("backend", "local")
    wd = Path(workdir or cfg.get("workdir", str(Path.cwd()))).expanduser()
    timeout = float(cfg.get("timeout", 60))

    if chosen == "docker":
        image = full_cfg.get("image", "python:3.12-slim")
        return DockerBackend(
            workdir=wd, image=image, timeout=timeout,
            pids_limit=full_cfg.get("pids_limit", 512),
        )
    if chosen == "podman":
        image = full_cfg.get("image", "python:3.12-slim")
        return PodmanBackend(
            workdir=wd, image=image, timeout=timeout,
            allow_network=bool(full_cfg.get("allow_network", False)),
            pids_limit=full_cfg.get("pids_limit", 512),
        )
    if chosen == "devcontainer":
        project_dir = Path(
            full_cfg.get("project_dir") or workdir or Path.cwd()
        ).expanduser()
        return DevcontainerBackend(
            project_dir=project_dir, timeout=timeout,
            allow_network=bool(full_cfg.get("allow_network", True)),
        )
    if chosen == "kubernetes":
        return KubernetesBackend(
            image=full_cfg.get("image", "python:3.12-slim"),
            namespace=full_cfg.get("namespace", "default"),
            context=full_cfg.get("context"),
            workdir=Path(full_cfg.get("workdir", "/workspaces/repo")),
            timeout=timeout,
            allow_network=bool(full_cfg.get("allow_network", False)),
            extra_kubectl_args=full_cfg.get("extra_kubectl_args") or [],
        )
    if chosen == "firecracker":
        return FirecrackerBackend(
            workdir=wd,
            image=full_cfg.get("image", "ubuntu:24.04-maverick"),
            timeout=timeout,
            provider=full_cfg.get("provider", "local"),
            api_key=full_cfg.get("api_key"),
            network=full_cfg.get("network", "egress-deny"),
        )
    if chosen == "ssh":
        host = full_cfg.get("host")
        if not host:
            raise ValueError(
                "sandbox backend=ssh requires [sandbox] host = \"user@example.com\""
            )
        return SSHBackend(
            host=host,
            workdir=Path(full_cfg.get("workdir", "~/maverick-workspace")),
            timeout=timeout,
            ssh_args=full_cfg.get("ssh_args", []),
        )
    _warn_local_unsandboxed()
    return LocalBackend(workdir=wd, timeout=timeout)
