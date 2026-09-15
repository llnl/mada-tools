# Branch Brief: `feature/skills-scheduler-domain`

## Goal

Roll out direct command and packaged skill support for the scheduler domain, covering both `flux` and `slurm`.

This branch should build on the pilot patterns already established by the `job_monitor` branch.

## Dependencies

This branch should be based on `feature/skills-support` after both of these branches are merged into it:

1. `feature/extension-capability-surfaces`
2. `feature/direct-cli-pilot-job-monitor`

## Required Outcomes

1. `flux` exposes direct commands and one or more packaged skill assets.
2. `slurm` exposes direct commands and one or more packaged skill assets.
3. Environment/config handling for scheduler-backed direct invocation is consistent with current server behavior.
4. Background execution works for scheduler direct commands where appropriate.

## Primary Files Likely To Change

- `src/mada_tools/scheduler/flux/direct.py`
- `src/mada_tools/scheduler/slurm/direct.py`
- `src/mada_tools/scheduler/flux/...`
- `src/mada_tools/scheduler/slurm/...`
- `src/mada_tools/extensions/builtins.py`
- tests under `tests/scheduler/`, `tests/cli/`, and `tests/extensions/`

## Implementation Tasks

1. Add a direct execution adapter for `flux`.
   - Reuse `FluxJobManager`.
   - Preserve the deferred environment/config setup that currently happens before the manager is used by the MCP server.

2. Add a direct execution adapter for `slurm`.
   - Reuse `SlurmJobManager`.
   - Align behavior with the existing MCP surface as closely as practical.

3. Register domain commands through the extension system.
   - Example shape:

```text
mada-tools flux submit-command ...
mada-tools flux submit-jobs ...
mada-tools flux check-job-status ...

mada-tools slurm submit-command ...
mada-tools slurm submit-jobs ...
mada-tools slurm check-job-status ...
```

4. Add scheduler skill files.
   - `flux` skills should cover job submission and job monitoring usage.
   - `slurm` skills should cover job submission and job monitoring usage.
   - Keep the skill guidance focused on direct invocation, required inputs, and expected scheduler behavior.

5. Register the skills and direct commands in `builtins.py`.

6. Add tests.
   - CLI parser and invocation tests.
   - Registration/discovery tests.
   - Task-runtime tests for background execution when applicable.
   - Helper/direct parity tests where feasible.

## Design Constraints

1. Avoid deep scheduler refactors unless they are required for direct invocation.
2. Keep the direct layer thin.
3. Be careful with side effects, persistent executors, and cleanup behavior.

## Acceptance Criteria

1. Both scheduler capabilities are discoverable as direct commands and skills.
2. Users can invoke the scheduler capabilities without MCP.
3. Scheduler configuration and environment handling remain consistent with the current implementation model.
4. Tests cover both capability registration and invocation behavior.

## Out Of Scope

- Non-scheduler domain migrations.
- Large scheduler-business-logic rewrites not needed for the new execution surface.
