"""Audit-log erase coverage extension.

GDPR Art. 17 right-to-erasure already covers world-model state via
``maverick erase --channel X --user Y``. This module extends that to
the audit log: scrub or tombstone audit events tied to the same user
identity.

Two modes:

  - ``scrub_user(channel, user_id)``: rewrites matching lines to a
    tombstone form, preserving the row count and timestamps but
    removing identifying payload fields. Default behavior.
  - ``delete_user(channel, user_id)``: removes matching lines entirely.
    More aggressive; use when you need the audit log to look like the
    user never existed.

Both walk every `*.ndjson` file in ``~/.maverick/audit/``. They never
modify files mid-write — they write to a temp file and atomically
rename.

Matching: an event matches a user iff its payload contains
``channel`` AND ``user_id`` keys equal to the args (or
``channel:user_id`` appears in any string field).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .writer import DEFAULT_AUDIT_DIR

log = logging.getLogger(__name__)


def _event_matches(event: dict, channel: str, user_id: str) -> bool:
    if event.get("channel") == channel and event.get("user_id") == user_id:
        return True
    target = f"{channel}:{user_id}"
    for v in event.values():
        if isinstance(v, str) and target in v:
            return True
    return False


def _tombstone(event: dict, channel: str, user_id: str) -> dict:
    """Replace identifying fields with [REDACTED]. Keep ts + kind."""
    keep = {"v", "ts", "kind", "schema_version"}
    out = {k: v for k, v in event.items() if k in keep}
    out["agent"] = "[REDACTED]"
    out["channel"] = channel  # keep so audit still reports who-was-scrubbed
    out["user_id"] = "[REDACTED]"
    out["erased_at"] = __import__("time").time()
    return out


def _process_file(
    path: Path, channel: str, user_id: str, *, delete: bool,
) -> tuple[int, int]:
    """Walk a single audit-log file. Returns (matched, written)."""
    if not path.exists() or path.is_dir():
        return 0, 0
    tmp = path.with_suffix(".ndjson.erasetmp")
    matched = 0
    written = 0
    try:
        with open(path, encoding="utf-8") as src, open(tmp, "w", encoding="utf-8") as dst:
            for raw in src:
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    dst.write(raw)
                    written += 1
                    continue
                if not _event_matches(event, channel, user_id):
                    dst.write(raw)
                    written += 1
                    continue
                matched += 1
                if delete:
                    continue
                dst.write(json.dumps(_tombstone(event, channel, user_id), default=str) + "\n")
                written += 1
        # Preserve perms.
        try:
            mode = path.stat().st_mode & 0o777
        except OSError:
            mode = 0o600
        tmp.replace(path)
        try:
            os.chmod(path, mode)
        except OSError:
            pass
    except OSError as e:
        log.warning("audit erase: %s: %s", path, e)
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        return 0, 0
    return matched, written


def scrub_user(
    channel: str,
    user_id: str,
    *,
    audit_dir: Path = DEFAULT_AUDIT_DIR,
) -> tuple[int, int]:
    """Replace matching events with tombstones. Returns (matched, scanned)."""
    total_matched = 0
    total_scanned = 0
    if not audit_dir.exists():
        return 0, 0
    for path in sorted(audit_dir.glob("*.ndjson")):
        m, w = _process_file(path, channel, user_id, delete=False)
        total_matched += m
        total_scanned += w
    log.info(
        "audit erase (scrub): channel=%s user_id=%s matched=%d scanned=%d",
        channel, user_id, total_matched, total_scanned,
    )
    return total_matched, total_scanned


def delete_user(
    channel: str,
    user_id: str,
    *,
    audit_dir: Path = DEFAULT_AUDIT_DIR,
) -> tuple[int, int]:
    """Delete matching events entirely. Returns (deleted, scanned)."""
    total_matched = 0
    total_scanned = 0
    if not audit_dir.exists():
        return 0, 0
    for path in sorted(audit_dir.glob("*.ndjson")):
        m, w = _process_file(path, channel, user_id, delete=True)
        total_matched += m
        total_scanned += w
    log.info(
        "audit erase (delete): channel=%s user_id=%s matched=%d scanned=%d",
        channel, user_id, total_matched, total_scanned,
    )
    return total_matched, total_scanned


__all__ = ["scrub_user", "delete_user"]
