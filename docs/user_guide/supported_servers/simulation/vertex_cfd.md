# Vertex-CFD MCP Server

The Vertex-CFD MCP Server provides an interface for setting up, running, and analyzing [Vertex-CFD](https://github.com/ORNL/VERTEX-CFD) simulations. It exposes MCP tools for generating parameter sweeps, running simulations, and comparing results between runs. The server is designed to integrate with job schedulers (like Flux or Slurm) and can be used as part of a larger simulation workflow.

## Requirements

This server requires:

- That Vertex-CFD is compiled and readily available on the host system
- Environment variables set for (these can be given in the configuration file or set at the CLI prior to launching the server):
    - `VERTEX_CFD_PATH`: the top level directory of the Vertex-CFD src, build, and install directories
    - `VERTEX_CFD_RESULTS_DIR`: the directory to use for simulation results

## Server Configuration

To use the Vertex-CFD server, copy and paste the below configuration into your configuration file. You'll need to fill in the missing settings.

=== "streamable-http transport"

    ```json
    "vertex_cfd": {
        "host": ,
        "port": ,
        "transport": "streamable-http",
        "env_vars": {
            "VERTEX_CFD_PATH": ,
            "VERTEX_CFD_RESULTS_DIR":
        }
    }
    ```

=== "stdio transport"

    ```json
    "vertex_cfd": {
        "transport": "stdio",
        "env_vars": {
            "VERTEX_CFD_PATH": ,
            "VERTEX_CFD_RESULTS_DIR":
        }
    }
    ```

## Available MCP Tools

| Tool Name                 | Description                                                               |
| ------------------------- | ------------------------------------------------------------------------- |
| `generate_parameter_runs` | Generate parameter sets and directories for a Vertex-CFD parameter sweep. |
| `post_process_runs`       | Analyze simulation results and compare results between runs.              |

## Key Features

- **Parameter Sweep Generation:** Create parameter sets and simulation directories for large-scale studies, ready for batch submission.
- **Run Comparison:** Analyze simulation results and compare results between runs.
- **Integration Ready:** Output from `generate_parameter_runs` is formatted for easy consumption by job schedulers like Flux or Slurm.
- **Customizable Paths:** All paths for executables, results, and scripts are configurable via environment variables.
