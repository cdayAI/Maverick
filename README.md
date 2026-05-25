# Maverick

An AI agent that anyone can run -- powerful enough for engineers, simple enough for everyone else.

Maverick combines two open-source projects into a single, safest-by-default assistant:

- **Maverick Agent** -- a recursive multi-agent swarm optimized for long-horizon work (hours, not minutes).
- **Agent Shield** -- a mature safety layer with F1 0.988 prompt-injection detection (full SDK) plus a built-in 20-pattern fallback that ships with Maverick.

Install in one command, the wizard walks you through every choice, and it deploys anywhere -- desktop, Docker, VPS, or phone-companion (via any of 9 channels).

## Status

**Early alpha.** Foundation complete; tag `v0.1.0` to publish to PyPI + GHCR. See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the technical map and [`docs/getting-started.md`](./docs/getting-started.md) for the install flow.

## What works today vs. planned

| Component | v0.1 (today) | Planned (v0.2+) |
|---|---|---|
| Install | Source via `pip install -e ./packages/maverick-core` (one-step `pip install maverick-agent` lands when tagged) | One-click Tauri DMG / MSIX / AppImage (signed) |
| GUI | Local web dashboard (`maverick dashboard`) + chat at `/chat` | Native Tauri shell + native iOS/Android |
| Sandbox | Local subprocess, Docker, SSH | Modal / Daytona |
| AI providers | Anthropic (full), OpenAI, OpenRouter, Ollama, Gemini -- per-role routable | Bedrock, Cohere |
| Channels | Telegram, Discord, Slack, Signal, Email, Matrix (ready) + WhatsApp, SMS, iMessage (scaffolds) | Push notifications, voice |
| Safety | Shield wired at 3 chokepoints; agent-shield SDK if installed, else 20 builtin rules | agent-shield SDK on PyPI; full ~115 patterns |
| Distribution | GHCR image + PyInstaller binaries + PyPI publish all wired (untagged) | Tagged release; signed bundles |
| Tests | 150+ tests, ruff + pytest on Py 3.10/3.11/3.12 | Integration tests + benchmark RESULTS.md |

## Install (preview)

Until PyPI publish, install from source:

```bash
git clone https://github.com/texasreaper62/maverick
cd maverick

pip install -e ./packages/maverick-core
pip install --no-deps -e ./packages/maverick-shield
pip install --no-deps -e ./packages/maverick-channels
pip install --no-deps -e ./packages/maverick-dashboard
pip install --no-deps -e ./packages/maverick-mcp
pip install --no-deps -e ./apps/installer-cli
pip install fastapi uvicorn jinja2 python-multipart questionary rich

maverick init                          # interactive wizard
maverick start "Plan a 2-week trip"     # one-shot goal
maverick chat                           # interactive REPL
maverick dashboard                      # web UI at http://127.0.0.1:8765
maverick serve                          # channel server (Telegram/Discord/...)
maverick mcp                            # MCP server (Claude Code / Cursor)
maverick doctor                         # health check
maverick version                        # installed package versions
```

When tagged for release, the install collapses to:

```bash
pipx install maverick-agent[all]
```

## CLI reference

| Command | What |
|---|---|
| `maverick init` | Interactive setup wizard with preflight + API-key validation |
| `maverick doctor` | Green / yellow / red health check + remediation hints |
| `maverick version` | Installed package versions + runtime info |
| `maverick config show / path / edit` | Show / locate / edit `~/.maverick/config.toml` |
| `maverick start TITLE [--template NAME --param k=v]` | Run a goal once |
| `maverick chat` | Interactive REPL (each line = a goal) |
| `maverick serve` | Channel server (reads `[channels.*]` from config) |
| `maverick dashboard [--host --port --token]` | Local web UI + REST API |
| `maverick mcp` | MCP server on stdio for Claude Code / Cursor / etc. |
| `maverick logs / status / answer / resume` | Inspect + control running goals |
| `maverick fact / facts` | Get / set persistent facts |
| `maverick skills` | List installed + distilled skills |
| `maverick skill install / remove / info` | Manage the skill marketplace |
| `maverick template list / show` | Goal templates with `{{ var }}` substitution |
| `maverick budget` | Total + per-run cost history |

## Repository layout

```
packages/
  maverick-core/       Python agent kernel: recursive swarm, persistent world
                       model (SQLite + FTS5 + schema v3), 5 LLM providers, 3
                       sandboxes, MCP client, skills, templates, persona,
                       background runner, budget tracking
  maverick-shield/     Agent Shield integration + 20-pattern builtin fallback
  maverick-channels/   9 channel adapters: Telegram, Discord, Slack, Signal,
                       Email, Matrix (ready) + WhatsApp, SMS, iMessage (scaffold)
  maverick-dashboard/  Local FastAPI web UI + REST API at /api/v1 + OpenAPI
                       docs at /docs. Live progress streaming via short-poll.
  maverick-mcp/        MCP server (stdio JSON-RPC) -- exposes Maverick to Claude
                       Code, Cursor, Claude Desktop as a tool. The agent kernel
                       can also CONSUME external MCP servers as its own tools.
apps/
  installer-cli/       Interactive Python TUI wizard (`maverick init`)
  installer-desktop/   Tauri-based GUI installer scaffold (signing in v0.2)
deploy/
  docker/ vps/ desktop/  Dockerfile, install.sh, systemd unit, Caddyfile
docs/
  getting-started.md     Install + first run
  configuration.md       Full config schema reference
  deployment.md          Desktop / Docker / VPS / Phone-companion targets
  safety.md              Shield chokepoints and built-in rule set
  api.md                 REST API reference + curl examples
benchmarks/
  longhorizon/           Reproducible long-horizon evaluation tasks
  example-skills/        Curated SKILL.md files for the marketplace
  example-templates/     Reusable goal-template files
```

## Vision

| Axis | Maverick |
|---|---|
| **Target user** | General consumer -- no AI expertise required |
| **Wedge** | Long-horizon depth + true multi-agent coordination |
| **Safety** | First-class. Every input, tool call, and output passes through Agent Shield. |
| **Control** | You pick the models. Per-role. Multi-provider. |
| **Deploy** | Desktop / Docker / VPS / Phone (9 channels) |
| **Privacy** | All detection runs locally. Your data never leaves your machine unless you choose a cloud LLM. |

## License

MIT. See [`LICENSE`](./LICENSE).
