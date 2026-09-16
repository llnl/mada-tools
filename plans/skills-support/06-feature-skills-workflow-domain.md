# Branch Brief: `feature/skills-workflow-domain`

## Goal

Roll out direct command and packaged skill support for the workflow domain, covering `maestro_command_executor`.

This branch focuses on direct execution of Maestro CLI-backed operations and the associated skill assets.

## Dependencies

This branch should be based on `feature/skills-support` after both of these branches are merged into it:

1. `feature/extension-capability-surfaces`
2. `feature/direct-cli-pilot-job-monitor`

## Required Outcomes

1. `maestro_command_executor` exposes direct commands through the extension-driven CLI.
2. The capability ships packaged skill assets explaining how to run and manage Maestro workflows through direct invocation.
3. Background execution works where it is appropriate for long-running workflow operations.

## Primary Files Likely To Change

- `src/mada_tools/workflow/weave/maestro/direct.py`
- `src/mada_tools/workflow/weave/maestro/skills/...`
- `src/mada_tools/extensions/builtins.py`
- tests under `tests/workflow/`, `tests/cli/`, and `tests/extensions/`

## Implementation Tasks

1. Add a direct execution adapter for `maestro_command_executor`.
   - Reuse `MaestroCommandExecutor`.
   - Keep the adapter thin and command-focused.

2. Register direct commands through the extension system.
   - Expected actions likely include:
     - `run-workflow`
     - `get-statuses`
     - `cancel-workflows`
     - `update-workflows`

3. Add skill files under `src/mada_tools/workflow/weave/maestro/skills/`.
   - Include at least one skill for starting workflows.
   - Include at least one skill for status inspection or lifecycle management.

4. Register the new skills and direct commands in `builtins.py`.

5. Add tests.
   - CLI and direct invocation tests.
   - Discovery tests.
   - Background-execution tests where relevant.

## Design Constraints

1. Keep the direct layer thin and reuse the existing executor.
2. Preserve the current CLI-command semantics as much as possible.
3. Avoid coupling the workflow domain rollout to WEAVE study-construction abstractions unless strictly necessary.

## Acceptance Criteria

1. `maestro_command_executor` is discoverable as both a direct command provider and a packaged skill source.
2. Users can launch and manage Maestro workflows without MCP.
3. Tests cover registration and execution behavior.

## Out Of Scope

- Adding direct support for abstract `study_construction` base classes.
- Broad workflow-domain refactors beyond what direct invocation requires.
