# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
CLI commands for MADA Tools.

The `commands` package provides a suite of command-line interface (CLI)
commands. Each command is implemented as a separate module and is designed to
be integrated with the main argument parser for flexible and scriptable control.

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
    export_docs:
        Implements the `ExportDocsCmd` for exporting packaged documentation sources.
"""

from importlib import import_module

_COMMAND_EXPORTS = {
    "AvailableServersCmd": ("mada_tools.cli.commands.available_servers", "AvailableServersCmd"),
    "ExportDocsCmd": ("mada_tools.cli.commands.export_docs", "ExportDocsCmd"),
    "RestartServersCmd": ("mada_tools.cli.commands.restart_servers", "RestartServersCmd"),
    "ServersStatusCmd": ("mada_tools.cli.commands.servers_status", "ServersStatusCmd"),
    "StartServersCmd": ("mada_tools.cli.commands.start_servers", "StartServersCmd"),
    "StopServersCmd": ("mada_tools.cli.commands.stop_servers", "StopServersCmd"),
}


def __getattr__(name):
    """Lazily load command classes and the main command registry.

    Loading the complete command registry imports server-management commands
    that require the MCP runtime dependency stack. Individual command modules
    should remain importable without paying that cost.
    """
    if name == "ALL_COMMANDS":
        commands = [
            __getattr__("AvailableServersCmd")(),
            __getattr__("ExportDocsCmd")(),
            __getattr__("RestartServersCmd")(),
            __getattr__("ServersStatusCmd")(),
            __getattr__("StartServersCmd")(),
            __getattr__("StopServersCmd")(),
        ]
        globals()[name] = commands
        return commands

    if name in _COMMAND_EXPORTS:
        module_name, attribute_name = _COMMAND_EXPORTS[name]
        value = getattr(import_module(module_name), attribute_name)
        globals()[name] = value
        return value

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ALL_COMMANDS",
    "AvailableServersCmd",
    "ExportDocsCmd",
    "RestartServersCmd",
    "ServersStatusCmd",
    "StartServersCmd",
    "StopServersCmd",
]
