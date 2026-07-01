# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Tests for the `registry.py` module."""

import types

from _pytest.logging import LogCaptureFixture
from _pytest.monkeypatch import MonkeyPatch

from mada_tools.extensions.manifest import ExtensionManifest, MCPServerRegistration
from mada_tools.extensions.registry import ExtensionRegistry


class FakeEntryPoint:
    def __init__(self, name, value, loaded=None, dist_name=None):
        self.name = name
        self.value = value
        self._loaded = loaded
        self.dist = types.SimpleNamespace(name=dist_name) if dist_name is not None else None

    def load(self):
        if isinstance(self._loaded, Exception):
            raise self._loaded
        return self._loaded


class FakeSelectableEntryPoints(list):
    def __init__(self, group, items):
        super().__init__(items)
        self.group = group

    def select(self, group=None):
        if group == self.group:
            return self
        return []


def make_manifest(provider_package: str, *servers: MCPServerRegistration) -> ExtensionManifest:
    return ExtensionManifest(
        display_name=f"{provider_package} display",
        version="1.0.0",
        provider_package=provider_package,
        mcp_servers=servers,
    )


def test_get_available_mcp_servers_returns_sorted_registrations(monkeypatch: MonkeyPatch):
    """Verify that available MCP server registrations are returned in package/name order."""
    registry = ExtensionRegistry()
    monkeypatch.setattr(
        registry,
        "discover_extensions",
        lambda: [
            make_manifest(
                "pkg_b",
                MCPServerRegistration("zeta", "pkg_b.zeta.server", "pkg_b"),
            ),
            make_manifest(
                "pkg_a",
                MCPServerRegistration("beta", "pkg_a.beta.server", "pkg_a"),
                MCPServerRegistration("alpha", "pkg_a.alpha.server", "pkg_a"),
            ),
        ],
    )

    discovered = registry.get_available_mcp_servers()

    assert [(server.package, server.name) for server in discovered] == [
        ("pkg_a", "alpha"),
        ("pkg_a", "beta"),
        ("pkg_b", "zeta"),
    ]


def test_get_mcp_server_index_keeps_first_server_on_name_collision(monkeypatch: MonkeyPatch, caplog: LogCaptureFixture):
    """Verify that name collisions keep the first discovered registration and log a warning."""
    registry = ExtensionRegistry()
    first = MCPServerRegistration("shared", "first_pkg.shared.server", "first_pkg")
    second = MCPServerRegistration("shared", "second_pkg.shared.server", "second_pkg")
    monkeypatch.setattr(
        registry,
        "discover_extensions",
        lambda: [make_manifest("first_pkg", first), make_manifest("second_pkg", second)],
    )

    with caplog.at_level("WARNING"):
        discovered = registry.get_mcp_server_index()

    assert discovered == {"shared": first}
    assert any("Plugin server name collision for 'shared'" in record.message for record in caplog.records)


def test_discover_manifest_extensions_discovers_valid_manifest(monkeypatch: MonkeyPatch):
    """Verify that valid manifest entry points are discovered successfully."""
    registry = ExtensionRegistry()
    manifest = make_manifest(
        "provider_pkg",
        MCPServerRegistration("slurm", "provider_pkg.scheduler.slurm.server", "provider_pkg"),
    )
    entry_points = [FakeEntryPoint("provider_pkg", "provider_pkg.extension:get_extension_manifest", lambda: manifest)]
    monkeypatch.setattr(
        registry,
        "_load_entry_points",
        lambda group: entry_points if group == "mada_tools.extensions" else [],
    )
    monkeypatch.setattr(
        "mada_tools.extensions.registry.importlib.import_module",
        lambda module_path: types.SimpleNamespace(main=lambda: None),
    )

    discovered = registry._discover_manifest_extensions()

    assert discovered == [manifest]


def test_discover_manifest_extensions_skips_duplicate_provider_packages(
    monkeypatch: MonkeyPatch, caplog: LogCaptureFixture
):
    """Verify that later manifest registrations from the same provider package are skipped."""
    registry = ExtensionRegistry()
    first = make_manifest("provider_pkg", MCPServerRegistration("alpha", "provider.alpha.server", "provider_pkg"))
    second = make_manifest("provider_pkg", MCPServerRegistration("beta", "provider.beta.server", "provider_pkg"))
    entry_points = [
        FakeEntryPoint("first", "provider.extension:first", lambda: first),
        FakeEntryPoint("second", "provider.extension:second", lambda: second),
    ]
    monkeypatch.setattr(
        registry,
        "_load_entry_points",
        lambda group: entry_points if group == "mada_tools.extensions" else [],
    )
    monkeypatch.setattr(
        "mada_tools.extensions.registry.importlib.import_module",
        lambda module_path: types.SimpleNamespace(main=lambda: None),
    )

    with caplog.at_level("WARNING"):
        discovered = registry._discover_manifest_extensions()

    assert discovered == [first]
    assert any("Duplicate extension package 'provider_pkg' discovered" in record.message for record in caplog.records)


def test_call_manifest_factory_rejects_non_callable_loaded_object(caplog: LogCaptureFixture):
    """Verify that non-callable loaded entry point objects are rejected."""
    registry = ExtensionRegistry()

    with caplog.at_level("WARNING"):
        manifest = registry._call_manifest_factory("broken", object())

    assert manifest is None
    assert any("did not load a callable factory" in record.message for record in caplog.records)


