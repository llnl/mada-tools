# Slurm MCP Server

The Slurm MCP Server provides an interface for job scheduling and execution using the [Slurm](https://slurm.schedmd.com/) workload manager. It exposes MCP tools for queued `sbatch` submission, direct `srun` execution, job monitoring, and cluster inspection. The server supports both scheduler-visible parameter sweeps and lightweight direct execution for debugging.

## Requirements

This server requires that Slurm is installed and available on the host system.

## Server Configuration

To use the Slurm server, add a `slurm` entry to your server configuration file.

=== "streamable-http transport"

    ```json
    "slurm": {
        "host": "localhost",
        "port": 8102,
        "transport": "streamable-http"
    }
    ```

=== "stdio transport"

    ```json
    "slurm": {
        "transport": "stdio"
    }
    ```

## Available MCP Tools

| Tool Name                         | Description                                                                  |
| --------------------------------- | ---------------------------------------------------------------------------- |
| `submit_jobs`                     | Submit generated run manifests. Defaults to queued `sbatch` submission.      |
| `check_job_status`                | Check the status of submitted job sets.                                      |
| `continuously_check_job_status`   | Poll job status until a bounded wait condition or timeout.                   |
| `submit_command`                  | Run one ad hoc command using `srun`; not for generated run manifests.        |
| `list_queue`                      | List all jobs in the Slurm queue using `squeue`.                             |
| `get_cluster_info`                | Get information about the cluster nodes using `sinfo`.                       |

## Tool Selection

Use `submit_jobs` for generated simulation/orchestration runs. Leave `blocking`
at its default `false` for normal scheduler-backed workflows because it queues
runs with `sbatch` and returns real Slurm job IDs. Set `blocking=true` only for
lightweight direct debugging when queued jobs are not needed. Use
`submit_command` only for one known ad hoc command, not for `run_instances.json`
or parameter sweeps.

Use `check_job_status(job_set_id=...)` after `submit_jobs(blocking=false)` to
refresh and report the returned job set plus real Slurm job IDs. Use
`continuously_check_job_status` only when the MCP server should wait for all
selected jobs to reach terminal status, or with `wait_until="any_running"` when
downstream work should start as soon as at least one job begins running.

## Key Features

- **Queued Job Submission:** Submit parameterized runs through `sbatch` and track real Slurm job IDs.
- **Parallel Direct Execution:** Launch multiple parameterized runs directly using `srun`, with control over concurrency.
- **Single Command Execution:** Run arbitrary shell commands on the cluster using `srun`, with customizable resources.
- **Job Monitoring:** Query the status of submitted job sets or individual jobs.
- **Bounded Status Waiting:** Poll scheduler status with explicit interval and timeout controls for tests and downstream workflows.
- **Queue Inspection:** List all jobs currently in the Slurm queue.
- **Cluster Information:** Query cluster node and partition status using `sinfo`.
- **Configurable Server:** Adjust host, port, and transport parameters to fit your cluster environment.
