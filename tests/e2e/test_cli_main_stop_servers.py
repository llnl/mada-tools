# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
End-to-end tests for the mada-tools CLI stop-servers flow.

These tests exercise the real CLI entrypoint through main(), including
argument parsing, command registration, command dispatch, and server
state persistence while stopping servers.
"""

import json
import sys
from pathlib import Path
from typing import Callable

import psutil
import pytest
from _pytest.monkeypatch import MonkeyPatch

from mada_tools.main import main
from mada_tools.server_management import ServerStatus


class DummyPsutilProcess:
    """
    Fake psutil.Process implementation used to simulate server shutdown
    behavior in CLI end-to-end tests.
    """

    def __init__(self, pid, cmdline=None, wait_plan=None, children_list=None):
        """
        Initialize the fake process.

        Args:
            pid: Fake process identifier.
            cmdline: Optional fake command line.
            wait_plan: Optional list of wait outcomes. Exception instances
                are raised, other values are returned.
            children_list: Optional list of fake child processes.
        """
        self.pid = pid
        self._cmdline = cmdline or []
        self._wait_plan = list(wait_plan or [0])
        self._children = children_list or []
        self.terminated = False
        self.killed = False

    def cmdline(self):
        """
        Return the configured fake command line.

        Returns:
            list[str]: Fake command line arguments.
        """
        return self._cmdline

    def terminate(self):
        """
        Simulate graceful termination.
        """
        self.terminated = True

    def wait(self, timeout=None):
        """
        Simulate waiting for process shutdown.

        Args:
            timeout: Optional timeout value.

        Raises:
            Exception: Configured exception if provided.
        """
        if self._wait_plan:
            result = self._wait_plan.pop(0)
        else:
            result = 0

        if isinstance(result, Exception):
            raise result
        return result

    def children(self, recursive=False):
        """
        Return child processes.

        Args:
            recursive: Whether children should be returned recursively.

        Returns:
            list: Fake child process list.
        """
        return self._children

    def kill(self):
        """
        Simulate force kill.
        """
        self.killed = True

    def is_running(self):
        """
        Simulate check for running process.

        Returns:
            bool: True if not terminated. False otherwise.
        """
        return not self.terminated


class DummyChildProcess:
    """
    Fake child process used during force-kill shutdown scenarios.
    """

    def __init__(self, pid):
        """
        Initialize the fake child process.

        Args:
            pid: Fake child PID.
        """
        self.pid = pid
        self.killed = False

    def kill(self):
        """
        Simulate killing the child process.
        """
        self.killed = True


def test_main_stop_servers_stops_all_running_servers_when_no_names_are_provided(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    state_file: Path,
    register_server: Callable,
):
    """
    End-to-end test, verify the CLI stop-servers command stops all running
    servers in the state file when no specific server names are provided.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
        patch_cli_dependencies (None):
            Fixture that patches nonessential external boundaries.
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
    )
    register_server(
        state_file=state_file,
        name="beta",
        pid=1002,
        status=ServerStatus.RUNNING,
        module_path="fake_pkg.beta.server",
    )

    processes = {
        1001: DummyPsutilProcess(1001, cmdline=["python", "-m", "fake_pkg.alpha.server", "alpha"]),
        1002: DummyPsutilProcess(1002, cmdline=["python", "-m", "fake_pkg.beta.server", "beta"]),
    }

    monkeypatch.setattr(
        "mada_tools.server_management.server_manager.psutil.Process",
        lambda pid: processes[pid],
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "stop-servers",
            "--state-file",
            str(state_file),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)
    assert processes[1001].terminated is True
    assert processes[1002].terminated is True

    state = json.loads(state_file.read_text())
    assert state["servers"] == {}


