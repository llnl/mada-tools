# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Data structures and enumerations for MCP server management.

This module defines the core types used for representing MCP server
configuration and runtime state, including the `ServerStatus` enumeration
and the `ServerInfo` dataclass. These structures support serialization
and deserialization for persistent server state tracking and configuration
management.
"""

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional


class ServerStatus(Enum):
    """
    Server status enumeration.

    Attributes:
        STOPPED (ServerStatus): The server is not running.
        STARTING (ServerStatus): The server is in the process of starting.
        RUNNING (ServerStatus): The server is running and healthy.
        UNHEALTHY (ServerStatus): The server is running but failed health checks.
        FAILED (ServerStatus): The server failed to start or encountered a fatal error.
    """

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    UNHEALTHY = "unhealthy"
    FAILED = "failed"


@dataclass
class ServerInfo:
    """
    Information about an MCP server.

    Attributes:
        name (str): The name of the server.
        package (str): The Python package that the server comes from.
        module_path (str): The full Python module path for the server.
        log_file (Optional[Path]): Path to the server's log file.
        env_vars (Optional[Dict[str, Any]]): Environment variables for the server process.
        status (ServerStatus): Current status of the server.
        url (Optional[str]): Optional URL for accessing the server.
        pid (Optional[int]): Process ID of the running server, if available.
        host (str): Hostname or IP address where the server is running.
        port (Optional[int]): Network port for the server, if applicable.
        started_at (Optional[str]): ISO timestamp when the server was started.
        last_checked (Optional[str]): ISO timestamp when the server status was last checked.

    Methods:
        to_dict:
            Serialize the ServerInfo instance to a dictionary suitable for JSON.
        from_dict:
            Deserialize a dictionary into a ServerInfo instance.
    """

    name: str
    package: str
    module_path: str
    log_file: Optional[Path] = None
    env_vars: Optional[Dict[str, Any]] = None
    status: ServerStatus = ServerStatus.STOPPED
    url: Optional[str] = None
    pid: Optional[int] = None
    host: str = "localhost"
    port: Optional[int] = None
    started_at: Optional[str] = None
    last_checked: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dict for JSON serialization.

        Returns:

        """
        d = asdict(self)
        # Convert Path to string
        if self.log_file:
            d["log_file"] = str(self.log_file)
        # Convert Enum to value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ServerInfo":
        """
        Create ServerInfo from dict.

        Returns:

        """
        # Convert status string back to Enum
        if "status" in data:
            data["status"] = ServerStatus(data["status"])
        # Convert log_file string back to Path
        if data.get("log_file"):
            data["log_file"] = Path(data["log_file"])
        return cls(**data)