def test_call_manifest_factory_rejects_wrong_type(caplog: LogCaptureFixture):
    """Verify that manifest factories returning the wrong type are rejected."""
    registry = ExtensionRegistry()

    with caplog.at_level("WARNING"):
        manifest = registry._call_manifest_factory("broken", lambda: {"not": "a manifest"})

    assert manifest is None
    assert any("returned dict instead of ExtensionManifest" in record.message for record in caplog.records)


def test_validate_extension_manifest_rejects_empty_provider_package(caplog: LogCaptureFixture):
    """Verify that manifests without a provider package are rejected."""
    registry = ExtensionRegistry()
    manifest = make_manifest("", MCPServerRegistration("alpha", "provider.alpha.server", "provider"))

    with caplog.at_level("WARNING"):
        is_valid = registry._validate_extension_manifest(manifest)

    assert not is_valid
    assert any("empty provider_package" in record.message for record in caplog.records)


def test_validate_extension_manifest_rejects_duplicate_server_names(
    caplog: LogCaptureFixture, monkeypatch: MonkeyPatch
):
    """Verify that duplicate server names within one manifest are rejected."""
    registry = ExtensionRegistry()
    monkeypatch.setattr(
        "mada_tools.extensions.registry.importlib.import_module",
        lambda module_path: types.SimpleNamespace(main=lambda: None),
    )
    manifest = make_manifest(
        "provider_pkg",
        MCPServerRegistration("dup", "provider.alpha.server", "provider_pkg"),
        MCPServerRegistration("dup", "provider.beta.server", "provider_pkg"),
    )

    with caplog.at_level("WARNING"):
        is_valid = registry._validate_extension_manifest(manifest)

    assert not is_valid
    assert any("registers duplicate MCP server name 'dup'" in record.message for record in caplog.records)


def test_validate_mcp_server_registration_rejects_module_without_main(
    monkeypatch: MonkeyPatch, caplog: LogCaptureFixture
):
    """Verify that server modules without callable `main()` are rejected."""
    registry = ExtensionRegistry()
    monkeypatch.setattr("mada_tools.extensions.registry.importlib.import_module", lambda module_path: object())

    with caplog.at_level("WARNING"):
        is_valid = registry._validate_mcp_server_registration(
            MCPServerRegistration("alpha", "provider.alpha.server", "provider_pkg")
        )

    assert not is_valid
    assert any("does not expose callable main()" in record.message for record in caplog.records)


def test_discover_legacy_server_extensions_groups_by_provider_and_skips_manifest_provider(monkeypatch: MonkeyPatch):
    """Verify that legacy servers are grouped by provider and skipped when a manifest exists."""
    registry = ExtensionRegistry()
    entry_points = [
        FakeEntryPoint("legacy_a", "pkg_a.alpha.server", dist_name="pkg_a"),
        FakeEntryPoint("legacy_b", "pkg_b.beta.server", dist_name="pkg_b"),
    ]
    monkeypatch.setattr(
        registry,
        "_load_entry_points",
        lambda group: entry_points if group == "mada_tools.servers" else [],
    )
    monkeypatch.setattr(
        "mada_tools.extensions.registry.importlib.import_module",
        lambda module_path: types.SimpleNamespace(main=lambda: None),
    )

    discovered = registry._discover_legacy_server_extensions(existing_provider_packages={"pkg_a"})

    assert len(discovered) == 1
    assert discovered[0].provider_package == "pkg_b"
    assert [server.name for server in discovered[0].mcp_servers] == ["legacy_b"]


def test_discover_legacy_server_extensions_uses_unknown_when_dist_name_missing(monkeypatch: MonkeyPatch):
    """Verify that legacy entry points without distribution metadata use `unknown`."""
    registry = ExtensionRegistry()
    entry_points = [FakeEntryPoint("legacy", "pkg.alpha.server")]
    monkeypatch.setattr(
        registry,
        "_load_entry_points",
        lambda group: entry_points if group == "mada_tools.servers" else [],
    )
    monkeypatch.setattr(
        "mada_tools.extensions.registry.importlib.import_module",
        lambda module_path: types.SimpleNamespace(main=lambda: None),
    )

    discovered = registry._discover_legacy_server_extensions(existing_provider_packages=set())

    assert len(discovered) == 1
    assert discovered[0].provider_package == "unknown"
    assert discovered[0].mcp_servers[0].package == "unknown"


def test_load_entry_points_supports_legacy_get_api(monkeypatch: MonkeyPatch):
    """Verify that legacy `entry_points().get(...)` results are supported."""
    registry = ExtensionRegistry()

    class LegacyEntryPoints(dict):
        pass

    legacy = LegacyEntryPoints(
        {
            "mada_tools.extensions": [FakeEntryPoint("provider", "provider.extension:factory")],
        }
    )
    monkeypatch.setattr("importlib.metadata.entry_points", lambda: legacy)

    discovered = registry._load_entry_points("mada_tools.extensions")

    assert len(discovered) == 1
    assert discovered[0].name == "provider"


def test_load_entry_points_returns_empty_on_failure(monkeypatch: MonkeyPatch, caplog: LogCaptureFixture):
    """Verify that entry-point loading failures produce an empty result and a warning."""
    registry = ExtensionRegistry()

    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr("importlib.metadata.entry_points", boom)

    with caplog.at_level("WARNING"):
        discovered = registry._load_entry_points("mada_tools.extensions")

    assert discovered == []
    assert any(
        "Failed to read entry points for 'mada_tools.extensions': boom" in record.message for record in caplog.records
    )
