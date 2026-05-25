"""Standalone entry point for the installer.

Installed as the ``maverick-init`` console script. Also reachable via
``maverick init`` when the core CLI is installed.
"""
from __future__ import annotations

import sys

from .wizard import run


def main() -> int:
    try:
        return run()
    except KeyboardInterrupt:
        print("\nAborted. Re-run `maverick init` any time.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
