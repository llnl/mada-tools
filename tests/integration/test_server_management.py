# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Integration tests for MCP server management.

These tests verify interactions between ServerManager, ServerStateManager,
and the core ServerInfo/ServerStatus data structures. External process,
network, and plugin discovery behavior is mocked so the tests remain
deterministic and do not require real MCP servers.
"""

from pathlib import Path
from typing import Dict

import pytest
from _pytest.monkeypatch import MonkeyPatch

from mada_tools.server_management import ServerInfo, ServerStatus
from mada_tools.server_management.server_manager import ServerManager
from mada_tools.server_management.state_manager import ServerStateManager
from mada_tools.shared import PortInUseError


class DummyProcess:
    """
    Simple fake subprocess process object for testing process lifecycle behavior.
    """

    def __init__(self, pid=12345, poll_result=None):
        """
        Initialize the dummy process.

        Args:
            pid: Fake process ID.
            poll_result: Value returned by poll(), where None means still running.
        """
        self.pid = pid
        self.returncode = 1
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
    Simple fake psutil.Process replacement for stop-server tests.
    """

    def __init__(self, pid, cmdline=None, wait_raises=None):
        """
        Initialize the fake process.

        Args:
            pid: Fake process ID.
            cmdline: Fake command line list.
            wait_raises: Optional exception instance to raise from wait().
        """
        self.pid = pid
        self._cmdline = cmdline or []
        self._wait_raises = wait_raises
        self.terminated = False
        self.killed = False

    def cmdline(self):
        """
        Return the fake command line.

        Returns:
            list[str]: Simulated process command line.
        """
        return self._cmdline

    def terminate(self):
        """
        Simulate graceful termination.
        """
        self.terminated = True

    def wait(self, timeout=None):
        """
        Simulate waiting for process completion.

        Args:
            timeout: Timeout value, unused in fake implementation.

        Raises:
            Exception: Configured wait exception if provided.
        """
        if self._wait_raises:
            raise self._wait_raises
        return 0

    def children(self, recursive=False):
        """
        Return fake child processes.

        Args:
            recursive: Whether recursive search is requested.

        Returns:
            list: Empty child process list.
        """
        return []

    def kill(self):
        """
        Simulate force kill.
        """
        self.killed = True


@pytest.fixture
def discovered_servers() -> Dict[str, Dict[str, str]]:
    """
    Provide a fake discovered server registry.

    Returns:
        dict: Server discovery metadata keyed by server name.
    """
    return {
        "alpha": {
            "module_path": "fake_pkg.alpha.server",
            "package": "fake_pkg",
        },
        "beta": {
            "module_path": "fake_pkg.beta.server",
            "package": "fake_pkg",
        },
    }


def test_load_servers_merges_config_with_discovered_servers_and_state(
    state_file: Path,
    config_file: Path,
    discovered_servers: Dict[str, Dict[str, str]],
    monkeypatch: MonkeyPatch,
):
    """
    Verify that loading servers combines config data, discovery metadata,
    and persisted running-state information into ServerInfo objects.

    Args:
        state_file (Path):
            Path to a test-local state file.
        config_file (Path):
            Path to the generated JSON config file.
        discovered_servers (Dict[str, Dict[str, str]]):
            Server discovery metadata keyed by server name.
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
    """
    manager = ServerManager(state_file=state_file)

    running_alpha = ServerInfo(
        name="alpha",
        package="old_pkg",
        module_path="old.module",
        pid=9999,
        host="127.0.0.1",
        port=7000,
        status=ServerStatus.RUNNING,
    )

    monkeypatch.setattr(manager, "_discover_servers", lambda: discovered_servers)
    monkeypatch.setattr(
        manager.state_manager,
        "get_running_servers",
        lambda validate=True: {"alpha": running_alpha},
    )

    servers = manager._load_servers(config_file)

    assert set(servers.keys()) == {"alpha", "beta"}

    assert servers["alpha"].pid == 9999
    assert servers["alpha"].status == ServerStatus.RUNNING
    assert servers["alpha"].module_path == "fake_pkg.alpha.server"
    assert servers["alpha"].package == "fake_pkg"
    assert servers["alpha"].port == 8001

    assert servers["beta"].pid is None
    assert servers["beta"].status == ServerStatus.STOPPED
    assert servers["beta"].module_path == "fake_pkg.beta.server"
    assert servers["beta"].package == "fake_pkg"
    assert servers["beta"].port == 8002


