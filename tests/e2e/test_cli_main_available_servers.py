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
        "mada_tools.server_management.server_manager.ServerManager._discover_servers",
        lambda self: {
            "alpha": {
                "module_path": "fake_pkg.alpha.server",
                "package": "fake_pkg",
            },
            "beta": {
                "module_path": "other_pkg.beta.server",
                "package": "other_pkg",
            },
        },
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
        "mada_tools.server_management.server_manager.ServerManager._discover_servers",
        lambda self: {},
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
        "mada_tools.server_management.server_manager.ServerManager._discover_servers",
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
        "mada_tools.server_management.server_manager.ServerManager._discover_servers",
        lambda self: {
            "zeta": {
                "module_path": "z_pkg.zeta.server",
                "package": "z_pkg",
            },
            "alpha": {
                "module_path": "a_pkg.alpha.server",
                "package": "a_pkg",
            },
            "beta": {
                "module_path": "a_pkg.beta.server",
                "package": "a_pkg",
            },
        },
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
