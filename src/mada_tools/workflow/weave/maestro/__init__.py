# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
The `maestro` package provides MCP server functionality for executing
Maestro CLI commands for workflow execution.

Modules:
    server:
        The MCP server for Maestro command execution.
    command_executor:
        Interface for running and managing Maestro CLI commands.
"""

from mada_tools.workflow.weave.maestro.server import MaestroCommandExecutionServer

__all__ = ["MaestroCommandExecutionServer"]
