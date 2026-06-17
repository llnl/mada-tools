# Flux MCP Server

The Flux MCP Server provides an interface for job scheduling and execution using the [Flux](https://flux-framework.org/) resource manager. It exposes MCP tools for submitting, monitoring, and managing computational jobs, supporting both synchronous and asynchronous workflows. The server can return real Flux job IDs for scheduler-visible jobs.

## Requirements

This server requires that Flux is installed and available on the host system.

## Server Configuration

To use the Flux server, add a `flux` entry to your server configuration file.

=== "streamable-http transport"

    ```json
    "flux": {
        "host": "localhost",
        "port": 8101,
        "transport": "streamable-http",
        "env_vars": {
            "FLUX_HANDLE": "default",
            "FLUX_USE_PERSISTENT_EXECUTOR": "true",
            "SPINDLE_FLUXOPT": "disable"
        }
    }
    ```

=== "stdio transport"

    ```json
    "flux": {
        "transport": "stdio",
        "env_vars": {
            "FLUX_HANDLE": "default",
            "FLUX_USE_PERSISTENT_EXECUTOR": "true"
        }
    }
    ```

| Environment Variable             | Description                                                                                  |
| -------------------------------- | -------------------------------------------------------------------------------------------- |
| `FLUX_HANDLE`                    | Flux handle target. Use `default` unless you need to connect to a specific Flux URI.          |
| `FLUX_USE_PERSISTENT_EXECUTOR`   | Compatibility setting for internal shared-executor mode. Direct submissions do not need it.   |
| `SPINDLE_FLUXOPT`                | Optional. Set to `disable` for local LLNL development brokers where Spindle blocks task start. |

## Available MCP Tools

| Tool Name                         | Description                                                              |
| --------------------------------- | ------------------------------------------------------------------------ |
| `submit_command`                  | Submit one ad hoc command to Flux. Not for generated run manifests.      |
| `submit_jobs`                     | Submit generated run manifests. Defaults to async Flux submission.       |
| `check_job_status`                | Check status of tracked jobs or a known Flux job ID.                     |
| `continuously_check_job_status`   | Poll job status until a bounded wait condition or timeout.               |

## Tool Selection

Use `submit_command` for one known command. Use `submit_jobs` for generated run
manifests from simulation/orchestration workflows, including a path to
`run_instances.json`. Leave `blocking` at its default `false` for Gradio or
long-running workflows because it returns immediately with real Flux job IDs.
Set `blocking=true` only when the caller explicitly wants to wait until all
generated runs finish, such as small debugging runs or end-to-end tests.

Use `check_job_status(job_id=...)` after `submit_jobs(blocking=false)` to refresh
and report the returned local MADA tracking ID plus the real Flux IDs. Use
`continuously_check_job_status` only when the MCP server should wait for all
selected jobs to reach terminal status, or with `wait_until="any_running"` when
downstream work should start as soon as at least one job begins running.

## Key Features

- **Job Submission:** Submit single or multiple jobs to the Flux scheduler, with customizable resources and parameters.
- **Asynchronous Execution:** Launch jobs asynchronously for large parameter sweeps or batch processing.
- **Synchronous Execution:** Wait for completion of computational runs, suitable for workflows requiring immediate results.
- **Job Monitoring:** Query job status by local tracking ID, real Flux job ID, or for all jobs managed by the server.
- **Bounded Status Waiting:** Poll scheduler status with explicit interval and timeout controls for tests and downstream workflows.
- **Configurable Environment:** Adjust Flux environment variables and server parameters for your cluster setup.
