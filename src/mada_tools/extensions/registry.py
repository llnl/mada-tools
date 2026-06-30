# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Discovery and validation for MADA extension manifests.

This module provides the `ExtensionRegistry`, which is responsible for loading
manifest factories, adapting legacy MCP server entry points, validating server
modules, and returning the final set of available MCP server registrations.
"""

import importlib
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from mada_tools.extensions.manifest import ExtensionManifest, MCPServerRegistration

LOG = logging.getLogger(__name__)


class ExtensionRegistry:
    """Discover extension manifests and expose validated MCP server registrations.

    Methods:
        discover_extensions:
            Return all manifest-based and legacy-adapted extensions.
        get_available_mcp_servers:
            Return validated MCP server registrations as a sorted list.
        get_mcp_server_index:
            Return validated MCP server registrations keyed by server name.
    """

    def discover_extensions(self) -> List[ExtensionManifest]:
        """Discover manifest-based and legacy extensions.

        Returns:
            List[ExtensionManifest]:
                Discovered extension manifests after manifest loading and legacy
                entry-point adaptation.
        """
        manifests = self._discover_manifest_extensions()
        manifests.extend(
            self._discover_legacy_server_extensions(
                existing_provider_packages={manifest.provider_package for manifest in manifests}
            )
        )
        return manifests

    def get_available_mcp_servers(self) -> List[MCPServerRegistration]:
        """Return validated MCP server registrations.

        Returns:
            List[MCPServerRegistration]:
                MCP server registrations sorted by provider package and server
                name.
        """
        return sorted(
            self.get_mcp_server_index().values(),
            key=lambda server: (server.package.lower(), server.name.lower()),
        )

    def get_mcp_server_index(self) -> Dict[str, MCPServerRegistration]:
        """Return validated MCP servers indexed by server name.

        Returns:
            Dict[str, MCPServerRegistration]:
                Mapping of server names to validated MCP server registrations.
        """
        available: Dict[str, MCPServerRegistration] = {}

        for manifest in self.discover_extensions():
            for server in manifest.mcp_servers:
                if server.name in available:
                    LOG.warning(
                        "Plugin server name collision for '%s', already discovered. Skipping server from package '%s'.",
                        server.name,
                        manifest.provider_package,
                    )
                    continue

                available[server.name] = server

        return available

    def _discover_manifest_extensions(self) -> List[ExtensionManifest]:
        """Discover extensions registered under the manifest entry point group.

        Returns:
            List[ExtensionManifest]:
                Valid manifest-based extensions discovered from the
                `mada_tools.extensions` entry point group.
        """
        manifests: List[ExtensionManifest] = []
        seen_provider_packages: set[str] = set()

        for entry_point in self._load_entry_points("mada_tools.extensions"):
            loaded = self._load_manifest_factory(entry_point)
            if loaded is None:
                continue

            manifest = self._call_manifest_factory(entry_point.name, loaded)
            if manifest is None:
                continue

            if not self._validate_extension_manifest(manifest):
                continue

            if manifest.provider_package in seen_provider_packages:
                LOG.warning(
                    "Duplicate extension package '%s' discovered. Skipping later registration from '%s'.",
                    manifest.provider_package,
                    entry_point.value,
                )
                continue

            seen_provider_packages.add(manifest.provider_package)
            manifests.append(manifest)

        return manifests

    def _discover_legacy_server_extensions(self, existing_provider_packages: set[str]) -> List[ExtensionManifest]:
        """Discover legacy server entry points and adapt them into manifests.

        Args:
            existing_provider_packages (set[str]):
                Provider packages already represented by manifest-based
                extensions. Legacy registrations from these packages are
                skipped.

        Returns:
            List[ExtensionManifest]:
                Synthetic manifests created from legacy
                `mada_tools.servers` entry points.
        """
        grouped_servers: dict[str, list[MCPServerRegistration]] = defaultdict(list)

        for entry_point in self._load_entry_points("mada_tools.servers"):
            module_path = entry_point.value.split(":")[0].strip()
            provider = getattr(entry_point, "dist", None)
            provider_name = getattr(provider, "name", None) or "unknown"

            # Prefer manifest-based registrations when a package exposes both APIs.
            if provider_name in existing_provider_packages:
                continue

            server = MCPServerRegistration(
                name=entry_point.name,
                module_path=module_path,
                package=provider_name,
            )

            if not self._validate_mcp_server_registration(server):
                continue

            grouped_servers[provider_name].append(server)

        manifests: List[ExtensionManifest] = []
        for provider_name, servers in grouped_servers.items():
            manifest = ExtensionManifest(
                display_name=f"Legacy MCP servers from {provider_name}",
                version="legacy",
                provider_package=provider_name,
                mcp_servers=tuple(servers),
            )

            if self._validate_extension_manifest(manifest):
                manifests.append(manifest)

        return manifests

    def _load_entry_points(self, group: str) -> list[Any]:
        """Load entry points for one group across modern and legacy APIs.

        Args:
            group (str):
                Entry point group name to load.

        Returns:
            list[Any]:
                Entry point objects returned by the active metadata API.
        """
        try:
            from importlib.metadata import entry_points
        except Exception:
            from importlib_metadata import entry_points  # type: ignore

        try:
            eps = entry_points()
            return list(eps.select(group=group) if hasattr(eps, "select") else eps.get(group, []))
        except Exception as e:
            LOG.warning("Failed to read entry points for '%s': %s", group, e)
            return []

    def _load_manifest_factory(self, entry_point: Any) -> Any | None:
        """Load one manifest factory from an entry point.

        Args:
            entry_point (Any):
                Entry point object to load.

        Returns:
            Any | None:
                Loaded factory object, or `None` if loading fails.
        """
        try:
            return entry_point.load()
        except Exception as e:
            LOG.warning("Failed to load extension entry point '%s': %s", entry_point.value, e)
            return None

    def _call_manifest_factory(self, entry_point_name: str, loaded: Any) -> Optional[ExtensionManifest]:
        """Call a loaded manifest factory and return its manifest.

        Args:
            entry_point_name (str):
                Name of the entry point being invoked.
            loaded (Any):
                Loaded factory object returned from the entry point.

        Returns:
            Optional[ExtensionManifest]:
                The produced manifest, or `None` if validation fails.
        """
        if not callable(loaded):
            LOG.warning("Extension entry point '%s' did not load a callable factory", entry_point_name)
            return None

        try:
            manifest = loaded()
        except Exception as e:
            LOG.warning("Extension manifest factory '%s' failed: %s", entry_point_name, e)
            return None

        if not isinstance(manifest, ExtensionManifest):
            LOG.warning(
                "Extension manifest factory '%s' returned %s instead of ExtensionManifest",
                entry_point_name,
                type(manifest).__name__,
            )
            return None

        return manifest

    def _validate_extension_manifest(self, manifest: ExtensionManifest) -> bool:
        """Validate one manifest and its registered MCP servers.

        Args:
            manifest (ExtensionManifest):
                Manifest to validate.

        Returns:
            bool:
                `True` when the manifest is structurally valid, otherwise
                `False`.
        """
        if not manifest.provider_package:
            LOG.warning("Encountered extension manifest with empty provider_package")
            return False

        if not manifest.display_name:
            LOG.warning("Extension '%s' is missing display_name", manifest.provider_package)
            return False

        seen_server_names: set[str] = set()
        for server in manifest.mcp_servers:
            if not self._validate_mcp_server_registration(server):
                return False

            if server.name in seen_server_names:
                LOG.warning(
                    "Extension '%s' registers duplicate MCP server name '%s'",
                    manifest.provider_package,
                    server.name,
                )
                return False

            seen_server_names.add(server.name)

        return True

    def _validate_mcp_server_registration(self, server: MCPServerRegistration) -> bool:
        """Validate one MCP server registration, including runtime importability.

        Args:
            server (MCPServerRegistration):
                Server registration to validate.

        Returns:
            bool:
                `True` when the registration is usable, otherwise `False`.
        """
        if not server.name:
            LOG.warning("Encountered MCP server registration with empty name")
            return False

        if not server.module_path:
            LOG.warning("MCP server '%s' is missing module_path", server.name)
            return False

        if not server.package:
            LOG.warning("MCP server '%s' is missing package", server.name)
            return False

        try:
            mod = importlib.import_module(server.module_path)
        except Exception as e:
            LOG.warning(
                "Could not import server module for '%s' from '%s': %s",
                server.name,
                server.module_path,
                e,
            )
            return False

        if not hasattr(mod, "main") or not callable(getattr(mod, "main")):
            LOG.warning(
                "Server module '%s' for '%s' does not expose callable main()",
                server.module_path,
                server.name,
            )
            return False

        return True
