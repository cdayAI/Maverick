"""Safety utilities for Maverick.

Currently:
  - ``secret_detector``: regex-based credential scrubbing for tool outputs.

This package is intentionally lightweight (no fancy ML deps). Heavier
classifiers live behind optional extras and are loaded on demand.
"""
from .secret_detector import SecretMatch, redact, scan  # noqa: F401


__all__ = ["redact", "scan", "SecretMatch"]
