# Skills Support Branch Plan

This directory contains branch-specific implementation briefs for adding tool-agnostic, package-distributed skill support to MADA Tools.

## Branch Model

- Create `feature/skills-support` from `develop`.
- Create each implementation branch from `feature/skills-support` unless a different base is explicitly needed.
- Merge each completed implementation branch back into `feature/skills-support`.
- Merge `feature/skills-support` into `develop` only after all child branches are complete and conflicts are resolved.

## Planned Branches

1. `feature/skills-support`
   - Integration branch only.
   - Holds the branch briefs in this directory and receives merges from child branches.
2. `feature/extension-capability-surfaces`
   - Adds extension-manifest support for skills and direct commands.
   - Extracts transport-agnostic background task execution from the MCP base class.
3. `feature/direct-cli-pilot-job-monitor`
   - Proves the architecture end-to-end using `job_monitor`.
   - Adds the first packaged skill asset and first direct command surface.
4. `feature/skills-scheduler-domain`
   - Adds direct command and skill support for `flux` and `slurm`.
5. `feature/skills-surrogate-domain`
   - Adds direct command and skill support for `professor`.
6. `feature/skills-workflow-domain`
   - Adds direct command and skill support for `maestro_command_executor`.
7. `feature/skills-simulation-domain`
   - Adds direct command and skill support for `vertex_cfd`.
8. `feature/docs-skill-discovery`
   - Updates user and developer docs after the architecture and built-in rollouts stabilize.

## Recommended Merge Order

1. `feature/extension-capability-surfaces`
2. `feature/direct-cli-pilot-job-monitor`
3. `feature/skills-scheduler-domain`
4. `feature/skills-surrogate-domain`
5. `feature/skills-workflow-domain`
6. `feature/skills-simulation-domain`
7. `feature/docs-skill-discovery`

## Common Architecture Rules

- Preserve the existing domain-first package layout.
- For each capability, keep the layers co-located:

```text
src/mada_tools/<domain>/<capability>/
  __init__.py
  server.py
  direct.py
  core/
  skills/
```

- `server.py` remains the MCP transport adapter.
- `direct.py` becomes the direct/skill-backed execution adapter.
- Business logic should live in helpers, managers, or `core/` modules.
- Skills are tool-agnostic assets distributed with the package.
- Skill and direct-command discovery should flow through the extension system, not hardcoded imports.
- Background and long-running execution should use a transport-agnostic shared task runtime.

## Notes For Separate Chats

When starting a new implementation chat, paste the contents of the relevant branch brief from this directory and specify that the work should be done on that branch only.
