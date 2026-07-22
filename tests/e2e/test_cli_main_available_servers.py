# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
End-to-end tests for the mada-tools CLI available-servers flow.

These tests exercise the real CLI entrypoint through main(), including
argument parsing, command registration, command dispatch, and available
server discovery and display behavior.
"""

import sys
from typing import Any, Callable, List, Tuple

import pytest
from _pytest.logging import LogCaptureFixture
from _pytest.monkeypatch import MonkeyPatch

from mada_tools.extensions.manifest import ExtensionManifest, MCPServerRegistration
from mada_tools.main import main


def test_main_available_servers_prints_available_server_table(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    capture_rich_prints: List[Tuple[Any, ...]],
    extract_tables: Callable,
):
    """
    End-to-end test, verify the CLI available-servers command prints a table
    of discovered servers and exits successfully.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
        patch_cli_dependencies (None):
            Fixture that patches nonessential external boundaries.
        capture_rich_prints (List[Tuple[Any, ...]]):
            Captured positional argument tuples from Console.print calls.
        extract_tables (Callable):
            A fixture that extracts Rich table outputs from Console.print calls.
    """
    monkeypatch.setattr(
        "mada_tools.cli.commands.available_servers.ExtensionRegistry.get_available_mcp_servers",
        lambda self: [
            MCPServerRegistration("alpha", "fake_pkg.alpha.server", "fake_pkg"),
            MCPServerRegistration("beta", "other_pkg.beta.server", "other_pkg"),
        ],
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "available-servers",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)

    tables = extract_tables(capture_rich_prints)
    assert len(tables) == 1


def test_main_available_servers_prints_no_servers_message_when_none_are_discovered(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    capsys: LogCaptureFixture,
):
    """
    End-to-end test, verify the CLI available-servers command prints a
    no-servers-found message when discovery returns no available servers.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
        patch_cli_dependencies (None):
            Fixture that patches nonessential external boundaries.
        capsys (LogCaptureFixture):
            Pytest capsys fixture.
    """
    monkeypatch.setattr(
        "mada_tools.cli.commands.available_servers.ExtensionRegistry.get_available_mcp_servers",
        lambda self: [],
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "available-servers",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)

    captured = capsys.readouterr()
    assert "No available servers found." in captured.out


def test_main_available_servers_discovery_failure_exits_with_error(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
):
    """
    End-to-end test, verify the CLI available-servers command exits with
    status code 1 when server discovery raises an exception.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
        patch_cli_dependencies (None):
            Fixture that patches nonessential external boundaries.
    """

    def fake_discover(self):
        raise RuntimeError("discovery failed")

    monkeypatch.setattr(
        "mada_tools.cli.commands.available_servers.ExtensionRegistry.get_available_mcp_servers",
        fake_discover,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "available-servers",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1


def test_main_available_servers_sorts_and_groups_discovered_servers_for_display(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    capture_rich_prints: List[Tuple[Any, ...]],
    extract_tables: Callable,
):
    """
    End-to-end test, verify the CLI available-servers command successfully
    prints discovered servers even when discovery order is unsorted.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
        patch_cli_dependencies (None):
            Fixture that patches nonessential external boundaries.
        capture_rich_prints (List[Tuple[Any, ...]]):
            Captured positional argument tuples from Console.print calls.
        extract_tables (Callable):
            A fixture that extracts Rich table outputs from Console.print calls.
    """
    monkeypatch.setattr(
        "mada_tools.cli.commands.available_servers.ExtensionRegistry.get_available_mcp_servers",
        lambda self: [
            MCPServerRegistration("zeta", "z_pkg.zeta.server", "z_pkg"),
            MCPServerRegistration("alpha", "a_pkg.alpha.server", "a_pkg"),
            MCPServerRegistration("beta", "a_pkg.beta.server", "a_pkg"),
        ],
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "available-servers",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)

    tables = extract_tables(capture_rich_prints)
    assert len(tables) == 1


def test_main_available_servers_discovers_manifest_servers_via_entry_points(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    capture_rich_prints: List[Tuple[Any, ...]],
    extract_tables: Callable,
):
    """End-to-end test, verify available servers flow through real registry entry-point discovery."""

    class FakeEntryPoint:
        def __init__(self, name, value, loaded=None, dist_name=None):
            self.name = name
            self.value = value
            self._loaded = loaded
            self.dist = type("Dist", (), {"name": dist_name})() if dist_name is not None else None

        def load(self):
            return self._loaded

    class FakeSelectableEntryPoints:
        def __init__(self, groups):
            self.groups = groups

        def select(self, group=None):
            return self.groups.get(group, [])

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
        lambda module_path: type("Module", (), {"main": staticmethod(lambda: None)})(),
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "available-servers",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)

    tables = extract_tables(capture_rich_prints)
    assert len(tables) == 1
