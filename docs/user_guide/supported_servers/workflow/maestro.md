# Maestro Command Execution MCP Server

The Maestro Command Execution MCP Server provides MCP tools for running and managing Maestro workflows through the Maestro CLI. It wraps common workflow operations, letting clients start workflows, check their status, update running studies, and cancel active workflows.

## Requirements

- The [Maestro workflow orchestration tool](https://maestrowf.readthedocs.io/en/latest/) from WEAVE must be installed and available in the environment.
- Workflow YAML files must be valid Maestro specifications.

## Server Configuration

To use the Maestro Command Execution server, copy and paste the below configuration into your configuration file.

=== "streamable-http transport"

    ```json
    "maestro_command_executor": {
        "host": "localhost",
        "port": 8300,
        "transport": "streamable-http",
    }
    ```

=== "stdio transport"

    ```json
    "maestro_command_executor": {
        "transport": "stdio",
    }
    ```

## Available MCP Tools

| Tool Name                 | Description                                                                       |
| ------------------------- | --------------------------------------------------------------------------------- |
| `run_workflow`     | Run a Maestro workflow from a workflow YAML file with optional runtime controls and parameter generation support. |
| `get_statuses`     | Query the status of one or more Maestro workflow output directories. |
| `update_workflows` | Update running workflows with new `rlimit`, `throttle`, or `sleeptime` settings. |
| `cancel_workflows` | Cancel one or more running Maestro workflows. |

## Key Features

- Runs Maestro workflows from YAML specifications.
- Supports workflow status querying for active studies.
- Allows live updates to running workflow settings.
- Supports cancellation of one or more workflows.
