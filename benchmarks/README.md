# Maverick benchmarks

The wedge claim is **long-horizon work + true multi-agent coordination**.
These benchmarks make that measurable.

## Why benchmarks exist

Without numbers, "better at long-horizon" is marketing. Each benchmark
in this directory:

- Has a verifiable success criterion (file produced, tests pass, etc.)
- Records wall-clock, cost (`$`), tokens, tool calls, and depth.
- Is reproducible from a single `maverick start` command.
- Has a baseline number from a single-shot LLM call for comparison.

Results belong in `RESULTS.md` next to each benchmark, with the run
metadata (date, model assignments, total cost) checked in.

## How to run a benchmark

```bash
# Pre-req: maverick init has been run with at least an Anthropic key.
maverick start "$(cat benchmarks/longhorizon/research-report.md)" \
  --max-dollars 5 --max-wall-seconds 1800 --workdir bench-workspace
```

When done, copy the output (and the budget summary line) into the
corresponding `RESULTS.md`.

## Suite

| Benchmark | Class | Expected wall | Expected cost |
|---|---|---|---|
| `longhorizon/research-report.md` | Research synthesis | 10–20 min | $0.50–$2 |
| `longhorizon/code-refactor.md` | Multi-file refactor | 15–30 min | $1–$3 |
| `longhorizon/multi-step-planning.md` | Planning + revision loop | 20–40 min | $1–$4 |

All three are designed to **fail** for single-shot prompting (too
broad, too many steps) and **succeed** for a recursive swarm with
verify + skill distill enabled.

## Comparing across providers

Re-run the same benchmark with different `[models]` config blocks:

```toml
# all-anthropic
benchmarks/configs/all-anthropic.toml

# orchestrator on Anthropic, workers on Ollama (local)
benchmarks/configs/mixed-local-cloud.toml
```

The `RESULTS.md` for each benchmark records all configurations tried
and their numbers side by side.

## What we are NOT measuring (yet)

- Raw LLM accuracy (SWE-bench / MMLU / etc.) -- those measure the
  model, not the agent system
- Safety / red-team coverage -- that's Agent Shield's territory and
  has its own benchmark suite
- Distillation quality (whether auto-generated SKILL.md files actually
  help future runs) -- needs a separate longitudinal study, planned
  for v0.2
