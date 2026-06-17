# MADA Tools

This repository contains AI tooling for the MADA (Multi-Agent Design Assistant) ecosystem, including Model Context Protocol (MCP) servers.

## Repository Structure

```
mada-tools/
├── src/
│   └── mada_tools/
│       ├── shared/                        # Common utilities and base classes
│       ├── scheduler/                     # Job scheduling tools
│       │   ├── flux/                      # Flux workload manager
│       │   └── slurm/                     # SLURM workload manager
│       ├── workflow/                      # Workflow orchestration tools
│       ├── simulation/                    # Simulation tools
│       │   └── vertex_cfd/                # Vertex-CFD multiphysics
│       ├── geometry/                      # Geometry and mesh tools
│       ├── surrogate/                     # Surrogate modeling and analysis tools
│       │   └── professor/                 # Professor analysis tools
│       └── monitor/                       # Job monitoring and failure diagnostics
│           └── job_monitor/               # Scheduler-agnostic log analysis server
├── examples/                              # Example agents for using MCP servers
├── configs/                               # Configuration files
├── scripts/                               # Deployment and startup scripts
```

## MCP Servers by Category

### Scheduler
- **Flux**: Job scheduling and execution using Flux scheduler
- **SLURM**: Job scheduling and execution using SLURM

### Simulation
- **Vertex-CFD**: Vertex-CFD mini-application tools

### Geometry
- Coming soon!

### Surrogate
- **Professor**: Surrogate modeling tools

### Monitor
- **Job Monitor**: Scheduler-agnostic job diagnostics


## Setup

```bash
python -m venv venv
source venv/bin/activate

# Basic installation (without Flux)
pip install -e .

# With Flux scheduler support
pip install -e ".[flux]"

# Install all optional dependencies
pip install -e ".[all]"
```

Set required environment variables for Professor server (LLM access):
```bash
export API_KEY="your-api-key-here"
export API_BASE_URL="https://api.openai.com/v1/responses"
```

## Quick Start

Each MCP server run independently, so you can pick and choose which servers to start. There are multiple ways to start servers:

1. **With the `mada-tools` command** (recommended):
    ```bash
    mada-tools start-servers configs/development.json
    ```

    With this command, you can also choose individual servers from the configuration file to start. For example, to start just flux and vertex_cfd:
    ```bash
    mada-tools start-servers configs/development.json -s flux vertex_cfd
    ```

2. **With individual commands & config files**:
    ```bash
   mada-mcp-flux --config configs/development.json
   mada-mcp-slurm --config configs/development.json
   mada-mcp-professor --config configs/development.json
   mada-mcp-monitor --config configs/development.json
   ```

3. **With individual commands & command line arguments**:
    ```bash
   # Using stdio transport (no host/port needed)
   mada-mcp-flux --transport stdio
   mada-mcp-slurm --transport stdio

   # Using streamable-http with custom host/port
   mada-mcp-flux --transport streamable-http --host localhost --port 9001
   mada-mcp-slurm --transport streamable-http --host localhost --port 9002
   mada-mcp-professor --transport streamable-http --host localhost --port 9006
   mada-mcp-monitor --transport streamable-http --host localhost --port 9007
   ```

3. **Start with defaults** (streamable-http on localhost:8000):
   ```bash
   mada-mcp-flux
   mada-mcp-slurm
   mada-mcp-professor
   mada-mcp-monitor
   ```

4. **Start all servers at once**:
   ```bash
   ./scripts/start_all_servers.sh
   ```

## Using Example Agents with MCP Servers

The `examples/` directory contains example agents that can connect to and use MADA MCP servers. This examples demonstrate how to integrate MCP tools with Large Language Models.

### Quick Start with Multi-Server Agent

1. **Set API credentials** (required for example agent):
    ```bash
    export API_KEY="your-api-key"
    export API_BASE_URL="https://api.openai.com/v1/responses"
    ```

   If using LivAI's endpoint, request a LivAPI key.

2. **Start MCP servers**:
    Starting all servers:
    ```bash
    mada-tools start-servers configs/development.json
    ```

    Starting specific servers:
    ```bash
    mada-tools start-servers configs/development.json -s flux vertex_cfd
    ```

3. **Run the multi-server agent**:
   ```bash
   cd examples
   python simple_agent_loop.py --config config.json
   ```

   **Use custom config**:
   ```bash
   python simple_agent_loop.py --config my_config.json
   ```

### Multi-Server Workflow Examples

The agent can now connect to multiple MCP servers simultaneously and use all their tools in a single session:

**Complete Parameter Sweep Workflow**:
Edit `config.json` to include only vertex_cfd and flux in `"mcp_servers"`, then:
```bash
python simple_agent_loop.py
```