def test_start_server_registers_state_and_marks_running_when_port_becomes_healthy(
    state_file: Path,
    config_file: Path,
    discovered_servers: Dict[str, Dict[str, str]],
    monkeypatch: MonkeyPatch,
):
    """
    Verify that starting a server launches a subprocess, registers state,
    and updates the server status to RUNNING when the health check succeeds.

    Args:
        state_file (Path):
            Path to a test-local state file.
        config_file (Path):
            Path to the generated JSON config file.
        discovered_servers (Dict[str, Dict[str, str]]):
            Server discovery metadata keyed by server name.
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
    """
    manager = ServerManager(state_file=state_file)

    monkeypatch.setattr(manager, "_discover_servers", lambda: discovered_servers)
    monkeypatch.setattr(manager.state_manager, "get_running_servers", lambda validate=True: {})

    servers = manager._load_servers(config_file)
    alpha = servers["alpha"]

    popen_calls = []

    def fake_popen(cmd, stdout, stderr, env, start_new_session):
        popen_calls.append(
            {
                "cmd": cmd,
                "env": env,
                "start_new_session": start_new_session,
            }
        )
        return DummyProcess(pid=4321, poll_result=None)

    port_check_calls = {"count": 0}

    def fake_is_port_in_use(host, port):
        port_check_calls["count"] += 1
        if port_check_calls["count"] == 1:
            return False
        return True

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr(manager.state_manager, "_is_port_in_use", fake_is_port_in_use)
    monkeypatch.setattr("time.sleep", lambda _: None)

    manager.start_server(config_file, "alpha", alpha)

    saved = manager.state_manager.get_server("alpha")
    assert saved is not None
    assert saved.pid == 4321
    assert saved.status == ServerStatus.RUNNING

    assert popen_calls
    assert popen_calls[0]["cmd"][0]
    assert popen_calls[0]["cmd"][1:] == [
        "-m",
        "fake_pkg.alpha.server",
        "--config",
        str(config_file),
    ]
    assert popen_calls[0]["env"]["MODE"] == "test"


def test_start_server_marks_failed_if_process_exits_immediately(
    state_file: Path,
    config_file: Path,
    discovered_servers: Dict[str, Dict[str, str]],
    monkeypatch: MonkeyPatch,
):
    """
    Verify that starting a server marks it as FAILED when the subprocess
    exits before passing the startup check.

    Args:
        state_file (Path):
            Path to a test-local state file.
        config_file (Path):
            Path to the generated JSON config file.
        discovered_servers (Dict[str, Dict[str, str]]):
            Server discovery metadata keyed by server name.
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
    """
    manager = ServerManager(state_file=state_file)

    monkeypatch.setattr(manager, "_discover_servers", lambda: discovered_servers)
    monkeypatch.setattr(manager.state_manager, "get_running_servers", lambda validate=True: {})
    monkeypatch.setattr(manager.state_manager, "_is_port_in_use", lambda host, port: False)
    monkeypatch.setattr("time.sleep", lambda _: None)
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda *args, **kwargs: DummyProcess(pid=5555, poll_result=1),
    )

    servers = manager._load_servers(config_file)
    manager.start_server(config_file, "alpha", servers["alpha"])

    saved = manager.state_manager.get_server("alpha")
    assert saved is not None
    assert saved.status == ServerStatus.FAILED
    assert saved.pid == 5555


