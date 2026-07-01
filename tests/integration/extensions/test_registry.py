# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Integration tests for the `extensions.registry` module."""

import types

from _pytest.monkeypatch import MonkeyPatch

from mada_tools.extensions.manifest import ExtensionManifest, MCPServerRegistration
from mada_tools.extensions.registry import ExtensionRegistry


class FakeEntryPoint:
    """Minimal fake entry point for integration-level registry tests."""

    def __init__(self, name, value, loaded=None, dist_name=None):
        """Initialize the fake entry point.

        Args:
            name: Entry point name.
            value: Entry point value string.
            loaded: Object returned by `load()`.
            dist_name: Optional distribution name.
        """
        self.name = name
        self.value = value
        self._loaded = loaded
        self.dist = types.SimpleNamespace(name=dist_name) if dist_name is not None else None

    def load(self):
        """Return the configured loaded object."""
        return self._loaded


class FakeSelectableEntryPoints:
    """Fake entry-point container supporting the modern `.select()` API."""

    def __init__(self, groups):
        """Initialize the fake entry-point container.

        Args:
            groups: Mapping of entry-point group names to entry-point lists.
        """
        self.groups = groups

    def select(self, group=None):
        """Return entry points for the requested group.

        Args:
            group: Entry-point group name.

        Returns:
            list: Entry points for the requested group.
        """
        return self.groups.get(group, [])


def test_registry_discovers_manifest_extensions_from_entry_points(monkeypatch: MonkeyPatch):
    """Verify that manifest entry points flow through real registry discovery methods."""

    def get_extension_manifest() -> ExtensionManifest:
        return ExtensionManifest(
            display_name="Example Extension",
            version="1.0.0",
            provider_package="example_pkg",
            mcp_servers=(
                MCPServerRegistration("alpha", "example_pkg.alpha.server", "example_pkg"),
                MCPServerRegistration("beta", "example_pkg.beta.server", "example_pkg"),
            ),
        )

    fake_entry_points = FakeSelectableEntryPoints(
        {
            "mada_tools.extensions": [
                FakeEntryPoint(
                    "example_pkg",
                    "example_pkg.extension:get_extension_manifest",
                    loaded=get_extension_manifest,
                    dist_name="example_pkg",
                )
            ]
        }
    )

    monkeypatch.setattr("importlib.metadata.entry_points", lambda: fake_entry_points)
    monkeypatch.setattr(
        "mada_tools.extensions.registry.importlib.import_module",
        lambda module_path: types.SimpleNamespace(main=lambda: None),
    )

    registry = ExtensionRegistry()

    discovered = registry.discover_extensions()
    available = registry.get_available_mcp_servers()
    indexed = registry.get_mcp_server_index()

    assert len(discovered) == 1
    assert discovered[0].provider_package == "example_pkg"
    assert [server.name for server in available] == ["alpha", "beta"]
    assert indexed["alpha"].module_path == "example_pkg.alpha.server"
    assert indexed["beta"].package == "example_pkg"


def test_registry_adapts_legacy_server_entry_points(monkeypatch: MonkeyPatch):
    """Verify that legacy server entry points are adapted into extension manifests."""

    fake_entry_points = FakeSelectableEntryPoints(
        {
            "mada_tools.servers": [
                FakeEntryPoint("alpha", "legacy_pkg.alpha.server", dist_name="legacy_pkg"),
                FakeEntryPoint("beta", "legacy_pkg.beta.server", dist_name="legacy_pkg"),
            ]
        }
    )

    monkeypatch.setattr("importlib.metadata.entry_points", lambda: fake_entry_points)
    monkeypatch.setattr(
        "mada_tools.extensions.registry.importlib.import_module",
        lambda module_path: types.SimpleNamespace(main=lambda: None),
    )

    registry = ExtensionRegistry()

    discovered = registry.discover_extensions()
    indexed = registry.get_mcp_server_index()

    assert len(discovered) == 1
    assert discovered[0].provider_package == "legacy_pkg"
    assert [server.name for server in discovered[0].mcp_servers] == ["alpha", "beta"]
    assert indexed["alpha"].module_path == "legacy_pkg.alpha.server"
    assert indexed["beta"].module_path == "legacy_pkg.beta.server"


def test_registry_prefers_manifest_extensions_over_legacy_from_same_provider(monkeypatch: MonkeyPatch):
    """Verify that manifest registrations win when a provider exposes both extension APIs."""

    def get_extension_manifest() -> ExtensionManifest:
        return ExtensionManifest(
            display_name="Dual Extension",
            version="2.0.0",
            provider_package="dual_pkg",
            mcp_servers=(MCPServerRegistration("alpha", "dual_pkg.alpha.server", "dual_pkg"),),
        )

    fake_entry_points = FakeSelectableEntryPoints(
        {
            "mada_tools.extensions": [
                FakeEntryPoint(
                    "dual_pkg",
                    "dual_pkg.extension:get_extension_manifest",
                    loaded=get_extension_manifest,
                    dist_name="dual_pkg",
                )
            ],
            "mada_tools.servers": [
                FakeEntryPoint("legacy_alpha", "dual_pkg.legacy_alpha.server", dist_name="dual_pkg"),
            ],
        }
    )

    monkeypatch.setattr("importlib.metadata.entry_points", lambda: fake_entry_points)
    monkeypatch.setattr(
        "mada_tools.extensions.registry.importlib.import_module",
        lambda module_path: types.SimpleNamespace(main=lambda: None),
    )

    registry = ExtensionRegistry()

    discovered = registry.discover_extensions()
    indexed = registry.get_mcp_server_index()

    assert len(discovered) == 1
    assert discovered[0].provider_package == "dual_pkg"
    assert set(indexed.keys()) == {"alpha"}
    assert indexed["alpha"].module_path == "dual_pkg.alpha.server"
