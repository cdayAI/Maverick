<!--
Thanks for contributing to Maverick! Keep this PR small and focused.
See CONTRIBUTING.md for the dev setup and house rules.
-->

## What & why

<!-- One or two sentences: what changes, and the problem it solves. Link issues with "Closes #123". -->

## How it was verified

<!-- The tests you added/ran, or the manual steps. "Write the test, then make it pass." -->

## Checklist

- [ ] **PR title is Conventional Commits** — `type:` prefix (`feat:`/`fix:`/`docs:`/`chore:`/`refactor:`/`test:`/`perf:`/`ci:`) and the subject **starts with a letter** (not a digit, quote, or backtick). The `lint-pr-title` check enforces this.
- [ ] **Tests added or updated** and `pytest -q` passes locally.
- [ ] **`ruff check .` is clean** (or run `pre-commit install` once and let it gate your commits).
- [ ] **No bare `import tomllib`** — it's 3.11+ stdlib and breaks CI on 3.10. Use the `try: import tomllib / except ModuleNotFoundError: import tomli as tomllib` fallback (see CLAUDE.md).
- [ ] **New capability → the wizard learns it.** If you added a channel/provider/sandbox/feature, `apps/installer-cli/` can enable it, or non-technical users can't reach it.
- [ ] **Safety invariants hold** (if you touched the agent loop or added a tool/sink): new tools go through `ctx.shield.scan_tool_call()`, long-running paths respect `Budget`, and all shell goes through `sandbox.exec()` (never `subprocess.run` directly).
- [ ] **Surgical change** — didn't reformat or "improve" adjacent code; matched the existing style.
