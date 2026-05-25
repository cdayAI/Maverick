# Maverick

An AI agent that anyone can run — powerful enough for engineers, simple enough for everyone else.

Maverick combines two open-source projects into a single, safest-by-default assistant:

- **Maverick Agent** — a recursive multi-agent swarm optimized for long-horizon work (hours, not minutes).
- **Agent Shield** — a mature safety layer with F1 0.988 prompt-injection detection, MCP security, OWASP/NIST/EU AI Act coverage.

You install it in one command, the wizard walks you through every choice, and it deploys anywhere — desktop, Docker, VPS, or phone-companion (via any of 9 channels).

## Status

**Early alpha.** The foundation is in place; not yet on PyPI. See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the technical map and [`docs/getting-started.md`](./docs/getting-started.md) for the install flow.

## What works today vs. planned

| Component | v0.1 (today) | Planned |
|---|---|---|
| Install | Source via `pip install -e ./packages/maverick-core` | `pipx install maverick` from PyPI |
| GUI installer | none — CLI wizard only (`maverick init`) | Tauri DMG / MSIX / AppImage |
| Sandbox | Local subprocess, Docker | SSH, Modal |
| AI providers | Anthropic, OpenAI, OpenRouter, Ollama (all routable per-role) | Cohere, Bedrock, Gemini direct |
| Channels | Telegram, Discord, Slack, Signal, Email, Matrix (full) + iMessage, WhatsApp, SMS (scaffolds) | All polished, native iOS/Android shells |
| Safety | Shield wired at input + tool-call + output chokepoints; fail-open if SDK missing | `agent-shield` published to PyPI; hard dep when `profile != off` |
| Tests | Smoke tests + CI on Python 3.10/3.11/3.12 | Integration + benchmark suite |
| Docker image | builds in CI | published to ghcr.io on tag |

## Vision

| Axis | Maverick |
|---|---|
| **Target user** | General consumer — no AI expertise required |
| **Wedge** | Long-horizon depth + true multi-agent coordination |
| **Safety** | First-class. Every input, tool call, and output passes through Agent Shield. |
| **Control** | You pick the models. Per-role. Multi-provider. |
| **Deploy** | Desktop / Docker / VPS / Phone (9 channels) |
| **Privacy** | All detection runs locally. Your data never leaves your machine unless you choose a cloud LLM. |

## Install (preview)

Until the PyPI release, install from source:

```bash
git clone https://github.com/texasreaper62/maverick
cd maverick
pip install -e ./packages/maverick-core
pip install -e ./packages/maverick-shield
pip install -e ./packages/maverick-channels
pip install -e ./apps/installer-cli

maverick init        # interactive wizard
maverick start "Plan a 2-week trip to Japan, write the itinerary to trip.md"
```

For phone-companion mode (after `init` enables Telegram/Discord/etc.):

```bash
maverick serve       # runs all enabled channels concurrently
```

The wizard asks:

1. **Deployment target** — Desktop / Docker / VPS / Phone companion
2. **AI providers** — Anthropic / OpenAI / OpenRouter / Ollama (local) / mix
3. **Per-role models** — Pick a model for each agent role (orchestrator, researcher, coder, writer, analyst, revisor, summarizer)
4. **Channels** — Telegram, Discord, Slack, Signal, Email, Matrix, WhatsApp, SMS, iMessage
5. **Safety profile** — Strict / Balanced / Permissive
6. **API keys** — Only for the providers and channels you chose
7. **Sandbox** — Local / Docker
8. **Budget caps** — `$`/run, wall-clock, tool calls

## Repository layout

```
packages/
  maverick-core/      Python agent kernel (recursive swarm, world model, skills,
                      multi-provider LLM dispatch)
  maverick-shield/    Agent Shield integration (input / tool / output chokepoints)
  maverick-channels/  Channel adapters (Telegram, Discord, Slack, Signal,
                      Email, Matrix, WhatsApp, SMS, iMessage)
apps/
  installer-cli/      Interactive Python TUI wizard (`maverick init`)
  installer-desktop/  Tauri-based GUI installer (planned)
deploy/
  docker/             Dockerfile + docker-compose for containerized runs
  vps/                install.sh + systemd unit + Caddyfile for always-on hosts
  desktop/            Notes for PyInstaller / Tauri native builds (planned)
docs/
  getting-started.md  Install + first run
  configuration.md    Config file reference
  deployment.md       Desktop / Docker / VPS / Phone targets + channel recipes
  safety.md           How Agent Shield wraps the agent
```

## License

MIT. See [`LICENSE`](./LICENSE).