def test_start_server_raises_port_in_use_error_before_launch(
    state_file: Path,
    config_file: Path,
    discovered_servers: Dict[str, Dict[str, str]],
    monkeypatch: MonkeyPatch,
):
    """
    Verify that starting a server raises PortInUseError when the configured
    host and port are already in use before subprocess launch.

    Args:
        state_file (Path):
            Path to a test-local state file.
        config_file (Path):
            Path to the generated JSON config file.
        discovered_servers (Dict[str, Dict[str, str]]):
            Server discovery metadata keyed by server name.
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
    """
    manager = ServerManager(state_file=state_file)

    monkeypatch.setattr(manager, "_discover_servers", lambda: discovered_servers)
    monkeypatch.setattr(manager.state_manager, "get_running_servers", lambda validate=True: {})
    monkeypatch.setattr(manager.state_manager, "_is_port_in_use", lambda host, port: True)

    servers = manager._load_servers(config_file)

    with pytest.raises(PortInUseError):
        manager.start_server(config_file, "alpha", servers["alpha"])


def test_stop_server_removes_server_from_state_after_graceful_shutdown(
    state_file: Path,
    monkeypatch: MonkeyPatch,
):
    """
    Verify that stopping a running server terminates the process gracefully
    and removes the server entry from persisted state.

    Args:
        state_file (Path):
            Path to a test-local state file.
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
    """
    manager = ServerManager(state_file=state_file)

    info = ServerInfo(
        name="alpha",
        package="fake_pkg",
        module_path="fake_pkg.alpha.server",
        pid=2468,
        host="127.0.0.1",
        port=8001,
        status=ServerStatus.RUNNING,
    )
    manager.state_manager.register_server(info, {})

    fake_proc = DummyPsutilProcess(
        pid=2468,
        cmdline=["python", "-m", "fake_pkg.alpha.server", "alpha"],
    )

    monkeypatch.setattr("psutil.Process", lambda pid: fake_proc)

    stopped = manager.stop_server("alpha", info)

    assert stopped is True
    assert fake_proc.terminated is True
    assert manager.state_manager.get_server("alpha") is None


def test_restart_server_stops_existing_process_and_starts_fresh(
    state_file: Path,
    config_file: Path,
    discovered_servers: Dict[str, Dict[str, str]],
    monkeypatch: MonkeyPatch,
):
    """
    Verify that restarting a server stops an existing running instance
    and then starts a fresh instance using current configuration.

    Args:
        state_file (Path):
            Path to a test-local state file.
        config_file (Path):
            Path to the generated JSON config file.
        discovered_servers (Dict[str, Dict[str, str]]):
            Server discovery metadata keyed by server name.
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
    """
    manager = ServerManager(state_file=state_file)

    existing = ServerInfo(
        name="alpha",
        package="fake_pkg",
        module_path="fake_pkg.alpha.server",
        pid=1111,
        host="127.0.0.1",
        port=8001,
        status=ServerStatus.RUNNING,
    )
    manager.state_manager.register_server(existing, {})

    monkeypatch.setattr(manager, "_discover_servers", lambda: discovered_servers)
    monkeypatch.setattr(
        manager.state_manager,
        "get_running_servers",
        lambda validate=True: {"alpha": existing},
    )

    servers = manager._load_servers(config_file)

    calls = []

    def fake_stop_server(name, server_info, timeout=10):
        calls.append(("stop", name, server_info.pid))
        manager.state_manager.remove_server(name)
        return True

    def fake_start_server(config_file_arg, name, server_info):
        calls.append(("start", name, server_info.module_path))
        server_info.pid = 2222
        server_info.status = ServerStatus.RUNNING
        manager.state_manager.register_server(server_info, {})
        manager.state_manager.update_server_status(name, ServerStatus.RUNNING)

    monkeypatch.setattr(manager, "stop_server", fake_stop_server)
    monkeypatch.setattr(manager, "start_server", fake_start_server)

    manager.restart_server(config_file, "alpha", servers["alpha"])

    assert calls == [
        ("stop", "alpha", 1111),
        ("start", "alpha", "fake_pkg.alpha.server"),
    ]

    saved = manager.state_manager.get_server("alpha")
    assert saved is not None
    assert saved.status == ServerStatus.RUNNING
    assert saved.pid == 2222


