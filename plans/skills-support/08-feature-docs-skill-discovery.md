# Branch Brief: `feature/docs-skill-discovery`

## Goal

Update the repository documentation to reflect the new architecture once the foundational and capability rollout branches have landed in `feature/skills-support`.

This branch should align the docs with the implemented behavior, not define architecture in a vacuum.

## Dependencies

This branch should be based on `feature/skills-support` after the architecture branch, pilot branch, and relevant built-in rollout branches are merged.

## Required Outcomes

1. User documentation explains the difference between MCP servers, direct commands, and packaged skills.
2. Developer documentation explains the new capability layout and extension registration model.
3. Plugin authors have documentation for adding skill files and direct commands through the extension system.
4. The README and docs landing pages no longer mention skills abstractly without implementation guidance.

## Primary Files Likely To Change

- `README.md`
- `docs/index.md`
- `docs/user_guide/cli.md`
- `docs/user_guide/index.md`
- `docs/developer_guide/architecture.md`
- `docs/developer_guide/server_creation/adding_new_servers.md`
- `docs/developer_guide/server_creation/extensions.md`
- additional new docs pages as needed

## Implementation Tasks

1. Update top-level project documentation.
   - Explain the three capability surfaces:
     - MCP server
     - direct command
     - packaged skill

2. Add or update user-guide documentation.
   - Describe skill discovery.
   - Describe direct command discovery and usage.
   - Document the relationship between skills and direct commands.

3. Update developer-guide architecture docs.
   - Document the preferred capability layout:

```text
src/mada_tools/<domain>/<capability>/
  __init__.py
  server.py
  direct.py
  core/
  skills/
```

4. Update extension/plugin author guidance.
   - Explain manifest registration for skills and direct commands.
   - Explain packaging of skill markdown assets.
   - Explain how plugin repositories should mirror the same capability pattern.

5. Document background task behavior for direct invocation if the CLI exposes it.

6. Update command examples and any supported-capability tables that need to mention direct/skill-backed usage.

## Design Constraints

1. Document what actually exists after the rollout branches, not aspirational behavior that is not implemented.
2. Keep examples consistent with real CLI command names and manifest fields.
3. Preserve useful MCP documentation rather than replacing it; expand it to cover the new surfaces.

## Acceptance Criteria

1. The docs tell a coherent story for users and plugin authors.
2. The README and docs index no longer imply skill support without explaining how it works.
3. The developer docs provide enough guidance for future capability authors to follow the new pattern.

## Out Of Scope

- Major code changes unrelated to documentation.
- Changing implemented CLI behavior solely to simplify docs.
