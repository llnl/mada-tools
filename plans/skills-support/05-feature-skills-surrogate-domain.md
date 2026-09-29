# Branch Brief: `feature/skills-surrogate-domain`

## Goal

Roll out direct command and packaged skill support for the surrogate domain, covering `professor`.

This should be a relatively contained domain rollout and can serve as a lighter-weight follow-up after the scheduler branch or in parallel if the dependency chain is already merged into `feature/skills-support`.

## Dependencies

This branch should be based on `feature/skills-support` after both of these branches are merged into it:

1. `feature/extension-capability-surfaces`
2. `feature/direct-cli-pilot-job-monitor`

## Required Outcomes

1. `professor` exposes direct commands.
2. `professor` ships one or more packaged skill assets.
3. LLM-backed and GUI-launching behavior remain consistent with the existing helper implementation.

## Primary Files Likely To Change

- `src/mada_tools/surrogate/professor/direct.py`
- `src/mada_tools/surrogate/professor/skills/...`
- `src/mada_tools/extensions/builtins.py`
- tests under `tests/surrogate/`, `tests/cli/`, and `tests/extensions/`

## Implementation Tasks

1. Add a direct execution adapter for `professor`.
   - Reuse `ProfessorHelper`.
   - Keep object construction and environment handling aligned with the helper's current behavior.

2. Register direct commands through the extension system.
   - Expected actions likely include:
     - launching the Professor GUI
     - analyzing an image with the configured LLM

3. Add skill files under `src/mada_tools/surrogate/professor/skills/`.
   - Include at least one skill for image analysis.
   - Consider a separate skill for GUI launching if that makes usage clearer.

4. Register the new skill and direct-command surfaces in `builtins.py`.

5. Add tests.
   - Direct invocation tests.
   - Discovery tests.
   - Environment-sensitive behavior tests where practical.

## Design Constraints

1. Keep the direct layer thin and helper-backed.
2. Do not overcomplicate the CLI surface if a small number of actions suffices.
3. Preserve existing optional-LLM behavior instead of making LLM configuration mandatory.

## Acceptance Criteria

1. `professor` is discoverable through the extension system as both skills and direct commands.
2. The direct command surface is usable without MCP.
3. Tests cover the new registration and execution paths.

## Out Of Scope

- Workflow, scheduler, or simulation capability changes.
- Reworking Professor business logic beyond what direct invocation requires.
