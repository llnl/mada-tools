# Branch Brief: `feature/skills-simulation-domain`

## Goal

Roll out direct command and packaged skill support for the simulation domain, covering `vertex_cfd`.

This is expected to be the heaviest built-in capability rollout because of its dependency profile and wider helper surface.

## Dependencies

This branch should be based on `feature/skills-support` after both of these branches are merged into it:

1. `feature/extension-capability-surfaces`
2. `feature/direct-cli-pilot-job-monitor`

## Required Outcomes

1. `vertex_cfd` exposes direct commands.
2. `vertex_cfd` ships one or more packaged skill assets.
3. Direct execution preserves the current helper-backed behavior for parameter-run generation, post-processing, and in-situ visualization.

## Primary Files Likely To Change

- `src/mada_tools/simulation/vertex_cfd/direct.py`
- `src/mada_tools/simulation/vertex_cfd/skills/...`
- possibly helper reorganization under `src/mada_tools/simulation/vertex_cfd/`
- `src/mada_tools/extensions/builtins.py`
- tests under `tests/simulation/`, `tests/cli/`, and `tests/extensions/`

## Implementation Tasks

1. Add a direct execution adapter for `vertex_cfd`.
   - Reuse `VertexCFDHelper`.
   - Normalize any helper-contract inconsistencies that make direct invocation difficult.

2. Register direct commands through the extension system.
   - Expected actions likely include:
     - generating parameter runs
     - post-processing runs
     - generating in-situ visualization

3. Add skill files under `src/mada_tools/simulation/vertex_cfd/skills/`.
   - Separate skills are likely appropriate because the workflows are distinct.
   - Skills should document environment requirements and expected filesystem effects clearly.

4. Register the new skills and direct commands in `builtins.py`.

5. Add tests.
   - Discovery tests.
   - Direct invocation tests.
   - Any environment-sensitive or dependency-sensitive tests that are realistic for the current test environment.

## Design Constraints

1. Do not over-refactor the simulation stack unless needed for a clean direct interface.
2. Keep direct invocation thin and helper-backed.
3. Be explicit about environment-variable requirements and output artifacts.

## Acceptance Criteria

1. `vertex_cfd` is discoverable through the extension system as both direct commands and skills.
2. Users can invoke the main simulation helper workflows without MCP.
3. The implementation documents or tests the important runtime/environment assumptions.

## Out Of Scope

- New simulation capabilities unrelated to `vertex_cfd`.
- Large simulation-logic redesigns not required by the new direct surface.
