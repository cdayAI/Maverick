#!/bin/bash
# SessionStart hook for Claude Code on the web.
#
# Provisions the dev environment so `python -m pytest` and `python -m ruff`
# work out of the box. Mirrors the install steps in .github/workflows/ci.yml
# (the source of truth) plus the few extras a bare web container needs.
#
# Idempotent: safe to re-run. No-op outside the remote web environment.
set -euo pipefail

# Only provision the Claude Code on the web container; a local checkout
# already has whatever the developer set up.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
cd "$ROOT"

# Use the same interpreter that runs `python -m pytest` later. The `pytest`
# and `ruff` binaries on PATH live in isolated uv-tool envs that can't see
# these installs, so always drive them via `python -m ...`.
PY="${PYTHON:-python}"

echo "[session-start] installing maverick packages (editable, mirrors CI)..."
# maverick-core first; the satellites use --no-deps so pip doesn't try to
# resolve maverick-agent from PyPI.
"$PY" -m pip install -q -e ./packages/maverick-core
"$PY" -m pip install -q --no-deps \
  -e ./packages/maverick-shield \
  -e ./packages/maverick-channels \
  -e ./packages/maverick-dashboard \
  -e ./packages/maverick-mcp \
  -e ./apps/installer-cli

echo "[session-start] installing runtime + dev deps..."
# Runtime deps the --no-deps installs dropped (the dashboard/mcp apps import
# the web stack at construction time), the installer's interactive deps, and
# the test/lint toolchain. ruff is installed as a module so `python -m ruff`
# works (the PATH `ruff` is a separate uv-tool env).
"$PY" -m pip install -q \
  'questionary>=2.0' 'rich>=13.7' \
  'fastapi>=0.110' 'uvicorn>=0.27' 'jinja2>=3.1' \
  'httpx>=0.27' 'python-multipart>=0.0.9' \
  pytest pytest-asyncio 'ruff>=0.5'

# cryptography's cffi backend is broken in the base image (_cffi_backend
# missing), which breaks the signed-skill tests on import. Reinstalling cffi
# fixes it; don't fail the whole hook if this step has no effect.
"$PY" -m pip install -q --force-reinstall cffi >/dev/null 2>&1 || true

# Persist PYTHONPATH for the session. The repo isn't a single installable
# tree; each package lives under its own dir, and PYTHONPATH is more robust
# than the editable-install finder under pytest's --import-mode=importlib.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export PYTHONPATH=\"$ROOT/packages/maverick-core:$ROOT/packages/maverick-dashboard:$ROOT/packages/maverick-mcp:$ROOT/packages/maverick-channels:$ROOT/packages/maverick-shield:$ROOT/apps/installer-cli\"" >> "$CLAUDE_ENV_FILE"
fi

echo "[session-start] done. Run tests with: python -m pytest   lint with: python -m ruff check ."
