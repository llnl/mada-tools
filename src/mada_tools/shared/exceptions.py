# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Common exceptions for MADA MCP servers."""


class MCPServerError(Exception):
    """Base exception for MCP server errors."""

    pass


class ToolExecutionError(MCPServerError):
    """Exception raised when a tool execution fails."""

    pass


class ConfigurationError(MCPServerError):
    """Exception raised when configuration is invalid."""

    pass


class BackendConnectionError(MCPServerError):
    """Exception raised when backend connection fails."""

    pass


class PortInUseError(MCPServerError):
    """Exception raised when a port is already in use."""

    pass


class TemplateContextError(ValueError):
    """Raised when jinja template context construction fails."""
