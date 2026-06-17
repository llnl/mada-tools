# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
CLI commands for MCP server management.

The `commands` package provides a suite of command-line interface (CLI)
commands for managing MCP servers. Each command is implemented as a separate
module and is designed to be integrated with the main argument parser for
flexible and scriptable server control.

Modules:
    base_cmd:
        Defines the abstract base class `BaseCmd` for all CLI commands,
        standardizing the interface for argument parsing and command execution.
    start_servers:
        Implements the `StartServersCmd` for starting one or more MCP servers.
    stop_servers:
        Implements the `StopServersCmd` for stopping running MCP servers.
    restart_servers:
        Implements the `RestartServersCmd` for restarting MCP servers.
    servers_status:
        Implements the `ServersStatusCmd` for displaying the status of MCP servers.
"""

from mada_tools.cli.commands.available_servers import AvailableServersCmd
from mada_tools.cli.commands.restart_servers import RestartServersCmd
from mada_tools.cli.commands.servers_status import ServersStatusCmd
from mada_tools.cli.commands.start_servers import StartServersCmd
from mada_tools.cli.commands.stop_servers import StopServersCmd

# Keep these in alphabetical order
ALL_COMMANDS = [
    AvailableServersCmd(),
    RestartServersCmd(),
    ServersStatusCmd(),
    StartServersCmd(),
    StopServersCmd(),
]

__all__ = [
    "AvailableServersCmd",
    "RestartServersCmd",
    "ServersStatusCmd",
    "StartServersCmd",
    "StopServersCmd",
]
