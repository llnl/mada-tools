# Supported MCP Servers

This section of the [User Guide](../index.md) helps users identify the MCP servers available in the MADA Tools project, understand their capabilities, and learn how these servers are organized.

## Server Organization

Servers are grouped into categories based on their primary capabilities. The following categories are currently supported:

<!-- Group these alphabetically -->

| Category Name                         | Category Description                          |
| ------------------------------------- | --------------------------------------------- |
| [Geometry](./geometry/index.md)       | Servers that handle geometry/mesh generation  |
| [Scheduler](./scheduler/index.md)     | Servers for running job schedulers            |
| [Simulation](./simulation/index.md)   | Servers for simulation codes                  |
| [Surrogate](./surrogate/index.md)     | Servers for analysis tools                    |
| [Workflow](./workflow/index.md)       | Servers for workflow orchestration            |

## Available Servers

The table below lists all servers available in the MADA Tools project, grouped by category and sorted alphabetically:

<!-- Group these by category and alphabetically -->

| Server Name                           | Server Description                                        | Server Category                       | Command to Start      |
| ------------------------------------- | --------------------------------------------------------- | ------------------------------------- | --------------------- |
| [Flux](./scheduler/flux.md)           | Flux scheduler for job scheduling and execution           | [Scheduler](./scheduler/index.md)     | `mada-mcp-flux`       |
| [Slurm](./scheduler/slurm.md)         | Slurm workload manager for job scheduling and execution   | [Scheduler](./scheduler/index.md)     | `mada-mcp-slurm`      |
| [Vertex-CFD](./simulation/vertex_cfd.md) | Vertex-CFD application tools                              | [Simulation](./simulation/index.md)   | `mada-mcp-vertex-cfd` |
| [Professor](./surrogate/professor.md)    | Professor analysis and visualization tools                | [Surrogate](./surrogate/index.md)     | `mada-mcp-professor`  |
| [Maestro Command Executor](./workflow/maestro.md) | Maestro command execution tools                  | [Workflow](./workflow/index.md)       | `mada-mcp-maestro-command-executor`  |
| [WEAVE Study Constructor](../../developer_guide/server_creation/weave_study_servers.md) | Abstract server for creating WEAVE studies | [Workflow](./workflow/index.md)     | N/A |