Try this example prompt:
```
Generate 10 runs in ./testrun with parameters velocity_0, velocity_1,  "Exodus Write Frequency", "Minimum Time Step", "Maximum Time Step",  "Initial Time Step", and "Final Time Index"  with lower bounds 0, 5, 10, 1e-4, 1e-3, 1e-3, 1000 and upper bounds 5, 10, 10, 1e-4, 1e-3, 1e-3, 1000
```

### Job Diagnostic Example

**Analyze Existing Vertex_CFD Runs**:
Start the server using: `mada-mcp-monitor --port 8006 &`, then run the diagnostic script:
```bash
python diagnose_existing_runs.py --monitor http://localhost:8006/mcp --study /path/to/study
```

This script will:
```
Scan the directory /path/to/study (for example ./testrun from above), locate all run_i folders, read the tail of run_i.out and run_i.err, and produce a structured summary for each run. The Job Monitor will classify failures such as segmentation faults, MPI rank aborts, missing files, permission errors, out-of-memory terminations, or scheduler preemptions. If no known signatures match, the summary includes an unclassified entry containing a log excerpt.
```

### Configuration

The agent uses `examples/config.json` for all configuration:
- **Model settings**: Configure which model and API endpoint to use
- **Server selection**: Simply include/exclude servers in the `"mcp_servers"` section

Example config:
```json
{
  "model": {
    "model": "o3",
    "api_key": "${API_KEY}",
    "base_url": "${API_BASE_URL:-https://api.openai.com/v1/responses}"
  },
  "mcp_servers": {
    "flux": {
      "url": "http://localhost:8001/mcp",
      "description": "Flux workload manager for job execution"
    },
    "professor": {
      "transport": "streamable-http",
      "url": "http://localhost:8005/mcp",
      "description": "Professor visualization tool"
    }
  }
}
```

The agent provides an interactive chat interface where you can use natural language to orchestrate complex multi-server workflows.

## Configuration

Server configurations can be found in the `configs/` directory:
- `development.json` - Development settings

### Environment Variable Expansion

Configuration files support environment variable expansion for secure handling of sensitive values:

```json
{
  "servers": {
    "professor": {
      "env_vars": {
        "API_KEY": "${API_KEY}",
        "API_BASE_URL": "${API_BASE_URL:-https://api.openai.com/v1/responses}"
      }
    }
  }
}
```

Supported formats:
- `${VAR_NAME}` - Expands to the value of `VAR_NAME` environment variable
- `${VAR_NAME:-default}` - Uses default value if `VAR_NAME` is not set

This allows you to:
Set environment variables: `export API_KEY="your-key"` and reference them securely in config: `"API_KEY": "${API_KEY}"`

### Transport Methods

MCP servers support different transport methods:

- **streamable-http**: Network-based HTTP transport (default)
  - Good for distributed systems and production
  - Supports streaming responses
  - Requires host and port configuration

- **stdio**: standardio-based transport
  - Good for local development and direct process communication
  - No network configuration needed
  - Communicates via stdin/stdout

Example configuration:
```json
{
  "servers": {
    "flux": {
      "transport": "streamable-http",
      "host": "localhost",
      "port": 8001,
      "env_vars": {
        "FLUX_HANDLE": "default"
      }
    },
    "professor": {
      "host": "localhost",
      "port": 8005,
      "transport": "streamable-http",
      "env_vars": {
        "API_KEY": "${API_KEY}",
        "MODEL": "${MODEL:-o3}",
        "PROF_VIS_PATH": "/usr/workspace/prof/bin/prof-vis",
        "API_BASE_URL": "${API_BASE_URL:-https://api.openai.com/v1/responses}"
      }
    }
  }
}
```

**Note**: `host` and `port` are only required when `transport` is `streamable-http`. For `stdio` transport, omit `host` and `port` since communication happens via process stdin/stdout.

## Troubleshooting

### Missing Dependencies

Each server has specific dependencies:

- **Professor Server**: Requires API access
  ```bash
  export API_KEY="your-api-key"
  ```

### Common Issues

1. **"No module named 'flux'"**: Install with Flux support: `pip install -e ".[flux]"`
2. **"Failed to connect to Flux"**: Ensure Flux is running and accessible
3. **API errors**: Check `API_KEY` environment variable. If using LivAI's endpoint, request a LivAPI key.

## Building Documentation Locally

Install the optional dependencies:

```bash
pip install -e .[docs]
```

Then build the documentation:

```bash
mkdocs serve
```

This will provide a localhost URL for you. Open that in your browser to view the documentation.


## Release

MADA Tools is distributed under the terms of the Apache License (Version 2.0) WITH LLVM Exception.

All new contributions must be made under the Apache 2.0 License WITH LLVM Exception.

See [LICENSE](./LICENSE), [COPYRIGHT](./COPYRIGHT), and [NOTICE](./NOTICE) for details.

SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

LLNL-CODE-2019936
