# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Tests for the `builtins.py` module."""

from importlib.metadata import PackageNotFoundError

from _pytest.monkeypatch import MonkeyPatch

from mada_tools.extensions.builtins import get_extension_manifest
from mada_tools.extensions.manifest import ExtensionManifest


def test_get_extension_manifest_returns_extension_manifest():
    """Verify that `get_extension_manifest()` returns an `ExtensionManifest`."""
    manifest = get_extension_manifest()

    assert isinstance(manifest, ExtensionManifest)


def test_get_extension_manifest_has_expected_provider_package():
    """Verify that the built-in manifest reports the `mada_tools` provider package."""
    manifest = get_extension_manifest()

    assert manifest.provider_package == "mada_tools"


def test_get_extension_manifest_contains_expected_server_names():
    """Verify that the built-in manifest registers the expected MCP server names."""
    manifest = get_extension_manifest()

    assert {server.name for server in manifest.mcp_servers} == {
        "flux",
        "slurm",
        "vertex_cfd",
        "professor",
        "job_monitor",
        "maestro_command_executor",
    }


def test_get_extension_manifest_contains_expected_module_paths():
    """Verify that built-in server registrations point at the expected server modules."""
    manifest = get_extension_manifest()

    assert {server.module_path for server in manifest.mcp_servers} == {
        "mada_tools.scheduler.flux.server",
        "mada_tools.scheduler.slurm.server",
        "mada_tools.simulation.vertex_cfd.server",
        "mada_tools.surrogate.professor.server",
        "mada_tools.monitor.job_monitor.server",
        "mada_tools.workflow.weave.maestro.server",
    }


def test_get_extension_manifest_uses_unknown_when_version_lookup_fails(monkeypatch: MonkeyPatch):
    """Verify that version lookup falls back to `unknown` when package metadata is unavailable."""

    def raise_package_not_found(_):
        raise PackageNotFoundError()

    monkeypatch.setattr("mada_tools.extensions.builtins.version", raise_package_not_found)

    manifest = get_extension_manifest()

    assert manifest.version == "unknown"
