# Diagnose Job Failures

Use this skill when you need to inspect stdout and stderr logs for one completed or failed run directory without starting an MCP server.

## When To Use It

- A batch job failed and you want a structured failure summary.
- You need the recent tail of stdout and stderr before deciding what to do next.
- You want to diagnose one run directory directly from the CLI.

## Direct CLI Surface

Read tailed logs:

```bash
mada-tools job-monitor read-logs <run_location> <stdout_file> <stderr_file>
```

Summarize status and classify failures:

```bash
mada-tools job-monitor summarize-status <run_location> <stdout_file> <stderr_file> [--exit-code <code>]
```

Run either command in the background:

```bash
mada-tools job-monitor summarize-status <run_location> <stdout_file> <stderr_file> --background
mada-tools task-result <task_id>
```

## Required Inputs

- `run_location`: Path to the run directory that contains the logs.
- `stdout_file`: File name of the stdout log inside `run_location`.
- `stderr_file`: File name of the stderr log inside `run_location`.
- `exit_code`: Optional scheduler or application exit code for `summarize-status`.

## Expected Outputs

- `read-logs` returns JSON with `stdout` and `stderr` tails.
- `summarize-status` returns JSON with:
  - `exit_code`
  - `stdout_tail`
  - `stderr_tail`
  - `detected_failures`
- Background execution returns a JSON task descriptor with a `task_id`.
- `task-result` returns the persisted task state, result payload, or error.

## Environment And Config Assumptions

- `MONITOR_LOG_TAIL_BYTES` controls how much of each log file is tailed.
- `MONITOR_DEFAULT_STATUS_DEPTH` is accepted for parity with the existing server configuration.
- Background task state is stored under the normal MADA state directory unless `--tasks-file` is provided.
