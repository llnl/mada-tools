# Branch Brief: `feature/skills-support`

## Purpose

This branch is the integration branch for the broader skills-support effort. It is a copy of `develop` that receives merges from the implementation branches listed in `plans/skills-support/README.md`.

This branch is not the place for primary feature development unless a change is specifically about integrating already-completed child branches.

## Responsibilities

1. Keep the branch briefs in `plans/skills-support/` available and up to date.
2. Receive merges from child branches.
3. Resolve merge conflicts carefully, preserving the intended architecture from the child branches.
4. Run integration-level verification after merges land.
5. Prepare the final branch state for merging back into `develop`.

## Implementation Rules

1. Do not introduce new capability behavior directly on this branch when it can live in a child branch.
2. Only make direct edits here for:
   - conflict resolution
   - branch-plan maintenance
   - integration fixes that depend on multiple merged branches
   - final consistency cleanup before merging to `develop`
3. If an issue is isolated to one capability or one architectural layer, send it back to the appropriate child branch instead of fixing it here.

## Integration Checklist

1. Confirm the child branch is based on `feature/skills-support` or is rebased appropriately.
2. Merge the child branch.
3. Run targeted tests for the area touched by that branch.
4. After multiple child merges, run broader regression checks covering:
   - extension discovery
   - CLI parsing
   - background task execution
   - built-in capability discovery
5. Resolve any cross-branch naming or registration collisions.
6. Keep documentation and plan files aligned with the merged state.

## Final Pre-Merge Checklist

Before merging `feature/skills-support` into `develop`:

1. Verify all planned child branches are merged.
2. Verify the extension system discovers MCP servers, skills, and direct commands correctly.
3. Verify packaged skill files are included in the distribution configuration.
4. Verify CLI help and discovery commands reflect the new architecture.
5. Run the full relevant test suite and document any known gaps.

## Out Of Scope

- Building the primary architecture from scratch.
- Rolling out one capability's direct command support directly on this branch unless it is part of conflict resolution.
- Large refactors that are not required for final integration.
