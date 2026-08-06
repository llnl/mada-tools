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

from importlib import import_module

__version__ = "0.1.1"

VERSION = __version__

_LAZY_IMPORTS = {
    "BaseMCPServer": ("mada_tools.shared.base_server", "BaseMCPServer"),
    "MCPServerError": ("mada_tools.shared.exceptions", "MCPServerError"),
    "ToolExecutionError": ("mada_tools.shared.exceptions", "ToolExecutionError"),
    "WEAVEStudyConstructionServer": ("mada_tools.workflow.weave", "WEAVEStudyConstructionServer"),
}


def __getattr__(name):
    """Lazily resolve legacy top-level exports.

    Importing a submodule such as ``mada_tools.docs`` executes this package
    initializer first. Keep the initializer free of dependency-heavy imports so
    lightweight APIs can be used without requiring optional MCP runtime
    dependencies such as FastMCP.
    """
    if name == "ServerManager":
        try:
            # ``server_management`` imports ``fcntl``, which is not available on
            # Windows. Preserve the previous Windows behavior while delaying the
            # import until callers explicitly request ``ServerManager``.
            value = import_module("mada_tools.server_management.server_manager").ServerManager
        except ModuleNotFoundError as exc:
            if exc.name != "fcntl":
                raise
            value = None
        globals()[name] = value
        return value

    if name in _LAZY_IMPORTS:
        # These exports preserve the historical top-level API without making
        # every ``mada_tools`` import load the MCP server dependency stack.
        module_name, attribute_name = _LAZY_IMPORTS[name]
        value = getattr(import_module(module_name), attribute_name)
        globals()[name] = value
        return value

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BaseMCPServer",
    "MCPServerError",
    "ServerManager",
    "ToolExecutionError",
    "WEAVEStudyConstructionServer",
]
