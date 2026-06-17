# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
The server management package provides classes and utilities for managing MCP
server processes, including configuration, lifecycle operations, and persistent
state tracking. It enables discovery, launching, monitoring, and safe shutdown
of server instances, and supports robust state persistence across sessions.

Modules:
    server_info:
        Data structures and enumerations for MCP server management.
    server_manager:
        Server management utilities for MCP servers.
    state_manager:
        Persistent state management for MCP server processes.
"""

from mada_tools.server_management.server_info import ServerInfo, ServerStatus
from mada_tools.server_management.server_manager import ServerManager
from mada_tools.server_management.state_manager import ServerStateManager

__all__ = [
    "ServerInfo",
    "ServerStatus",
    "ServerManager",
    "ServerStateManager",
]
