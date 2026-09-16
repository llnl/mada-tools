# Branch Brief: `feature/direct-cli-pilot-job-monitor`

## Goal

Prove the new architecture end-to-end with the `job_monitor` capability.

This branch should deliver the first real direct command implementation, the first packaged skill asset, and the first use of the shared background task runtime outside MCP.

## Dependencies

This branch should be based on top of `feature/extension-capability-surfaces` after that branch is merged into `feature/skills-support`.

## Required Outcomes

1. `job_monitor` can be used without starting an MCP server.
2. The CLI discovers and mounts direct commands through the extension system rather than hardcoded imports.
3. Direct invocation supports both foreground and background execution.
4. At least one packaged skill for `job_monitor` is discoverable through the extension system.

## Primary Files Likely To Change

- `src/mada_tools/main.py`
- CLI command modules under `src/mada_tools/cli/`
- `src/mada_tools/extensions/builtins.py`
- `src/mada_tools/monitor/job_monitor/direct.py`
- `src/mada_tools/monitor/job_monitor/skills/diagnose_job_failures.md`
- tests under `tests/cli/`, `tests/monitor/job_monitor/`, and possibly `tests/extensions/`

## Implementation Tasks

1. Add a direct execution adapter for `job_monitor`.
   - Create `src/mada_tools/monitor/job_monitor/direct.py`.
   - Reuse `JobMonitorHelper` rather than duplicating business logic.

2. Extend the CLI to mount extension-provided direct commands.
   - Keep the command-discovery flow extension-driven.
   - Prefer a stable UX such as:

```text
mada-tools job-monitor read-logs ...
mada-tools job-monitor summarize-status ...
```

3. Add background execution support for direct commands.
   - Use the shared task runtime from the foundational branch.
   - Add a consistent way to retrieve task results.
   - Prefer a shared top-level task retrieval command if it fits the CLI architecture cleanly.

4. Add the first skill asset.
   - Create a skill markdown file under `src/mada_tools/monitor/job_monitor/skills/`.
   - The skill should explain when to use the capability, how to invoke it through the direct command surface, required inputs, expected outputs, and relevant environment/config assumptions.

5. Register the new surfaces.
   - Add `job_monitor` skill registration in `builtins.py`.
   - Add `job_monitor` direct-command registration in `builtins.py`.

6. Add tests.
   - Direct foreground execution.
   - Direct background execution.
   - Task result retrieval.
   - Extension discovery for the `job_monitor` skill and direct command.
   - Reasonable parity tests comparing direct invocation and the existing helper-backed behavior.

## Design Constraints

1. Do not introduce a second code path for business logic.
2. Keep `server.py` unchanged except where needed to align with the shared task runtime.
3. Treat this branch as the example that later domain branches will copy.

## Acceptance Criteria

1. A user can discover the `job_monitor` skill through the extension system.
2. A user can run `job_monitor` functionality through `mada-tools` without MCP.
3. Long-running or background direct execution works and task results can be retrieved.
4. Tests clearly document the intended pattern for later rollouts.

## Out Of Scope

- Direct command rollouts for other domains.
- Large documentation refreshes outside what is needed to keep this branch understandable.
