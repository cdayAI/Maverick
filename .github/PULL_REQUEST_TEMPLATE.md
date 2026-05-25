# Pull request

## What

<!-- One-line summary of the change. The diff shows what; this is the elevator pitch. -->

## Why

<!-- The motivation. Link the council finding, issue, or strategic gap that this closes. -->

## How

<!--
List of files touched and what changed in each. Keep it short -- reviewers can read the diff.
Only use this section to flag non-obvious design decisions or trade-offs.
-->

## Test plan

<!--
- [ ] `pytest -vvs` passes
- [ ] `maverick doctor` still healthy after changes
- [ ] If you touched the agent loop, added a FakeLLM-driven test
- [ ] If you added a tool / sink, it goes through `ctx.shield.scan_tool_call()`
- [ ] If you added a provider, the wizard catalog (`models.py`) is updated
- [ ] If you added a channel, the wizard `CHANNELS` list and `server.py` `_WIRES` are updated
- [ ] If you added a CLI command, `docs/getting-started.md` mentions it
-->

## Council-flag triage

<!-- If this addresses a council review finding (architecture / security / UX / code quality
     / translator / channels / docs / tests / deployment / strategic), reference it: -->

- Council finding: ...
- Severity: ...
