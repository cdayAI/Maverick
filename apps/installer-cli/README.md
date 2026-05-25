# maverick-installer

The interactive setup wizard. Reach it via:

```bash
maverick init           # if maverick-core is installed
maverick-init           # standalone entry point
```

Walks through:

1. Deployment target (Desktop / Docker / VPS / Phone companion)
2. AI providers (Anthropic / OpenAI / OpenRouter / Ollama)
3. Per-role model picks
4. Safety profile (Strict / Balanced / Permissive / Off)
5. Sandbox backend
6. Budget caps
7. API keys

Writes `~/.maverick/config.toml` and `~/.maverick/.env`.
