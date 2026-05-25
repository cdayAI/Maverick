# Maverick

An AI agent that anyone can run — powerful enough for engineers, simple enough for everyone else.

Maverick combines two open-source projects into a single, safest-by-default assistant:

- **Maverick Agent** — a recursive multi-agent swarm optimized for long-horizon work (hours, not minutes).
- **Agent Shield** — a mature safety layer with F1 0.988 prompt-injection detection, MCP security, OWASP/NIST/EU AI Act coverage.

You install it in one command, the wizard walks you through every choice, and it deploys anywhere — desktop, Docker, VPS, or phone-companion.

## Status

**Early alpha.** Foundation is being laid. See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the technical map and [`docs/getting-started.md`](./docs/getting-started.md) for the install flow.

## Vision

| Axis | Maverick |
|---|---|
| **Target user** | General consumer — no AI expertise required |
| **Wedge** | Long-horizon depth + true multi-agent coordination |
| **Safety** | First-class. Every input, tool call, and output passes through Agent Shield. |
| **Control** | You pick the models. Per-role. Multi-provider. |
| **Deploy** | Desktop / Docker / VPS / Phone (via Telegram + iMessage companions) |
| **Privacy** | All detection runs locally. Your data never leaves your machine unless you choose a cloud LLM. |

## Install (preview)

```bash
pipx install maverick
maverick init        # interactive wizard
maverick start "Plan a 2-week trip to Japan, write the itinerary to trip.md"
```

The wizard asks:

1. **Deployment target** — Desktop / Docker / VPS / Phone companion
2. **AI providers** — Anthropic / OpenAI / OpenRouter / Ollama (local) / mix
3. **Per-role models** — Pick a model for each agent role (orchestrator, researcher, coder, writer, analyst, revisor, summarizer)
4. **Safety profile** — Strict / Balanced / Permissive
5. **API keys** — Only for the providers you chose
6. **Sandbox** — Local / Docker / SSH
7. **Budget caps** — `$`/run, wall-clock, tool calls

## Repository layout

```
packages/
  maverick-core/      Python agent kernel (recursive swarm, world model, skills)
  maverick-shield/    Agent Shield integration (input / tool / output chokepoints)
apps/
  installer-cli/      Interactive Python TUI wizard (`maverick init`)
  installer-desktop/  Tauri-based GUI installer (planned)
docs/
  getting-started.md  Install + first run
  configuration.md    Config file reference
  deployment.md       Desktop / Docker / VPS / Phone targets
  safety.md           How Agent Shield wraps the agent
```

## License

MIT. See [`LICENSE`](./LICENSE).
