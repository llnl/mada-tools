# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
End-to-end tests for the mada-tools CLI restart-servers flow.

These tests exercise the real CLI entrypoint through main(), including
argument parsing, command registration, command dispatch, restart
orchestration, and state persistence behavior.
"""

import json
import sys
from pathlib import Path
from typing import Callable

import pytest
from _pytest.monkeypatch import MonkeyPatch

from mada_tools.main import main
from mada_tools.server_management import ServerStatus


class DummyProcess:
    """
    Fake subprocess process object for restart end-to-end tests.
    """

    def __init__(self, pid=4321, poll_result=None):
        """
        Initialize the fake process.

        Args:
            pid: Fake process identifier.
            poll_result: Poll result, where None means still running.
        """
        self.pid = pid
        self._poll_result = poll_result

    def poll(self):
        """
        Return the configured poll result.

        Returns:
            The configured poll result.
        """
        return self._poll_result


class DummyPsutilProcess:
    """
    Fake psutil.Process implementation used to simulate shutdown behavior
    during restart end-to-end tests.
    """

    def __init__(self, pid, cmdline=None):
        """
        Initialize the fake process.

        Args:
            pid: Fake process identifier.
            cmdline: Optional fake command line.
        """
        self.pid = pid
        self._cmdline = cmdline or []
        self.terminated = False

    def cmdline(self):
        """
        Return the configured fake command line.

        Returns:
            list[str]: Fake command line.
        """
        return self._cmdline

    def terminate(self):
        """
        Simulate graceful termination.
        """
        self.terminated = True

    def wait(self, timeout=None):
        """
        Simulate successful process wait.

        Args:
            timeout: Optional timeout.
        """
        return 0

    def children(self, recursive=False):
        """
        Return no child processes.

        Args:
            recursive: Recursive flag.

        Returns:
            list: Empty child list.
        """
        return []

    def kill(self):
        """
        Simulate force kill.
        """
        return None


def test_main_restart_servers_restarts_all_configured_servers(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    config_file: Path,
    state_file: Path,
    register_server: Callable,
):
    """
    End-to-end test, verify the CLI restart-servers command stops and starts
    all configured servers when no specific server names are provided.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
        patch_cli_dependencies (None):
            Fixture that patches nonessential external boundaries.
        config_file (Path):
            Path to the generated JSON config file.
        state_file (Path):
            Path to a test-local state file.
        register_server (Callable):
            A fixture that registers servers in a real state file.
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
        "mada_tools.server_management.server_manager.ServerManager._discover_servers",
        lambda self: {
            "alpha": {
                "module_path": "fake_pkg.alpha.server",
                "package": "fake_pkg",
            },
            "beta": {
                "module_path": "fake_pkg.beta.server",
                "package": "fake_pkg",
            },
        },
    )

    process_map = {
        1001: DummyPsutilProcess(1001, ["python", "-m", "fake_pkg.alpha.server", "alpha"]),
        1002: DummyPsutilProcess(1002, ["python", "-m", "fake_pkg.beta.server", "beta"]),
    }

    launched = []
    next_pid = {"value": 2000}

    def fake_psutil_process(pid):
        return process_map[pid]

    def fake_popen(cmd, stdout, stderr, env, start_new_session):
        launched.append(cmd)
        next_pid["value"] += 1
        return DummyProcess(pid=next_pid["value"], poll_result=None)

    port_check_counts = {}

    def fake_is_port_in_use(self, host, port):
        count = port_check_counts.get(port, 0) + 1
        port_check_counts[port] = count
        return count >= 2

    monkeypatch.setattr(
        "mada_tools.server_management.server_manager.psutil.Process",
        fake_psutil_process,
    )
    monkeypatch.setattr(
        "mada_tools.server_management.state_manager.ServerStateManager._is_process_running",
        lambda self, pid: True,
    )
    monkeypatch.setattr(
        "mada_tools.server_management.state_manager.ServerStateManager._is_port_in_use",
        fake_is_port_in_use,
    )
    monkeypatch.setattr(
        "mada_tools.server_management.server_manager.subprocess.Popen",
        fake_popen,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "restart-servers",
            str(config_file),
            "--state-file",
            str(state_file),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)
    assert process_map[1001].terminated is True
    assert process_map[1002].terminated is True
    assert len(launched) == 2

    state = json.loads(state_file.read_text())
    assert set(state["servers"].keys()) == {"alpha", "beta"}
    assert state["servers"]["alpha"]["status"] == ServerStatus.RUNNING.value
    assert state["servers"]["beta"]["status"] == ServerStatus.RUNNING.value
    assert state["servers"]["alpha"]["pid"] != 1001
    assert state["servers"]["beta"]["pid"] != 1002


