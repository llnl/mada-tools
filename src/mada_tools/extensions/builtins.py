# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Built-in extension manifest for MCP servers shipped with MADA.

This module exposes the manifest factory used by the core `mada_tools`
package to register its built-in MCP servers through the shared extension
discovery path.
"""

from importlib.metadata import PackageNotFoundError, version

from mada_tools.extensions.manifest import ExtensionManifest, MCPServerRegistration


def get_extension_manifest() -> ExtensionManifest:
    """Return the built-in MADA extension manifest.

    Returns:
        ExtensionManifest:
            Manifest describing MCP servers provided directly by `mada_tools`.
    """
    try:
        package_version = version("mada_tools")
    except PackageNotFoundError:
        package_version = "unknown"

    return ExtensionManifest(
        display_name="MADA Tools",
        version=package_version,
        provider_package="mada_tools",
        mcp_servers=(
            MCPServerRegistration(
                name="flux",
                module_path="mada_tools.scheduler.flux.server",
                package="mada_tools",
            ),
            MCPServerRegistration(
                name="slurm",
                module_path="mada_tools.scheduler.slurm.server",
                package="mada_tools",
            ),
            MCPServerRegistration(
                name="vertex_cfd",
                module_path="mada_tools.simulation.vertex_cfd.server",
                package="mada_tools",
            ),
            MCPServerRegistration(
                name="professor",
                module_path="mada_tools.surrogate.professor.server",
                package="mada_tools",
            ),
            MCPServerRegistration(
                name="job_monitor",
                module_path="mada_tools.monitor.job_monitor.server",
                package="mada_tools",
            ),
            MCPServerRegistration(
                name="maestro_command_executor",
                module_path="mada_tools.workflow.weave.maestro.server",
                package="mada_tools",
            ),
        ),
    )
