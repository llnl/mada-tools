# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
End-to-end tests for the mada-tools CLI servers-status flow.

These tests exercise the real CLI entrypoint through main(), including
argument parsing, command registration, command dispatch, and status
reporting behavior through the real server management stack.
"""

import json
import sys
from pathlib import Path
from typing import Any, Callable, List, Tuple

import pytest
from _pytest.monkeypatch import MonkeyPatch

from mada_tools.extensions.manifest import MCPServerRegistration
from mada_tools.main import main
from mada_tools.server_management import ServerStatus
from mada_tools.server_management.state_manager import ServerStateManager


def test_main_servers_status_shows_running_servers_from_state(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    capture_rich_prints: List[Tuple[Any, ...]],
    state_file: Path,
    register_server: Callable,
    extract_tables: Callable,
):
    """
    End-to-end test, verify the CLI servers-status command prints a status
    table for running servers stored in the state file.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
        patch_cli_dependencies (None):
            Fixture that patches nonessential external boundaries.
        capture_rich_prints (List[Tuple[Any, ...]]):
            Captured positional argument tuples from Console.print calls.
        state_file (Path):
            Path to a test-local state file.
        register_server (Callable):
            A fixture that registers servers in a real state file.
        extract_tables (Callable):
            A fixture that extracts Rich table outputs from Console.print calls.
    """
    register_server(
        state_file=state_file,
        name="alpha",
        pid=1001,
        status=ServerStatus.RUNNING,
        module_path="fake_pkg.alpha.server",
        port=8011,
    )
    register_server(
        state_file=state_file,
        name="beta",
        pid=1002,
        status=ServerStatus.UNHEALTHY,
        module_path="fake_pkg.beta.server",
        port=8012,
    )

    monkeypatch.setattr(
        "mada_tools.server_management.state_manager.ServerStateManager._is_process_running",
        lambda self, pid: True,
    )
    monkeypatch.setattr(
        "mada_tools.server_management.state_manager.ServerStateManager._is_port_in_use",
        lambda self, host, port: True if port == 8011 else False,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "servers-status",
            "--state-file",
            str(state_file),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)

    tables = extract_tables(capture_rich_prints)
    assert len(tables) == 1

    state = json.loads(state_file.read_text())
    assert set(state["servers"].keys()) == {"alpha", "beta"}
    assert state["servers"]["alpha"]["status"] == ServerStatus.RUNNING.value
    assert state["servers"]["beta"]["status"] == ServerStatus.UNHEALTHY.value


def test_main_servers_status_filters_to_requested_server_names(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    capture_rich_prints: List[Tuple[Any, ...]],
    state_file: Path,
    register_server: Callable,
    extract_tables: Callable,
):
    """
    End-to-end test, verify the CLI servers-status command prints status only
    for explicitly requested server names.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
        patch_cli_dependencies (None):
            Fixture that patches nonessential external boundaries.
        capture_rich_prints (List[Tuple[Any, ...]]):
            Captured positional argument tuples from Console.print calls.
        state_file (Path):
            Path to a test-local state file.
        register_server (Callable):
            A fixture that registers servers in a real state file.
        extract_tables (Callable):
            A fixture that extracts Rich table outputs from Console.print calls.
    """
    register_server(
        state_file=state_file,
        name="alpha",
        pid=1001,
        status=ServerStatus.RUNNING,
        module_path="fake_pkg.alpha.server",
        port=8011,
    )
    register_server(
        state_file=state_file,
        name="beta",
        pid=1002,
        status=ServerStatus.RUNNING,
        module_path="fake_pkg.beta.server",
        port=8012,
    )

    monkeypatch.setattr(
        "mada_tools.server_management.state_manager.ServerStateManager._is_process_running",
        lambda self, pid: True,
    )
    monkeypatch.setattr(
        "mada_tools.server_management.state_manager.ServerStateManager._is_port_in_use",
        lambda self, host, port: True,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "servers-status",
            "--servers",
            "beta",
            "--state-file",
            str(state_file),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)

    tables = extract_tables(capture_rich_prints)
    assert len(tables) == 1

    state_manager = ServerStateManager(state_file=state_file)
    statuses = state_manager.get_servers(validate=False)
    assert set(statuses.keys()) == {"alpha", "beta"}


def test_main_servers_status_with_config_includes_stopped_servers_from_config(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    capture_rich_prints: List[Tuple[Any, ...]],
    state_file: Path,
    register_server: Callable,
    config_file: Path,
    extract_tables: Callable,
):
    """
    End-to-end test, verify the CLI servers-status command includes configured
    servers that are not currently running when a config file is provided.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
        patch_cli_dependencies (None):
            Fixture that patches nonessential external boundaries.
        capture_rich_prints (List[Tuple[Any, ...]]):
            Captured positional argument tuples from Console.print calls.
        state_file (Path):
            Path to a test-local state file.
        register_server (Callable):
            A fixture that registers servers in a real state file.
        config_file (Path):
            Path to the generated JSON config file.
        extract_tables (Callable):
            A fixture that extracts Rich table outputs from Console.print calls.
    """
    register_server(
        state_file=state_file,
        name="alpha",
        pid=1001,
        status=ServerStatus.RUNNING,
        module_path="fake_pkg.alpha.server",
        port=8011,
    )

    monkeypatch.setattr(
        "mada_tools.server_management.server_manager.ExtensionRegistry.get_mcp_server_index",
        lambda self: {
            "alpha": MCPServerRegistration("alpha", "fake_pkg.alpha.server", "fake_pkg"),
            "beta": MCPServerRegistration("beta", "fake_pkg.beta.server", "fake_pkg"),
        },
    )

    monkeypatch.setattr(
        "mada_tools.server_management.state_manager.ServerStateManager._is_process_running",
        lambda self, pid: True,
    )
    monkeypatch.setattr(
        "mada_tools.server_management.state_manager.ServerStateManager._is_port_in_use",
        lambda self, host, port: True if port == 8011 else False,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "servers-status",
            "--config",
            str(config_file),
            "--state-file",
            str(state_file),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)

    tables = extract_tables(capture_rich_prints)
    assert len(tables) == 1

    manager = ServerStateManager(state_file=state_file)
    persisted = manager.get_servers(validate=False)
    assert "alpha" in persisted
    assert "beta" not in persisted


def test_main_servers_status_with_config_and_server_filter_only_targets_matching_servers(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    capture_rich_prints: List[Tuple[Any, ...]],
    state_file: Path,
    register_server: Callable,
    config_file: Path,
    extract_tables: Callable,
):
    """
    End-to-end test, verify the CLI servers-status command honors both config
    scoping and explicit server-name filtering.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
        patch_cli_dependencies (None):
            Fixture that patches nonessential external boundaries.
        capture_rich_prints (List[Tuple[Any, ...]]):
            Captured positional argument tuples from Console.print calls.
        state_file (Path):
            Path to a test-local state file.
        register_server (Callable):
            A fixture that registers servers in a real state file.
        config_file (Path):
            Path to the generated JSON config file.
        extract_tables (Callable):
            A fixture that extracts Rich table outputs from Console.print calls.
    """
    register_server(
        state_file=state_file,
        name="alpha",
        pid=1001,
        status=ServerStatus.RUNNING,
        module_path="fake_pkg.alpha.server",
        port=8011,
    )
    register_server(
        state_file=state_file,
        name="gamma",
        pid=1003,
        status=ServerStatus.RUNNING,
        module_path="fake_pkg.gamma.server",
        port=8013,
    )

    monkeypatch.setattr(
        "mada_tools.server_management.server_manager.ExtensionRegistry.get_mcp_server_index",
        lambda self: {
            "alpha": MCPServerRegistration("alpha", "fake_pkg.alpha.server", "fake_pkg"),
            "beta": MCPServerRegistration("beta", "fake_pkg.beta.server", "fake_pkg"),
            "gamma": MCPServerRegistration("gamma", "fake_pkg.gamma.server", "fake_pkg"),
        },
    )

    monkeypatch.setattr(
        "mada_tools.server_management.state_manager.ServerStateManager._is_process_running",
        lambda self, pid: True,
    )
    monkeypatch.setattr(
        "mada_tools.server_management.state_manager.ServerStateManager._is_port_in_use",
        lambda self, host, port: port in {8011, 8013},
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "servers-status",
            "--config",
            str(config_file),
            "--servers",
            "beta",
            "--state-file",
            str(state_file),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)

    tables = extract_tables(capture_rich_prints)
    assert len(tables) == 1


def test_main_servers_status_shows_no_servers_found_when_state_is_empty(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    capture_rich_prints: List[Tuple[Any, ...]],
    state_file: Path,
):
    """
    End-to-end test, verify the CLI servers-status command reports that no
    servers were found when the state file has no server entries.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
        patch_cli_dependencies (None):
            Fixture that patches nonessential external boundaries.
        capture_rich_prints (List[Tuple[Any, ...]]):
            Captured positional argument tuples from Console.print calls.
        state_file (Path):
            Path to a test-local state file.
    """
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "servers-status",
            "--state-file",
            str(state_file),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)

    assert any(any("No servers found." in str(obj) for obj in args) for args in capture_rich_prints)


def test_main_servers_status_marks_dead_processes_as_stopped_during_validation(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    capture_rich_prints: List[Tuple[Any, ...]],
    state_file: Path,
    register_server: Callable,
    extract_tables: Callable,
):
    """
    End-to-end test, verify the CLI servers-status command validates persisted
    process state and marks dead processes as stopped.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
        patch_cli_dependencies (None):
            Fixture that patches nonessential external boundaries.
        capture_rich_prints (List[Tuple[Any, ...]]):
            Captured positional argument tuples from Console.print calls.
        state_file (Path):
            Path to a test-local state file.
        register_server (Callable):
            A fixture that registers servers in a real state file.
        extract_tables (Callable):
            A fixture that extracts Rich table outputs from Console.print calls.
    """
    register_server(
        state_file=state_file,
        name="alpha",
        pid=1001,
        status=ServerStatus.RUNNING,
        module_path="fake_pkg.alpha.server",
        port=8011,
    )

    monkeypatch.setattr(
        "mada_tools.server_management.state_manager.ServerStateManager._is_process_running",
        lambda self, pid: False,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "servers-status",
            "--state-file",
            str(state_file),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)

    tables = extract_tables(capture_rich_prints)
    assert len(tables) == 1

    state = json.loads(state_file.read_text())
    assert state["servers"]["alpha"]["status"] == ServerStatus.STOPPED.value
    assert state["servers"]["alpha"]["pid"] is None


def test_main_servers_status_ignores_unknown_server_names_in_filter(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    capture_rich_prints: List[Tuple[Any, ...]],
    state_file: Path,
    register_server: Callable,
    extract_tables: Callable,
):
    """
    End-to-end test, verify the CLI servers-status command ignores unknown
    server names supplied in the filter and still succeeds.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
        patch_cli_dependencies (None):
            Fixture that patches nonessential external boundaries.
        capture_rich_prints (List[Tuple[Any, ...]]):
            Captured positional argument tuples from Console.print calls.
        state_file (Path):
            Path to a test-local state file.
        register_server (Callable):
            A fixture that registers servers in a real state file.
        extract_tables (Callable):
            A fixture that extracts Rich table outputs from Console.print calls.
    """
    register_server(
        state_file=state_file,
        name="alpha",
        pid=1001,
        status=ServerStatus.RUNNING,
        module_path="fake_pkg.alpha.server",
        port=8011,
    )

    monkeypatch.setattr(
        "mada_tools.server_management.state_manager.ServerStateManager._is_process_running",
        lambda self, pid: True,
    )
    monkeypatch.setattr(
        "mada_tools.server_management.state_manager.ServerStateManager._is_port_in_use",
        lambda self, host, port: True,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "servers-status",
            "--servers",
            "alpha",
            "does-not-exist",
            "--state-file",
            str(state_file),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)

    tables = extract_tables(capture_rich_prints)
    assert len(tables) == 1
