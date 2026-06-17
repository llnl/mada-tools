# MADA Tools Codebase Architecture

## Top-Level Repository Structure

At the top-level of the repository you'll find:

- Project configuration files (pyproject.toml, mkdocs.yaml, etc.)
- Directories to the rest of the project, including:
    - **Configuration:** Example configuration files
    - **Documentation:** Containing files for the documentation
    - **Examples:** Example agents for using MCP servers
    - **Scripts:** Bash scripts for stopping/stopping all of the existing MCP servers in this project
    - **[Source Code](#source-code-structure):** All of the source code for the MADA MCP Servers project
    - **[Tests](#test-code-structure):** All of the test files for testing the source code

Below is a visual representation of the top-level repository:

```bash
mada-tools/
├── src/
├── examples/
├── configs/
├── scripts/
├── .gitignore
├── pyproject.toml
├── mkdocs.yaml
└── README.md
```

## Source Code Structure

The source code for the MADA Tools repository is designed with the goal of easily being able to add new MCP servers and keep them organized. There are multiple directories to keep MCP servers organized:

- **Geometry:** This directory contains MCP servers for handling geometries
- **Scheduler:** This directory contains MCP servers for handling schedulers (e.g., flux, slurm)
- **Shared:** This directory stores shared files to be used throughout the repository. It does *not* contain any concrete MCP servers, but it does contain the base server that every MCP server must inherit from
- **Simulation:** This directory contains MCP servers for simulation codes and simulation utilities for creating samples
- **Surrogate:** This directory contains MCP servers for analysis tools (e.g., professor)

Each of these organizational directories will contain subdirectories for each MCP server that is defined. For example, the `scheduler/` directory will contain a subdirectory for the Flux MCP server and another subdirectory for the Slurm MCP server. Each of these subdirectories will need to have a `server.py` file that defines the MCP server and its available tools for that code. For more information on the `server.py` file, see [Adding New MCP Servers](./server_creation/adding_new_servers.md).

In addition to the directories related to storing MCP servers, there are some additional directories:

- **cli:** This directory contains code for setting up CLI commands (e.g., `start-servers`, `stop-servers`, etc.)
- **server_management:** This directory contains code for managing server life cycles and checking their statuses.

Below is a visual representation of the source code structure:

```bash
src/
└── mada_tools/
    ├── cli/                       # CLI command setup
    │   └── commands/                # Where subcommands/subparsers are defined
    ├── server_management/         # Functionality for managing server life cycles
    ├── shared/                    # Common utilities and base classes
    ├── scheduler/                 # Job scheduling tools
    │   ├── flux/                    # Flux workload manager
    │   │   └── server.py               # Flux MCP server definition
    │   └── slurm/                   # SLURM workload manager
    │       └── server.py               # SLURM MCP server definition
    ├── simulation/                # Simulation tools
    │   └── vertex_cfd/              # Vertex CFD simulations
    │       └── server.py               # Vertex CFD MCP server definition
    ├── geometry/                  # Geometry and mesh tools
    ├── monitor/                   # Workflow monitoring tools
    │   └── job_monitor/              # Scheduler-agnostic job monitor
    │       └── server.py               # Job Monitor MCP server definition
    └── surrogate/                 # Surrogate modeling and analysis tools
        └── professor/             # Professor analysis tools
            └── server.py               # Professor MCP server definition
```

## Test Code Structure

Tests should follow the same directory structure as the [source code](#source-code-structure). There should be organizational directories and appropriate test files underneath them. For example, tests for the Vertex-CFD MCP server will live at `tests/simulation/vertex_cfd/` just like its source code lives at `mada_tools/simulation/vertex_cfd/`.

There can be a `conftest.py` file in each testing directory to help define shared fixtures for individual servers. There will also be a `conftest.py` file at the top-level directory for fixtures that are shared across the entire test suite.

For more on testing, see the [MADA Tools Testing Guide](./testing.md).