def test_get_server_statuses_with_config_includes_stopped_servers_from_config(
    state_file: Path,
    config_file: Path,
    discovered_servers: Dict[str, Dict[str, str]],
    monkeypatch: MonkeyPatch,
):
    """
    Verify that get_server_statuses returns configured servers, including
    servers that are currently stopped, when a config file is provided.

    Args:
        state_file (Path):
            Path to a test-local state file.
        config_file (Path):
            Path to the generated JSON config file.
        discovered_servers (Dict[str, Dict[str, str]]):
            Server discovery metadata keyed by server name.
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
    """
    manager = ServerManager(state_file=state_file)

    running_alpha = ServerInfo(
        name="alpha",
        package="fake_pkg",
        module_path="fake_pkg.alpha.server",
        pid=9999,
        host="127.0.0.1",
        port=8001,
        status=ServerStatus.RUNNING,
    )

    monkeypatch.setattr(manager, "_discover_servers", lambda: discovered_servers)
    monkeypatch.setattr(
        manager.state_manager,
        "get_running_servers",
        lambda validate=True: {"alpha": running_alpha},
    )

    statuses = manager.get_server_statuses(config_file=config_file)

    assert set(statuses.keys()) == {"alpha", "beta"}
    assert statuses["alpha"].status == ServerStatus.RUNNING
    assert statuses["beta"].status == ServerStatus.STOPPED


def test_state_manager_get_running_servers_filters_out_stopped_entries(
    state_file: Path,
):
    """
    Verify that the state manager returns only active server entries from
    get_running_servers and excludes stopped entries.

    Args:
        state_file (Path):
            Path to a test-local state file.
    """
    state_manager = ServerStateManager(state_file=state_file)

    running = ServerInfo(
        name="alpha",
        package="fake_pkg",
        module_path="fake_pkg.alpha.server",
        pid=123,
        status=ServerStatus.RUNNING,
        host="localhost",
        port=9001,
    )
    stopped = ServerInfo(
        name="beta",
        package="fake_pkg",
        module_path="fake_pkg.beta.server",
        pid=None,
        status=ServerStatus.STOPPED,
        host="localhost",
        port=9002,
    )

    state_manager.register_server(running, {})
    state_manager.register_server(stopped, {})
    state_manager.update_server_status("alpha", ServerStatus.RUNNING)
    state_manager.update_server_status("beta", ServerStatus.STOPPED)

    running_servers = state_manager.get_running_servers(validate=False)

    assert set(running_servers.keys()) == {"alpha"}
    assert running_servers["alpha"].status == ServerStatus.RUNNING


def test_state_manager_validation_updates_running_and_unhealthy_statuses(
    state_file: Path,
    monkeypatch: MonkeyPatch,
):
    """
    Verify that state validation updates server statuses based on process
    liveness and port health checks.

    Args:
        state_file (Path):
            Path to a test-local state file.
        monkeypatch (MonkeyPatch):
            Pytest mocker fixture.
    """
    state_manager = ServerStateManager(state_file=state_file)

    healthy = ServerInfo(
        name="alpha",
        package="fake_pkg",
        module_path="fake_pkg.alpha.server",
        pid=1001,
        host="localhost",
        port=7001,
        status=ServerStatus.STARTING,
    )
    unhealthy = ServerInfo(
        name="beta",
        package="fake_pkg",
        module_path="fake_pkg.beta.server",
        pid=1002,
        host="localhost",
        port=7002,
        status=ServerStatus.STARTING,
    )

    state_manager.register_server(healthy, {})
    state_manager.register_server(unhealthy, {})

    monkeypatch.setattr(
        state_manager,
        "_is_process_running",
        lambda pid: True,
    )
    monkeypatch.setattr(
        state_manager,
        "_is_port_in_use",
        lambda host, port: port == 7001,
    )

    servers = state_manager.get_servers(validate=True)

    assert servers["alpha"].status == ServerStatus.RUNNING
    assert servers["beta"].status == ServerStatus.UNHEALTHY
