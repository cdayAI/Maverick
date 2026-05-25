# Example goal templates

Reusable goal bodies with parameter substitution. Run any of them with:

```bash
maverick start --template <name> --param key=value --param key2=value2
```

For example:

```bash
maverick start --template compare-options \
  --param category="vector databases" \
  --param option_a="pgvector" \
  --param option_b="Qdrant"

maverick start --template trip-plan \
  --param destination="Lisbon" \
  --param duration="5 days"

maverick start --template standup --param project="Maverick"
```

## Catalog

| Template | What it does | Required params |
|---|---|---|
| [`compare-options.md`](compare-options.md) | Side-by-side comparison of two alternatives | `category`, `option_a`, `option_b` |
| [`trip-plan.md`](trip-plan.md) | Day-by-day travel itinerary | `destination`, `duration` |
| [`standup.md`](standup.md) | Daily standup from git log + workspace notes | `project` |

## Schema

```markdown
---
title: <Title with {{ params }}>
budget_dollars: <float, default 5.0>
budget_wall_seconds: <float, default 3600>
params:
  - first_required_param
  - second_required_param
---
The goal body. Use {{ first_required_param }} and {{ second_required_param }}
where you'd otherwise hardcode values.
```

Variables that aren't supplied at runtime are left in the rendered output
(useful for partial templates), but any param listed in `params:` is
**required** -- omitting one raises an error before the agent starts.

## Installing your own templates

Drop a `.md` file in `~/.maverick/templates/` and it's available
immediately. User templates take precedence over bundled ones when
they share a name.
