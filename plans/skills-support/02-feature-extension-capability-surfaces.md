# Branch Brief: `feature/extension-capability-surfaces`

## Goal

Add the shared infrastructure needed for skills and direct commands to exist as first-class extension surfaces alongside MCP servers.

This branch is foundational. It should not roll out multiple concrete built-in capabilities beyond the minimum needed to prove the registration shape.

## Required Outcomes

1. The extension manifest model can represent:
   - MCP servers
   - skill assets
   - direct commands
2. The extension registry can discover and validate all three surface types.
3. Background task execution is available through a transport-agnostic shared runtime rather than being owned solely by `BaseMCPServer`.
4. Packaged skill markdown files can be distributed with `mada_tools`.

## Primary Files Likely To Change

- `src/mada_tools/extensions/manifest.py`
- `src/mada_tools/extensions/registry.py`
- `src/mada_tools/extensions/builtins.py`
- `src/mada_tools/shared/base_server.py`
- `src/mada_tools/shared/task_runtime.py` or equivalent new shared module
- `pyproject.toml`
- tests under `tests/extensions/` and `tests/shared/`

## Implementation Tasks

1. Extend the extension manifest datamodel.
   - Add `SkillRegistration`.
   - Add `DirectCommandRegistration`.
   - Extend `ExtensionManifest` with `skills` and `direct_commands` collections.

2. Define validation rules for the new registration types.
   - Skill registrations should validate required metadata and a package-distributed skill path format.
   - Direct command registrations should validate required metadata and their import target information.

3. Extend `ExtensionRegistry`.
   - Discover, validate, and expose skill registrations.
   - Discover, validate, and expose direct command registrations.
   - Preserve current MCP discovery behavior.

4. Extract background task logic from `BaseMCPServer`.
   - Move task tracking and task result handling into a shared, transport-agnostic runtime.
   - Keep `BaseMCPServer` behavior stable by delegating to the shared runtime.

5. Update built-in registrations.
   - Add the new manifest fields in `builtins.py`.
   - It is acceptable for this branch to leave them empty or minimally populated if full rollout is deferred to later branches.

6. Update packaging.
   - Ensure `skills/**/*.md` style assets can be shipped in distributions.
   - Keep the change generic enough for plugin packages to follow the same convention.

7. Add tests.
   - Manifest structure and validation tests.
   - Extension-registry discovery tests.
   - Shared task runtime tests.
   - Packaging-related tests if the repo already has a pattern for validating package data.

## Design Constraints

1. Do not hardcode built-in skill or direct-command behavior into the CLI here.
2. Keep the new background task runtime reusable by both MCP and direct invocation.
3. Prefer minimal structural changes that unlock later branches without forcing full capability migrations immediately.

## Acceptance Criteria

1. There is a stable manifest shape for skills and direct commands.
2. There are registry accessors for all discovered built-in extension surfaces.
3. `BaseMCPServer` still works, but no longer owns the background task implementation details directly.
4. The package configuration can include skill markdown files.
5. Tests cover the new registry and runtime behavior.

## Out Of Scope

- Full direct CLI implementation.
- Capability-specific skill files beyond minimal scaffolding.
- User-facing documentation refresh.
