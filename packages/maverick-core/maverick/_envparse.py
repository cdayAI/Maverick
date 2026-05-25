"""Small helpers for environment-driven config without import-time crashes."""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


def env_int(name: str, default: int) -> int:
    """Read an int env var, falling back to ``default`` (with a log) on
    bad input. Without this, a typo like ``MAVERICK_MAX_SWARM_FANOUT=high``
    raises ValueError at module import, taking the whole package down."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning(
            "%s=%r is not an int; using default %s", name, raw, default,
        )
        return default


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning(
            "%s=%r is not a float; using default %s", name, raw, default,
        )
        return default
