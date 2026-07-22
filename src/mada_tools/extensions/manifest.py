# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Definitions for extension manifests and MCP server registrations.

This module provides small immutable data containers used by extension
discovery and registration. These types describe one extension package and the
MCP servers that it contributes to MADA.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MCPServerRegistration:
    """Describe one MCP server contributed by an extension.

    Attributes:
        name (str):
            The server name used by MADA configuration and discovery output.
        module_path (str):
            Importable Python module path for the server implementation.
        package (str):
            Provider package name associated with the registration.
        description (str | None):
            Optional human-readable description of the server registration.
    """

    name: str
    module_path: str
    package: str
    description: str | None = None


@dataclass(frozen=True)
class ExtensionManifest:
    """Describe one installable MADA extension package.

    Attributes:
        display_name (str):
            Human-readable name for the extension package.
        version (str):
            Version string reported by the extension package.
        provider_package (str):
            Python package or distribution providing this extension.
        mcp_servers (tuple[MCPServerRegistration, ...]):
            MCP server registrations contributed by the extension.
    """

    display_name: str
    version: str
    provider_package: str
    mcp_servers: tuple[MCPServerRegistration, ...] = field(default_factory=tuple)