def test_main_restart_servers_only_restarts_requested_server(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    config_file: Path,
    state_file: Path,
    register_server: Callable,
):
    """
    End-to-end test, verify the CLI restart-servers command restarts only the
    explicitly requested server when multiple servers are configured.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
        patch_cli_dependencies (None):
            Fixture that patches nonessential external boundaries.
        config_file (Path):
            Path to the generated JSON config file.
        state_file (Path):
            Path to a test-local state file.
        register_server (Callable):
            A fixture that registers servers in a real state file.
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
        "mada_tools.server_management.server_manager.ServerManager._discover_servers",
        lambda self: {
            "alpha": {
                "module_path": "fake_pkg.alpha.server",
                "package": "fake_pkg",
            },
            "beta": {
                "module_path": "fake_pkg.beta.server",
                "package": "fake_pkg",
            },
        },
    )

    process_map = {
        1001: DummyPsutilProcess(1001, ["python", "-m", "fake_pkg.alpha.server", "alpha"]),
        1002: DummyPsutilProcess(1002, ["python", "-m", "fake_pkg.beta.server", "beta"]),
    }

    launched = []

    def fake_popen(cmd, stdout, stderr, env, start_new_session):
        launched.append(cmd)
        return DummyProcess(pid=3001, poll_result=None)

    port_check_counts = {}

    def fake_is_port_in_use(self, host, port):
        count = port_check_counts.get(port, 0) + 1
        port_check_counts[port] = count
        if port == 8011:
            return count >= 2
        return False

    monkeypatch.setattr(
        "mada_tools.server_management.server_manager.psutil.Process",
        lambda pid: process_map[pid],
    )
    monkeypatch.setattr(
        "mada_tools.server_management.state_manager.ServerStateManager._is_process_running",
        lambda self, pid: True,
    )
    monkeypatch.setattr(
        "mada_tools.server_management.state_manager.ServerStateManager._is_port_in_use",
        fake_is_port_in_use,
    )
    monkeypatch.setattr(
        "mada_tools.server_management.server_manager.subprocess.Popen",
        fake_popen,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "restart-servers",
            str(config_file),
            "--servers",
            "alpha",
            "--state-file",
            str(state_file),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)
    assert process_map[1001].terminated is True
    assert process_map[1002].terminated is False
    assert len(launched) == 1
    assert "fake_pkg.alpha.server" in launched[0]

    state = json.loads(state_file.read_text())
    assert set(state["servers"].keys()) == {"alpha", "beta"}
    assert state["servers"]["alpha"]["pid"] == 3001
    assert state["servers"]["beta"]["pid"] == 1002


def test_main_restart_servers_starts_fresh_when_server_is_not_already_running(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    config_file: Path,
    state_file: Path,
):
    """
    End-to-end test, verify the CLI restart-servers command starts a configured
    server even when it is not already present in the running state file.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
        patch_cli_dependencies (None):
            Fixture that patches nonessential external boundaries.
        config_file (Path):
            Path to the generated JSON config file.
        state_file (Path):
            Path to a test-local state file.
    """
    monkeypatch.setattr(
        "mada_tools.server_management.server_manager.ServerManager._discover_servers",
        lambda self: {
            "alpha": {
                "module_path": "fake_pkg.alpha.server",
                "package": "fake_pkg",
            }
        },
    )

    monkeypatch.setattr(
        "mada_tools.server_management.state_manager.ServerStateManager._is_process_running",
        lambda self, pid: False,
    )

    port_check_counts = {"count": 0}

    def fake_is_port_in_use(self, host, port):
        port_check_counts["count"] += 1
        return port_check_counts["count"] >= 2

    monkeypatch.setattr(
        "mada_tools.server_management.state_manager.ServerStateManager._is_port_in_use",
        fake_is_port_in_use,
    )
    monkeypatch.setattr(
        "mada_tools.server_management.server_manager.subprocess.Popen",
        lambda *args, **kwargs: DummyProcess(pid=4001, poll_result=None),
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "restart-servers",
            str(config_file),
            "--state-file",
            str(state_file),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)

    state = json.loads(state_file.read_text())
    assert set(state["servers"].keys()) == {"alpha"}
    assert state["servers"]["alpha"]["pid"] == 4001
    assert state["servers"]["alpha"]["status"] == ServerStatus.RUNNING.value


def test_main_restart_servers_exits_with_error_for_unknown_server_name(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    config_file: Path,
    state_file: Path,
):
    """
    End-to-end test, verify the CLI restart-servers command exits with status 1
    when the user requests a server name not present in the config.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
        patch_cli_dependencies (None):
            Fixture that patches nonessential external boundaries.
        config_file (Path):
            Path to the generated JSON config file.
        state_file (Path):
            Path to a test-local state file.
    """
    monkeypatch.setattr(
        "mada_tools.server_management.server_manager.ServerManager._discover_servers",
        lambda self: {
            "alpha": {
                "module_path": "fake_pkg.alpha.server",
                "package": "fake_pkg",
            },
            "beta": {
                "module_path": "fake_pkg.beta.server",
                "package": "fake_pkg",
            },
        },
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "restart-servers",
            str(config_file),
            "--servers",
            "charlie",
            "--state-file",
            str(state_file),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1


def test_main_restart_servers_exits_with_error_when_restarted_server_port_is_in_use(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    config_file: Path,
    state_file: Path,
    register_server: Callable,
):
    """
    End-to-end test, verify the CLI restart-servers command logs a restart
    failure but still exits successfully when a stopped server cannot be
    started again because its port is already in use.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
        patch_cli_dependencies (None):
            Fixture that patches nonessential external boundaries.
        config_file (Path):
            Path to the generated JSON config file.
        state_file (Path):
            Path to a test-local state file.
        register_server (Callable):
            A fixture that registers servers in a real state file.
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
        "mada_tools.server_management.server_manager.ServerManager._discover_servers",
        lambda self: {
            "alpha": {
                "module_path": "fake_pkg.alpha.server",
                "package": "fake_pkg",
            }
        },
    )

    fake_proc = DummyPsutilProcess(
        1001,
        ["python", "-m", "fake_pkg.alpha.server", "alpha"],
    )

    monkeypatch.setattr(
        "mada_tools.server_management.server_manager.psutil.Process",
        lambda pid: fake_proc,
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
            "restart-servers",
            str(config_file),
            "--servers",
            "alpha",
            "--state-file",
            str(state_file),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)
    assert fake_proc.terminated is True

    state = json.loads(state_file.read_text())
    assert state["servers"] == {}