def test_main_stop_servers_only_stops_requested_server(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    state_file: Path,
    register_server: Callable,
):
    """
    End-to-end test, verify the CLI stop-servers command stops only the
    requested server and leaves other running servers in state.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
        patch_cli_dependencies (None):
            Fixture that patches nonessential external boundaries.
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
    )
    register_server(
        state_file=state_file,
        name="beta",
        pid=1002,
        status=ServerStatus.RUNNING,
        module_path="fake_pkg.beta.server",
    )

    processes = {
        1001: DummyPsutilProcess(1001, cmdline=["python", "-m", "fake_pkg.alpha.server", "alpha"]),
        1002: DummyPsutilProcess(1002, cmdline=["python", "-m", "fake_pkg.beta.server", "beta"]),
    }

    monkeypatch.setattr(
        "mada_tools.server_management.server_manager.psutil.Process",
        lambda pid: processes[pid],
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "stop-servers",
            "--servers",
            "alpha",
            "--state-file",
            str(state_file),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)
    assert processes[1001].terminated is True
    assert processes[1002].terminated is False

    state = json.loads(state_file.read_text())
    assert set(state["servers"].keys()) == {"beta"}


def test_main_stop_servers_with_config_only_stops_servers_defined_in_config(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    state_file: Path,
    config_file: Path,
    register_server: Callable,
):
    """
    End-to-end test, verify the CLI stop-servers command restricts stopping
    to servers defined in the provided config file.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
        patch_cli_dependencies (None):
            Fixture that patches nonessential external boundaries.
        state_file (Path):
            Path to a test-local state file.
        config_file (Path):
            Path to the generated JSON config file.
        register_server (Callable):
            A fixture that registers servers in a real state file.
    """
    register_server(
        state_file=state_file,
        name="alpha",
        pid=1001,
        status=ServerStatus.RUNNING,
        module_path="fake_pkg.alpha.server",
    )
    register_server(
        state_file=state_file,
        name="charlie",  # Using charlie instead of beta since beta already exists in `config_file`
        pid=1003,
        status=ServerStatus.RUNNING,
        module_path="fake_pkg.charlie.server",
    )

    monkeypatch.setattr(
        "mada_tools.server_management.server_manager.ServerManager._discover_servers",
        lambda self: {
            "alpha": {
                "module_path": "fake_pkg.alpha.server",
                "package": "fake_pkg",
            },
            "charlie": {
                "module_path": "fake_pkg.charlie.server",
                "package": "fake_pkg",
            },
        },
    )

    processes = {
        1001: DummyPsutilProcess(1001, cmdline=["python", "-m", "fake_pkg.alpha.server", "alpha"]),
        1003: DummyPsutilProcess(1003, cmdline=["python", "-m", "fake_pkg.charlie.server", "charlie"]),
    }

    monkeypatch.setattr(
        "mada_tools.server_management.server_manager.psutil.Process",
        lambda pid: processes[pid],
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "stop-servers",
            "--config",
            str(config_file),
            "--state-file",
            str(state_file),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)
    assert processes[1001].terminated is True
    assert processes[1003].terminated is False

    state = json.loads(state_file.read_text())
    assert set(state["servers"].keys()) == {"charlie"}


def test_main_stop_servers_gracefully_handles_server_that_is_already_gone(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    state_file: Path,
    register_server: Callable,
):
    """
    End-to-end test, verify the CLI stop-servers command succeeds when a
    recorded server process no longer exists and cleans up stale state.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
        patch_cli_dependencies (None):
            Fixture that patches nonessential external boundaries.
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
    )

    monkeypatch.setattr(
        "mada_tools.server_management.state_manager.ServerStateManager._is_process_running",
        lambda self, pid: True,
    )

    def fake_process(pid):
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(
        "mada_tools.server_management.server_manager.psutil.Process",
        fake_process,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "stop-servers",
            "--state-file",
            str(state_file),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)

    state = json.loads(state_file.read_text())
    assert state["servers"] == {}


def test_main_stop_servers_force_kills_process_after_timeout(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    state_file: Path,
    register_server: Callable,
):
    """
    End-to-end test, verify the CLI stop-servers command force kills a server
    after graceful shutdown times out and removes it from state.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
        patch_cli_dependencies (None):
            Fixture that patches nonessential external boundaries.
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
    )

    monkeypatch.setattr(
        "mada_tools.server_management.state_manager.ServerStateManager._is_process_running",
        lambda self, pid: True,
    )

    child1 = DummyChildProcess(2001)
    child2 = DummyChildProcess(2002)

    fake_parent = DummyPsutilProcess(
        1001,
        cmdline=["python", "-m", "fake_pkg.alpha.server", "alpha"],
        wait_plan=[
            psutil.TimeoutExpired(seconds=10, pid=1001),
            0,
        ],
        children_list=[child1, child2],
    )

    monkeypatch.setattr(
        "mada_tools.server_management.server_manager.psutil.Process",
        lambda pid: fake_parent,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "stop-servers",
            "--servers",
            "alpha",
            "--state-file",
            str(state_file),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)
    assert fake_parent.terminated is True
    assert fake_parent.killed is True
    assert child1.killed is True
    assert child2.killed is True

    state = json.loads(state_file.read_text())
    assert state["servers"] == {}


def test_main_stop_servers_skips_unmatched_pid_and_leaves_state_unchanged(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    state_file: Path,
    register_server: Callable,
):
    """
    End-to-end test, verify the CLI stop-servers command does not stop a
    process whose command line does not appear to match the requested server.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
        patch_cli_dependencies (None):
            Fixture that patches nonessential external boundaries.
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
        package="fake_pkg",
        module_path="fake_pkg.alpha.server",
    )

    fake_proc = DummyPsutilProcess(
        1001,
        cmdline=["python", "-m", "completely.different.server"],
    )

    monkeypatch.setattr(
        "mada_tools.server_management.server_manager.psutil.Process",
        lambda pid: fake_proc,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "stop-servers",
            "--servers",
            "alpha",
            "--state-file",
            str(state_file),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)
    assert fake_proc.terminated is False

    state = json.loads(state_file.read_text())
    assert state["servers"] == {}
