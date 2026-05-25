"""SSH sandbox backend.

Executes commands on a remote host via the system ``ssh`` binary. No
Python dep (paramiko) -- we just shell out to ssh so users get the
same keys / config / agents they already have set up.

Config::

    [sandbox]
    backend = "ssh"
    host = "me@example.com"
    workdir = "/home/me/maverick-workspace"
    timeout = 60
    # optional: extra ssh args
    ssh_args = ["-i", "~/.ssh/maverick_key", "-o", "StrictHostKeyChecking=accept-new"]

Security notes:
  - The workdir on the remote machine is the sandbox boundary. Don't
    point this at a path with sudo access.
  - Use a dedicated ssh key with a forced-command restriction in
    authorized_keys for stronger isolation.
  - This backend trusts the remote host's filesystem; no further
    sandboxing on the remote side. Pair with Docker on the remote for
    proper isolation.
"""
from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .local import ExecResult


@dataclass
class SSHBackend:
    host: str                       # "user@host" or just "host"
    workdir: Path = Path("~/maverick-workspace")
    timeout: float = 60.0
    ssh_args: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # workdir is a remote path; keep as string-style Path.
        if isinstance(self.workdir, str):
            self.workdir = Path(self.workdir)
        self._verify_ssh()

    def _verify_ssh(self) -> None:
        """Best-effort: confirm the ssh binary exists and we can connect."""
        import shutil
        if not shutil.which("ssh"):
            raise RuntimeError(
                "ssh binary not found on PATH. Install openssh-client."
            )
        # Lightweight reachability check.
        check = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
             *self.ssh_args, self.host, "true"],
            capture_output=True, timeout=10,
        )
        if check.returncode != 0:
            stderr = check.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"ssh to {self.host} failed: {stderr or 'unknown error'}. "
                "Check your SSH config / keys."
            )

    def exec(self, cmd: str) -> ExecResult:
        # The remote shell runs: cd <workdir> && <cmd>
        # We quote the whole thing as a single argument to ssh so the
        # local shell doesn't interpret it.
        remote = f"mkdir -p {shlex.quote(str(self.workdir))} && " \
                 f"cd {shlex.quote(str(self.workdir))} && {cmd}"
        args = ["ssh", *self.ssh_args, self.host, remote]
        try:
            result = subprocess.run(
                args, capture_output=True, text=True, timeout=self.timeout,
            )
            return ExecResult(
                stdout=result.stdout[-8000:],
                stderr=result.stderr[-2000:],
                exit_code=result.returncode,
            )
        except subprocess.TimeoutExpired as e:
            return ExecResult(
                stdout=(e.stdout or b"").decode("utf-8", errors="replace")[-8000:],
                stderr=f"TIMEOUT after {self.timeout}s",
                exit_code=124,
            )
