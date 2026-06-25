# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
MADA MCP Servers package.

This is the top-level package for the MADA tools repository. This
package contains custom MCP servers for use in the MADA framework
and CLI functionality for interacting with the servers.

Subpackages:
    cli: Functionality for interacting with the command line interface.
    geometry: MCP servers for geometry tooling.
    monitor: MCP servers for tooling to help with job monitoring.
    scheduler: MCP servers for tooling related to schedulers (like SLURM,
        Flux, etc.)
    server_management: Functionality for managing server life cycles.
    shared: Utility and abstract classes that are shared throughout
        the codebase.
    simulation: MCP servers for simulation code tooling.
    surrogate: MCP servers containing surrogate modeling tooling.

Modules:
    logging_config: Utility functions to set up logging in the codebase.
    main: The entry point to the MADA tools repository.
"""

from mada_tools.server_management.server_manager import ServerManager
from mada_tools.shared.base_server import BaseMCPServer
from mada_tools.shared.exceptions import MCPServerError, ToolExecutionError
from mada_tools.workflow.weave import WEAVEStudyConstructionServer

__version__ = "0.1.1"

VERSION = __version__

# No server imports - each server runs independently via entry points
__all__ = [
    "BaseMCPServer",
    "MCPServerError",
    "ServerManager",
    "ToolExecutionError",
    "WEAVEStudyConstructionServer",
]
