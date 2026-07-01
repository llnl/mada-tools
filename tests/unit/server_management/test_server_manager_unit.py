# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Tests for the `server_manager.py` module.
"""

import json
import logging
import types
from datetime import datetime
from pathlib import Path
from typing import Dict
from unittest.mock import MagicMock, patch

import psutil
import pytest
from _pytest.logging import LogCaptureFixture
from _pytest.monkeypatch import MonkeyPatch
from pytest_mock import MockerFixture

from mada_tools.extensions.registry import ExtensionRegistry
from mada_tools.server_management.server_info import ServerInfo, ServerStatus
from mada_tools.server_management.server_manager import ServerManager
from mada_tools.shared import PortInUseError


@pytest.fixture
def dummy_state_manager(mocker: MockerFixture) -> type:
    """
    Set up a dummy StateManager class for testing.

    Args:
        mocker (MockerFixture):
            Pytest mocker fixture.

    Returns:
        A `DummyStateManager` class for testing.
    """

    class DummyStateManager:
        def __init__(self, running_servers: Dict[str, ServerInfo]):
            self._running_servers = running_servers

        def get_running_servers(self, validate: bool = True):
            return self._running_servers

    return DummyStateManager


@pytest.fixture
def server_manager(mocker: MockerFixture, dummy_state_manager: type) -> ServerManager:
    """
    Create an instance of the `ServerManager` class, with
    `discover_servers` and `state_manager` mocked or injected.

    Args:
        mocker (MockerFixture):
            Pytest mocker fixture.
        dummy_state_manager (DummyStateManager):
            A `DummyStateManager` class for testing.

    Returns:
        A `ServerManager` instance to use for testing.
    """
    # Adjust to how you actually construct your class
    obj = ServerManager()

    # Patch registry-backed discovery; default is empty, override in tests as needed
    mocker.patch.object(obj._extension_registry, "get_mcp_server_index", return_value={})

    # Default state manager has no running servers, override in tests as needed
    obj.state_manager = dummy_state_manager(running_servers={})

    return obj


@pytest.fixture
def server_info() -> ServerInfo:
    """
    Returns an instance of `ServerInfo` that can be used for testing.
    """
    return ServerInfo(
        name="srv",
        package="mada_tools",
        module_path="mada_tools.some_server",
        pid=12345,
    )


def write_config(server_management_testing_dir: Path, content: dict) -> Path:
    config_file = server_management_testing_dir / "config.json"
    config_file.write_text(json.dumps(content))
    return config_file


# ---------------------------------------
# ---------- Constructor tests ----------
# ---------------------------------------


def test_server_manager_constructor_uses_state_file():
    """
    Verify that `ServerManager`'s constructor passes the provided `state_file`
    argument through to `ServerStateManager` and stores the created
    `ServerStateManager` instance on the manager.
    """
    fake_state_file = Path("/tmp/fake_state.json")

    with patch("mada_tools.server_management.server_manager.ServerStateManager") as MockStateManager:
        manager = ServerManager(state_file=fake_state_file)

        # Ensure ServerStateManager was constructed with the given state_file
        MockStateManager.assert_called_once_with(state_file=fake_state_file)
        # And the instance is stored on the manager
        assert manager.state_manager is MockStateManager.return_value


def test_server_manager_constructor_default_state_file():
    """
    Verify that `ServerManager`'s constructor uses `state_file=None` by default
    when no `state_file` argument is provided, and that the resulting
    `ServerStateManager` instance is stored on the manager.
    """
    with patch("mada_tools.server_management.server_manager.ServerStateManager") as MockStateManager:
        manager = ServerManager()

        # Should be called with state_file=None by default
        MockStateManager.assert_called_once_with(state_file=None)
        assert manager.state_manager is MockStateManager.return_value


# ---------------------------------------------
# ---------- Discovery wiring tests ----------
# ---------------------------------------------


def test_server_manager_constructor_initializes_extension_registry():
    """Verify that `ServerManager` creates an `ExtensionRegistry` instance."""
    with patch("mada_tools.server_management.server_manager.ServerStateManager"):
        manager = ServerManager()

    assert isinstance(manager._extension_registry, ExtensionRegistry)


def test_load_servers_uses_extension_registry_index(monkeypatch: MonkeyPatch, server_management_testing_dir: Path):
    """Verify that `_load_servers()` queries the registry-backed server index."""
    config_file = write_config(server_management_testing_dir, {"servers": {"slurm": {}}})
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager.state_manager.get_running_servers.return_value = {}

    registry_mock = MagicMock(
        return_value={
            "slurm": ServerInfo(
                name="slurm",
                package="mada_tools",
                module_path="mada_tools.scheduler.slurm.server",
            )
        }
    )
    monkeypatch.setattr(manager._extension_registry, "get_mcp_server_index", registry_mock)

    manager._load_servers(config_file)

    registry_mock.assert_called_once_with()


# -----------------------------------------
# ---------- _load_servers tests ----------
# -----------------------------------------


def test_load_servers_raises_when_config_missing(server_management_testing_dir: Path):
    """
    Verify that `_load_servers` raises `FileNotFoundError` when the provided
    configuration file path does not exist.

    Args:
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the `server_management` directory.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()

    tmp_dir = server_management_testing_dir / "test_load_servers_raises_when_config_missing"
    missing = tmp_dir / "missing_config.json"

    with pytest.raises(FileNotFoundError) as excinfo:
        manager._load_servers(missing)

    assert str(missing) in str(excinfo.value)


def test_load_servers_uses_discovered_servers_for_mada_package(
    server_management_testing_dir: Path,
    monkeypatch: MonkeyPatch,
):
    """
    Verify that for servers with package 'mada_tools' (or default),
    _load_servers:
      - uses the extension registry to resolve the server module path,
      - creates ServerInfo with the correct module path and defaults,
      - and sets status to STOPPED for non running servers.

    Args:
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the `server_management` directory.
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
    """
    config_data = {
        "servers": {
            "slurm": {
                # package omitted, so default "mada_tools" is used
                "host": "example.com",
                "port": 9000,
                "env_vars": {"A": "1"},
                "log_file": "~/custom_slurm.log",
            }
        }
    }

    tmp_dir = server_management_testing_dir / "test_load_servers_uses_discovered_servers_for_mada_package"
    tmp_dir.mkdir(parents=True)
    config_file = tmp_dir / "config.json"
    config_file.write_text(json.dumps(config_data))

    manager = ServerManager(state_file=None)

    # Mock state manager to report no running servers
    manager.state_manager = MagicMock()
    manager.state_manager.get_running_servers.return_value = {}

    # Mock discovered servers
    monkeypatch.setattr(
        manager._extension_registry,
        "get_mcp_server_index",
        MagicMock(
            return_value={
                "slurm": ServerInfo(
                    name="slurm",
                    package="mada_tools",
                    module_path="mada_tools.scheduler.slurm.server",
                )
            }
        ),
    )

    servers = manager._load_servers(config_file)

    assert set(servers.keys()) == {"slurm"}
    slurm_info = servers["slurm"]

    assert isinstance(slurm_info, ServerInfo)
    assert slurm_info.name == "slurm"
    assert slurm_info.package == "mada_tools"
    assert slurm_info.module_path == "mada_tools.scheduler.slurm.server"
    # log_file should be expanded
    assert slurm_info.log_file == Path("~/custom_slurm.log").expanduser()
    assert slurm_info.env_vars == {"A": "1"}
    assert slurm_info.host == "example.com"
    assert slurm_info.port == 9000
    assert slurm_info.status == ServerStatus.STOPPED

    manager.state_manager.get_running_servers.assert_called_once_with(validate=True)
    manager._extension_registry.get_mcp_server_index.assert_called_once_with()


def test_load_servers_skips_missing_mada_server(
    server_management_testing_dir: Path,
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
):
    """
    Verify that when a server is configured with package 'mada_tools'
    but is not present in the discovered servers mapping, _load_servers:
      - logs a warning,
      - and skips that server from the returned mapping.

    Args:
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the `server_management` directory.
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    config_data = {
        "servers": {
            "missing_server": {
                "package": "mada_tools",
            }
        }
    }

    tmp_dir = server_management_testing_dir / "test_load_servers_skips_missing_mada_server"
    tmp_dir.mkdir(parents=True)
    config_file = tmp_dir / "config.json"
    config_file.write_text(json.dumps(config_data))

    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager.state_manager.get_running_servers.return_value = {}

    monkeypatch.setattr(
        manager._extension_registry,
        "get_mcp_server_index",
        MagicMock(
            return_value={
                "other": ServerInfo(
                    name="other",
                    package="mada_tools",
                    module_path="mada_tools.other.server",
                )
            }
        ),
    )

    with caplog.at_level("WARNING"):
        servers = manager._load_servers(config_file)

    assert servers == {}
    assert any(
        "Server 'missing_server' not found in discovered servers, skipping" in record.message
        for record in caplog.records
    )


def test_load_servers_skips_server_not_in_discovery(
    server_management_testing_dir: Path,
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
):
    """
    Verify that `_load_servers()` skips servers that are not found in discovery.

    Args:
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the `server_management` directory.
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    config_data = {
        "servers": {
            "myserver": {
                "host": "localhost",
            }
        }
    }

    tmp_dir = server_management_testing_dir / "test_load_servers_skips_server_not_in_discovery"
    tmp_dir.mkdir(parents=True)
    config_file = tmp_dir / "config.json"
    config_file.write_text(json.dumps(config_data))

    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager.state_manager.get_running_servers.return_value = {}

    monkeypatch.setattr(manager._extension_registry, "get_mcp_server_index", MagicMock(return_value={}))

    with caplog.at_level("WARNING"):
        servers = manager._load_servers(config_file)

    assert servers == {}
    assert any(
        "Server 'myserver' not found in discovered servers, skipping" in record.message for record in caplog.records
    )


def test_load_servers_uses_default_log_file_and_host(
    server_management_testing_dir: Path,
    monkeypatch: MonkeyPatch,
):
    """
    Verify that when log_file and host are omitted in the configuration,
    _load_servers:
      - uses ~/.mada/server_logs/<name>.log as the default log file,
      - uses 'localhost' as the default host.

    Args:
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the `server_management` directory.
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
    """
    config_data = {
        "servers": {
            "slurm": {
                # no log_file, no host
                "port": 1234,
            }
        }
    }

    tmp_dir = server_management_testing_dir / "test_load_servers_uses_default_log_file_and_host"
    tmp_dir.mkdir(parents=True)
    config_file = tmp_dir / "config.json"
    config_file.write_text(json.dumps(config_data))

    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager.state_manager.get_running_servers.return_value = {}

    monkeypatch.setattr(
        manager._extension_registry,
        "get_mcp_server_index",
        MagicMock(
            return_value={
                "slurm": ServerInfo(
                    name="slurm",
                    package="mada_tools",
                    module_path="mada_tools.scheduler.slurm.server",
                )
            }
        ),
    )

    servers = manager._load_servers(config_file)
    slurm_info = servers["slurm"]

    expected_log_file = Path.home() / ".mada" / "server_logs" / "slurm.log"
    assert slurm_info.log_file == expected_log_file
    assert slurm_info.host == "localhost"
    assert slurm_info.port == 1234


def test_load_servers_updates_running_server_info(
    server_management_testing_dir: Path,
    monkeypatch: MonkeyPatch,
):
    """
    Verify that when a server is already running and present in the state
    manager's running_servers mapping, _load_servers:
      - reuses the existing ServerInfo object,
      - updates its package, log_file, env_vars, host, and port fields from
        the configuration and discovery results,
      - keeps status and other runtime properties from the existing object.

    Args:
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the `server_management` directory.
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
    """
    config_data = {
        "servers": {
            "slurm": {
                "host": "updated-host",
                "port": 9999,
                "env_vars": {"B": "2"},
            }
        }
    }

    tmp_dir = server_management_testing_dir / "test_load_servers_updates_running_server_info"
    tmp_dir.mkdir(parents=True)
    config_file = tmp_dir / "config.json"
    config_file.write_text(json.dumps(config_data))

    manager = ServerManager(state_file=None)

    # Existing running server info
    existing_info = ServerInfo(
        name="slurm",
        package="old",
        module_path="old.package",
        log_file=Path("/tmp/old.log"),
        env_vars={"OLD": "x"},
        host="old-host",
        port=1111,
        status=ServerStatus.RUNNING,
    )

    running_servers = {"slurm": existing_info}

    manager.state_manager = MagicMock()
    manager.state_manager.get_running_servers.return_value = running_servers

    monkeypatch.setattr(
        manager._extension_registry,
        "get_mcp_server_index",
        MagicMock(
            return_value={
                "slurm": ServerInfo(
                    name="slurm",
                    package="mada_tools",
                    module_path="mada_tools.scheduler.slurm.server",
                )
            }
        ),
    )

    servers = manager._load_servers(config_file)

    # Should be the same instance, updated in place
    assert servers["slurm"] is existing_info
    info = servers["slurm"]

    assert info.package == "mada_tools"
    assert info.module_path == "mada_tools.scheduler.slurm.server"
    # Default log path since not in config
    assert info.log_file == Path.home() / ".mada" / "server_logs" / "slurm.log"
    assert info.env_vars == {"B": "2"}
    assert info.host == "updated-host"
    assert info.port == 9999
    # Status should remain RUNNING
    assert info.status == ServerStatus.RUNNING


# -----------------------------------------
# ---------- start_servers tests ----------
# -----------------------------------------


def test_start_servers_all_servers(server_management_testing_dir: Path, monkeypatch: MonkeyPatch):
    """
    Verify that when server_names is None, start_servers:
      - loads all servers from _load_servers,
      - calls start_server once for each loaded server,
      - passes through the config_file, server name, and ServerInfo instance.

    Args:
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the `server_management` directory.
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
    """
    tmp_dir = server_management_testing_dir / "test_start_servers_all_servers"
    tmp_dir.mkdir(parents=True)
    config_file = tmp_dir / "config.json"
    config_file.write_text("{}")

    manager = ServerManager(state_file=None)

    # Fake servers returned from _load_servers
    fake_server_info_a = MagicMock(name="ServerInfoA")
    fake_server_info_b = MagicMock(name="ServerInfoB")
    fake_servers = {
        "server_a": fake_server_info_a,
        "server_b": fake_server_info_b,
    }

    monkeypatch.setattr(manager, "_load_servers", MagicMock(return_value=fake_servers))
    manager.start_server = MagicMock()

    manager.start_servers(config_file)

    # _load_servers should be called once with config_file
    manager._load_servers.assert_called_once_with(config_file)

    # start_server should be called for both servers
    expected_calls = [
        ((config_file, "server_a", fake_server_info_a), {}),
        ((config_file, "server_b", fake_server_info_b), {}),
    ]
    actual_calls = [(c.args, c.kwargs) for c in manager.start_server.call_args_list]
    assert actual_calls == expected_calls


def test_start_servers_specific_servers(server_management_testing_dir: Path, monkeypatch: MonkeyPatch):
    """
    Verify that when server_names is provided, start_servers:
      - validates that all requested names exist in the loaded servers,
      - only calls start_server for the requested subset,
      - in the order of server_names.

    Args:
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the `server_management` directory.
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
    """
    tmp_dir = server_management_testing_dir / "test_start_servers_specific_servers"
    tmp_dir.mkdir(parents=True)
    config_file = tmp_dir / "config.json"
    config_file.write_text("{}")

    manager = ServerManager(state_file=None)

    s1 = MagicMock(name="ServerInfo1")
    s2 = MagicMock(name="ServerInfo2")
    s3 = MagicMock(name="ServerInfo3")
    fake_servers = {"a": s1, "b": s2, "c": s3}

    monkeypatch.setattr(manager, "_load_servers", MagicMock(return_value=fake_servers))
    manager.start_server = MagicMock()

    manager.start_servers(config_file, server_names=["c", "a"])

    # Ensure load called once
    manager._load_servers.assert_called_once_with(config_file)

    # Only "c" and "a" should be started, in that order
    expected_calls = [
        ((config_file, "c", s3), {}),
        ((config_file, "a", s1), {}),
    ]
    actual_calls = [(c.args, c.kwargs) for c in manager.start_server.call_args_list]
    assert actual_calls == expected_calls


def test_start_servers_unknown_server_raises(server_management_testing_dir: Path, monkeypatch: MonkeyPatch):
    """
    Verify that if server_names contains a name not present in the loaded servers,
    start_servers raises ValueError and does not call start_server at all.

    Args:
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the `server_management` directory.
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
    """
    tmp_dir = server_management_testing_dir / "test_start_servers_unknown_server_raises"
    tmp_dir.mkdir(parents=True)
    config_file = tmp_dir / "config.json"
    config_file.write_text("{}")

    manager = ServerManager(state_file=None)

    s1 = MagicMock(name="ServerInfo1")
    fake_servers = {"a": s1}

    monkeypatch.setattr(manager, "_load_servers", MagicMock(return_value=fake_servers))
    manager.start_server = MagicMock()

    with pytest.raises(ValueError) as excinfo:
        manager.start_servers(config_file, server_names=["a", "missing"])

    assert "Unknown server: missing" in str(excinfo.value)

    # start_server should not be called if validation fails
    manager.start_server.assert_not_called()


def test_start_servers_propagates_start_error_and_logs(
    server_management_testing_dir: Path,
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
):
    """
    Verify that if start_server raises an exception for a server,
    start_servers:
      - logs an error mentioning that specific server,
      - re-raises the original exception.

    Args:
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of
            files in the `server_management` directory.
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    tmp_dir = server_management_testing_dir / "test_start_servers_propagates_start_error_and_logs"
    tmp_dir.mkdir(parents=True)
    config_file = tmp_dir / "config.json"
    config_file.write_text("{}")

    manager = ServerManager(state_file=None)

    s1 = MagicMock(name="ServerInfo1")
    fake_servers = {"a": s1}

    monkeypatch.setattr(manager, "_load_servers", MagicMock(return_value=fake_servers))

    def failing_start_server(cfg, name, info):
        raise RuntimeError("start failed")

    manager.start_server = MagicMock(side_effect=failing_start_server)

    with caplog.at_level("ERROR"), pytest.raises(RuntimeError, match="start failed"):
        manager.start_servers(config_file)

    # There should be an error log mentioning the server name
    assert any("Failed to start server 'a'." in record.message for record in caplog.records)


# ----------------------------------------
# ---------- start_server tests ----------
# ----------------------------------------


def _make_server_info(
    tmp_path: Path,
    name: str = "srv",
    package: str = "pkg",
    module_path: str = "pkg.server",
    port: int = None,
    pid: int = 12345,
):
    """
    Helper to construct a minimal `ServerInfo` with a log file in tmp_path.

    Args:
        tmp_path (Path):
            Temporary path to store log file.
        name (str):
            Server name.
        package (str):
            The package the server is associated with.
        port (int):
            The port for the server.
        pid (int):
            The process ID for the server.
    """
    return ServerInfo(
        name=name,
        package=package,
        module_path=module_path,
        log_file=tmp_path / f"{name}.log",
        env_vars={"FOO": "bar"},
        host="localhost",
        port=port,
        status=ServerStatus.STOPPED,
        pid=pid,
    )


def test_start_server_returns_if_already_running(server_management_testing_dir: Path, caplog: LogCaptureFixture):
    """
    Verify that if state_manager.get_server returns an entry with a valid pid
    and _is_process_running returns True, start_server:
      - logs that the server is already running,
      - does not attempt to start a new process,
      - does not change server_info status.

    Args:
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of
            files in the `server_management` directory.
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()

    tmp_dir = server_management_testing_dir / "test_start_server_returns_if_already_running"
    tmp_dir.mkdir(parents=True)

    existing_info = ServerInfo(
        name="srv",
        package="pkg",
        module_path="pkg.server",
        log_file=tmp_dir / "srv.log",
        env_vars={},
        host="localhost",
        port=None,
        status=ServerStatus.RUNNING,
    )
    existing_info.pid = 1234

    manager.state_manager.get_server.return_value = existing_info
    manager.state_manager._is_process_running.return_value = True

    info = _make_server_info(tmp_dir, name="srv")

    # Create dummy config file
    config_file = tmp_dir / "config.json"
    config_file.write_text(json.dumps({"servers": {"srv": {}}}))

    with caplog.at_level("INFO"):
        manager.start_server(config_file, "srv", info)

    # Should not call Popen nor register_server
    manager.state_manager.register_server.assert_not_called()
    assert info.status == ServerStatus.STOPPED
    # Expect log message that server is already running
    assert "is already running" in caplog.text


def test_start_server_starts_new_process_and_registers(
    server_management_testing_dir: Path,
):
    """
    Verify that when the server is not already running, start_server:
      - prepares the log file directory and opens the log file,
      - builds the correct command using 'python -m <package> --config <file>',
      - starts a subprocess with the environment containing env_vars,
      - updates server_info pid, status, and started_at,
      - reads config file and calls state_manager.register_server with server_info
        and the specific server config.

    Args:
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of
            files in the `server_management` directory.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()

    tmp_dir = server_management_testing_dir / "test_start_server_starts_new_process_and_registers"
    tmp_dir.mkdir(parents=True)

    # Simulate not already running
    manager.state_manager.get_server.return_value = None

    info = _make_server_info(tmp_dir, name="srv", package="pkg", module_path="pkg.server", port=None)

    # Config file with a server entry
    config = {"servers": {"srv": {"extra": "value"}}}
    config_file = tmp_dir / "config.json"
    config_file.write_text(json.dumps(config))

    # Patch subprocess.Popen to avoid real process
    class DummyProcess:
        def __init__(self, pid):
            self.pid = pid
            self.poll_called = False

        def poll(self):
            self.poll_called = True

    popen_mock = MagicMock(return_value=DummyProcess(pid=4321))

    # No health check because port is None
    manager.state_manager._is_port_in_use = MagicMock()

    with (
        patch(
            "mada_tools.server_management.server_manager.subprocess.Popen",
            popen_mock,
        ),
        patch(
            "mada_tools.server_management.server_manager.time.sleep",
            lambda *args, **kwargs: None,
        ),
    ):
        before = datetime.now()
        manager.start_server(config_file, "srv", info)
        after = datetime.now()

    # Verify command construction
    args, kwargs = popen_mock.call_args
    cmd = args[0]
    assert cmd[1] == "-m"
    assert cmd[2] == "pkg.server"
    assert "--config" in cmd
    assert str(config_file) in cmd

    # Environment should include our env_vars
    env = kwargs["env"]
    assert env["FOO"] == "bar"

    # ServerInfo updated
    assert info.pid == 4321
    assert info.status == ServerStatus.STARTING
    # started_at within reasonable range
    started_at = datetime.fromisoformat(info.started_at)
    assert before <= started_at <= after

    # register_server called with info and its config
    manager.state_manager.register_server.assert_called_once_with(info, config["servers"]["srv"])


def test_start_server_health_check_updates_status_running(
    server_management_testing_dir: Path,
):
    """
    Verify that when server_info.port is set and _is_port_in_use returns True
    after starting the server, start_server updates the server status to
    RUNNING via state_manager.

    Args:
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of
            files in the `server_management` directory.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager.state_manager.get_server.return_value = None

    tmp_dir = server_management_testing_dir / "test_start_server_health_check_updates_status_running"
    tmp_dir.mkdir(parents=True)

    info = _make_server_info(tmp_dir, name="srv", package="pkg", module_path="pkg.server", port=8000)

    config = {"servers": {"srv": {}}}
    config_file = tmp_dir / "config.json"
    config_file.write_text(json.dumps(config))

    class DummyProcess:
        def __init__(self, pid):
            self.pid = pid
            self.poll_called = False

        def poll(self):
            self.poll_called = True

    popen_mock = MagicMock(return_value=DummyProcess(pid=1111))

    manager.state_manager._is_port_in_use.side_effect = [False, True]

    with (
        patch(
            "mada_tools.server_management.server_manager.subprocess.Popen",
            popen_mock,
        ),
        patch(
            "mada_tools.server_management.server_manager.time.sleep",
            lambda *args, **kwargs: None,
        ),
    ):
        manager.start_server(config_file, "srv", info)

    manager.state_manager.update_server_status.assert_called_once_with("srv", ServerStatus.RUNNING)


def test_start_server_health_check_updates_status_unhealthy(
    server_management_testing_dir: Path,
):
    """
    Verify that when server_info.port is set and _is_port_in_use returns False
    after starting the server, start_server updates status to UNHEALTHY via
    state_manager.

    Args:
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of
            files in the `server_management` directory.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager.state_manager.get_server.return_value = None

    tmp_dir = server_management_testing_dir / "test_start_server_health_check_updates_status_unhealthy"
    tmp_dir.mkdir(parents=True)

    info = _make_server_info(tmp_dir, name="srv", package="pkg", module_path="pkg.server", port=8000)

    config = {"servers": {"srv": {}}}
    config_file = tmp_dir / "config.json"
    config_file.write_text(json.dumps(config))

    class DummyProcess:
        def __init__(self, pid):
            self.pid = pid
            self.poll_called = False

        def poll(self):
            self.poll_called = True

    popen_mock = MagicMock(return_value=DummyProcess(pid=2222))

    manager.state_manager._is_port_in_use.side_effect = [False, False]

    with (
        patch(
            "mada_tools.server_management.server_manager.subprocess.Popen",
            popen_mock,
        ),
        patch(
            "mada_tools.server_management.server_manager.time.sleep",
            lambda *args, **kwargs: None,
        ),
    ):
        manager.start_server(config_file, "srv", info)

    manager.state_manager.update_server_status.assert_called_once_with("srv", ServerStatus.UNHEALTHY)


def test_start_server_handles_exception_and_sets_failed_status(
    server_management_testing_dir: Path,
    caplog: LogCaptureFixture,
):
    """
    Verify that if an exception occurs during process start, start_server:
      - logs an error mentioning the server name,
      - sets server_info.status to FAILED,
      - re-raises the exception.

    Args:
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of
            files in the `server_management` directory.
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager.state_manager.get_server.return_value = None

    tmp_dir = server_management_testing_dir / "test_start_server_handles_exception_and_sets_failed_status"
    tmp_dir.mkdir(parents=True)

    info = _make_server_info(tmp_dir, name="srv", package="pkg", module_path="pkg.server", port=None)

    config = {"servers": {"srv": {}}}
    config_file = tmp_dir / "config.json"
    config_file.write_text(json.dumps(config))

    def failing_popen(*args, **kwargs):
        raise RuntimeError("boom")

    with (
        patch(
            "mada_tools.server_management.server_manager.subprocess.Popen",
            failing_popen,
        ),
        patch(
            "mada_tools.server_management.server_manager.time.sleep",
            lambda *args, **kwargs: None,
        ),
        caplog.at_level("ERROR"),
        pytest.raises(RuntimeError, match="boom"),
    ):
        manager.start_server(config_file, "srv", info)

    assert info.status == ServerStatus.FAILED
    assert "Failed to start server 'srv'" in caplog.text


def test_start_server_raises_port_in_use_error(server_management_testing_dir: Path):
    """
    Verify that when the requested port to start a server on is already in use,
    `start_server` raises a `PortInUseError`.

    Args:
        server_management_testing_dir (Path):
            The path to the temporary testing directory for tests of
            files in the `server_management` directory.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager.state_manager.get_server.return_value = None
    manager.state_manager._is_port_in_use.return_value = True

    tmp_dir = server_management_testing_dir / "test_start_server_raises_port_in_use_error"
    tmp_dir.mkdir(parents=True)

    info = _make_server_info(
        tmp_dir,
        name="srv",
        package="provider_pkg",
        module_path="pkg.server",
        port=8000,
    )

    config_file = tmp_dir / "config.json"
    config_file.write_text(json.dumps({"servers": {"srv": {}}}))

    with pytest.raises(PortInUseError):
        manager.start_server(config_file, "srv", info)


# ----------------------------------------
# ---------- stop_servers tests ----------
# ----------------------------------------


def test_stop_servers_no_args_stops_all_running_servers(caplog: LogCaptureFixture):
    """
    If no server names and no config file are provided, `stop_servers` should stop
    all currently running servers returned by `state_manager.get_running_servers(validate=True)`,
    and it should not call `_load_servers`.

    Args:
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager._load_servers = MagicMock()
    manager.stop_server = MagicMock()

    running = {
        "a": MagicMock(name="info_a"),
        "b": MagicMock(name="info_b"),
    }
    manager.state_manager.get_running_servers.return_value = running

    caplog.set_level(logging.WARNING)

    manager.stop_servers(server_names=None, config_file=None)

    manager.state_manager.get_running_servers.assert_called_once_with(validate=True)
    manager._load_servers.assert_not_called()

    # Called for each running server
    manager.stop_server.assert_any_call("a", running["a"])
    manager.stop_server.assert_any_call("b", running["b"])
    assert manager.stop_server.call_count == 2

    # No warnings expected
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_stop_servers_with_server_names_filters_and_warns_not_running_no_config(
    caplog: LogCaptureFixture,
):
    """
    If `server_names` is provided without a config file, `stop_servers` should stop only
    servers that are currently running, and it should log a warning for requested
    servers that are not running.

    Args:
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager._load_servers = MagicMock()
    manager.stop_server = MagicMock()

    running = {
        "a": MagicMock(name="info_a"),
        "b": MagicMock(name="info_b"),
    }
    manager.state_manager.get_running_servers.return_value = running

    caplog.set_level(logging.WARNING)

    manager.stop_servers(server_names=["b", "c"], config_file=None)

    # Stops only "b"
    manager.stop_server.assert_called_once_with("b", running["b"])

    # Warns for "c" not running
    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert "Server 'c' is not running" in warnings


def test_stop_servers_with_config_file_limits_allowed_to_configured_and_running():
    """
    If `config_file` is provided, `stop_servers` should only attempt to stop servers that are
    both configured in the config and currently running, even if additional servers are running.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager._load_servers = MagicMock()
    manager.stop_server = MagicMock()

    running = {
        "a": MagicMock(name="info_a"),
        "b": MagicMock(name="info_b"),
        "x": MagicMock(name="info_x"),
    }
    manager.state_manager.get_running_servers.return_value = running

    # Config contains a and x and y (y not running)
    configured = {
        "a": MagicMock(name="cfg_a"),
        "x": MagicMock(name="cfg_x"),
        "y": MagicMock(name="cfg_y"),
    }
    cfg_path = Path("/tmp/config.yaml")
    manager._load_servers.return_value = configured

    manager.stop_servers(server_names=None, config_file=cfg_path)

    manager._load_servers.assert_called_once_with(cfg_path)

    # Allowed servers are intersection of configured keys and running servers: a, x
    manager.stop_server.assert_any_call("a", running["a"])
    manager.stop_server.assert_any_call("x", running["x"])
    assert manager.stop_server.call_count == 2

    # b is running but not configured, should not be stopped
    assert ("b", running["b"]) not in [c.args for c in manager.stop_server.call_args_list]


def test_stop_servers_with_config_and_names_warns_not_in_config_and_not_running(
    caplog: LogCaptureFixture,
):
    """
    If `config_file` and `server_names` are provided, `stop_servers` should:
      - stop servers that are both configured and running,
      - warn if a requested server is configured but not running,
      - warn if a requested server is not present in the config at all.

    Args:
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager._load_servers = MagicMock()
    manager.stop_server = MagicMock()

    running = {
        "a": MagicMock(name="info_a"),
    }
    manager.state_manager.get_running_servers.return_value = running

    # Config has a and b, but b is not running
    configured = {
        "a": MagicMock(name="cfg_a"),
        "b": MagicMock(name="cfg_b"),
    }
    cfg_path = Path("/tmp/config.yaml")
    manager._load_servers.return_value = configured

    caplog.set_level(logging.WARNING)

    manager.stop_servers(server_names=["a", "b", "c"], config_file=cfg_path)

    # Stops only a (running and configured)
    manager.stop_server.assert_called_once_with("a", running["a"])

    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert "Server 'b' is not running" in warnings
    assert "Server 'c' not found in config" in warnings


def test_stop_servers_with_names_ignores_not_allowed_and_stops_allowed_only(
    caplog: LogCaptureFixture,
):
    """
    If `config_file` is provided and `server_names` includes entries not in the config,
    `stop_servers` should not attempt to stop those entries, and it should warn they are not
    found in config (even if they are running).

    Args:
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager._load_servers = MagicMock()
    manager.stop_server = MagicMock()

    running = {
        "a": MagicMock(name="info_a"),
        "b": MagicMock(name="info_b"),
    }
    manager.state_manager.get_running_servers.return_value = running

    # Config only includes b
    configured = {"b": MagicMock(name="cfg_b")}
    cfg_path = Path("/tmp/config.yaml")
    manager._load_servers.return_value = configured

    caplog.set_level(logging.WARNING)

    manager.stop_servers(server_names=["a", "b"], config_file=cfg_path)

    # Only b is allowed (configured+running), so only b is stopped
    manager.stop_server.assert_called_once_with("b", running["b"])

    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert "Server 'a' not found in config" in warnings


def test_stop_servers_logs_error_and_continues_when_stop_server_raises(
    caplog: LogCaptureFixture,
):
    """
    If `stop_server` raises for one server, `stop_servers` should log an error for that server
    and continue attempting to stop the remaining servers.

    Args:
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager._load_servers = MagicMock()
    manager.stop_server = MagicMock()

    running = {
        "a": MagicMock(name="info_a"),
        "b": MagicMock(name="info_b"),
    }
    manager.state_manager.get_running_servers.return_value = running

    def stop_side_effect(name, info):
        if name == "a":
            raise RuntimeError("boom")
        return None

    manager.stop_server.side_effect = stop_side_effect

    caplog.set_level(logging.ERROR)

    manager.stop_servers(server_names=None, config_file=None)

    # Should attempt both servers even if first fails
    assert manager.stop_server.call_count == 2

    errors = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert any("Failed to stop server 'a': boom" in msg for msg in errors)


# ---------------------------------------
# ---------- stop_server tests ----------
# ---------------------------------------


def test_stop_server_no_pid_warns_removes_state_and_returns_false(server_info: ServerInfo, caplog: LogCaptureFixture):
    """
    If ServerInfo.pid is missing/falsey, stop_server should warn, remove the server
    from state anyway, and return False.

    Args:
        server_info (ServerInfo):
            An instance of `ServerInfo` for testing.
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()

    server_info.pid = None

    caplog.set_level(logging.WARNING)

    result = manager.stop_server("myserver", server_info, timeout=10)

    assert result is False
    manager.state_manager.remove_server.assert_called_once_with("myserver")

    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert "Server 'myserver' has no PID recorded" in warnings


def test_stop_server_no_such_process_cleans_state_and_returns_false(
    server_info: ServerInfo,
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
):
    """
    If psutil.Process(pid) raises NoSuchProcess, stop_server should treat it as already stopped,
    remove state, and return False.

    Args:
        server_info (ServerInfo):
            An instance of `ServerInfo` for testing.
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()

    caplog.set_level(logging.INFO)

    def proc_ctor(pid):
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(psutil, "Process", proc_ctor)

    result = manager.stop_server("myserver", server_info, timeout=10)

    assert result is False
    manager.state_manager.remove_server.assert_called_once_with("myserver")

    infos = [r.message for r in caplog.records if r.levelno == logging.INFO]
    assert any("is already stopped" in msg for msg in infos)


def test_stop_server_access_denied_on_process_open_returns_false_no_cleanup(
    server_info: ServerInfo,
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
):
    """
    If psutil.Process(pid) raises AccessDenied, stop_server should log an error and return False,
    and it should not remove server state (per implementation).

    Args:
        server_info (ServerInfo):
            An instance of `ServerInfo` for testing.
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()

    caplog.set_level(logging.ERROR)

    def proc_ctor(pid):
        raise psutil.AccessDenied(pid=pid)

    monkeypatch.setattr(psutil, "Process", proc_ctor)

    result = manager.stop_server("myserver", server_info, timeout=10)

    assert result is False
    manager.state_manager.remove_server.assert_not_called()

    errors = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert any("Access denied when accessing server 'myserver'" in msg for msg in errors)


def test_stop_server_cmdline_safety_check_mismatch_skips_and_cleans_state(
    server_info: ServerInfo,
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
):
    """
    If the process cmdline does not appear to match the server name or package,
    stop_server should warn, remove state, and return False without terminating.

    Args:
        server_info (ServerInfo):
            An instance of `ServerInfo` for testing.
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()

    proc = MagicMock()
    proc.cmdline.return_value = ["python", "-c", "print('not our server')"]

    monkeypatch.setattr(psutil, "Process", lambda pid: proc)

    caplog.set_level(logging.WARNING)

    result = manager.stop_server("myserver", server_info, timeout=10)

    assert result is False
    manager.state_manager.remove_server.assert_called_once_with("myserver")
    proc.terminate.assert_not_called()

    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("doesn't appear to be server 'myserver'" in msg for msg in warnings)


def test_stop_server_cmdline_access_denied_is_ignored_and_still_terminates(
    server_info: ServerInfo,
    monkeypatch: MonkeyPatch,
):
    """
    If cmdline() raises AccessDenied/NoSuchProcess, the safety check is skipped (pass),
    and stop_server should proceed to terminate the process.

    Args:
        server_info (ServerInfo):
            An instance of `ServerInfo` for testing.
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()

    proc = MagicMock()
    proc.cmdline.side_effect = psutil.AccessDenied(pid=server_info.pid)
    proc.wait.return_value = None  # graceful exit

    monkeypatch.setattr(psutil, "Process", lambda pid: proc)

    result = manager.stop_server("myserver", server_info, timeout=10)

    assert result is True
    proc.terminate.assert_called_once()
    proc.wait.assert_called_once_with(timeout=10)
    manager.state_manager.remove_server.assert_called_once_with("myserver")


def test_stop_server_graceful_shutdown_success_removes_state_returns_true(
    server_info: ServerInfo, monkeypatch: MonkeyPatch, caplog: LogCaptureFixture
):
    """
    On a normal graceful shutdown path, stop_server should terminate(), wait(),
    remove state, and return True.

    Args:
        server_info (ServerInfo):
            An instance of `ServerInfo` for testing.
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()

    proc = MagicMock()
    proc.cmdline.return_value = [
        "python",
        "-m",
        server_info.module_path,
        "--config",
        "x",
    ]
    proc.wait.return_value = None

    monkeypatch.setattr(psutil, "Process", lambda pid: proc)

    caplog.set_level(logging.INFO)

    result = manager.stop_server("myserver", server_info, timeout=7)

    assert result is True
    proc.terminate.assert_called_once()
    proc.wait.assert_called_once_with(timeout=7)
    manager.state_manager.remove_server.assert_called_once_with("myserver")

    infos = [r.message for r in caplog.records if r.levelno == logging.INFO]
    assert any("stopped gracefully" in msg for msg in infos)


def test_stop_server_timeout_then_force_kill_children_and_parent(
    server_info: ServerInfo,
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
):
    """
    If graceful wait times out, stop_server should warn and then attempt a force stop:
    kill children first, then kill parent, wait briefly, remove state, return True.

    Args:
        server_info (ServerInfo):
            An instance of `ServerInfo` for testing.
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()

    # First Process(pid) instance used for terminate + wait(timeout=timeout)
    proc_for_term = MagicMock()
    proc_for_term.cmdline.return_value = ["python", "-m", server_info.module_path]
    proc_for_term.wait.side_effect = psutil.TimeoutExpired(10)

    # Second Process(pid) instance used as "parent" in force-kill path
    child1 = MagicMock()
    child1.pid = 111
    child2 = MagicMock()
    child2.pid = 222

    parent = MagicMock()
    parent.children.return_value = [child1, child2]
    parent.wait.return_value = None

    # psutil.Process called multiple times, return proc_for_term first, then parent
    proc_calls = {"n": 0}

    def proc_ctor(pid):
        proc_calls["n"] += 1
        return proc_for_term if proc_calls["n"] == 1 else parent

    monkeypatch.setattr(psutil, "Process", proc_ctor)

    caplog.set_level(logging.WARNING)

    result = manager.stop_server("myserver", server_info, timeout=10)

    assert result is True
    proc_for_term.terminate.assert_called_once()
    proc_for_term.wait.assert_called_once_with(timeout=10)

    # Force kill path
    child1.kill.assert_called_once()
    child2.kill.assert_called_once()
    parent.kill.assert_called_once()
    parent.wait.assert_called_once_with(timeout=2)

    manager.state_manager.remove_server.assert_called_once_with("myserver")

    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("did not stop gracefully" in msg for msg in warnings)


def test_stop_server_timeout_force_kill_no_such_process_still_cleans_state_returns_true(
    server_info: ServerInfo,
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
):
    """
    If graceful wait times out and then the force-kill section finds the process already gone
    (psutil.NoSuchProcess), stop_server should log, remove state, and return True.

    Args:
        server_info (ServerInfo):
            An instance of `ServerInfo` for testing.
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()

    proc_for_term = MagicMock()
    proc_for_term.cmdline.return_value = ["python", "-m", server_info.module_path]
    proc_for_term.wait.side_effect = psutil.TimeoutExpired(10)

    proc_calls = {"n": 0}

    def proc_ctor(pid):
        proc_calls["n"] += 1
        if proc_calls["n"] == 1:
            return proc_for_term
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(psutil, "Process", proc_ctor)

    caplog.set_level(logging.INFO)

    result = manager.stop_server("myserver", server_info, timeout=10)

    assert result is True
    manager.state_manager.remove_server.assert_called_once_with("myserver")

    infos = [r.message for r in caplog.records if r.levelno == logging.INFO]
    assert any("process terminated" in msg for msg in infos)


def test_stop_server_no_such_process_during_terminate_cleans_state_returns_true(
    server_info: ServerInfo,
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
):
    """
    If the process disappears during terminate/wait (outer try catches NoSuchProcess),
    stop_server should remove state and return True.

    Args:
        server_info (ServerInfo):
            An instance of `ServerInfo` for testing.
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()

    proc = MagicMock()
    proc.cmdline.return_value = ["python", "-m", server_info.module_path]
    proc.terminate.side_effect = psutil.NoSuchProcess(server_info.pid)

    monkeypatch.setattr(psutil, "Process", lambda pid: proc)

    caplog.set_level(logging.INFO)

    result = manager.stop_server("myserver", server_info, timeout=10)

    assert result is True
    manager.state_manager.remove_server.assert_called_once_with("myserver")

    infos = [r.message for r in caplog.records if r.levelno == logging.INFO]
    assert any("process already terminated" in msg for msg in infos)


def test_stop_server_access_denied_during_terminate_returns_false_no_cleanup(
    server_info: ServerInfo,
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
):
    """
    If terminate/wait raises AccessDenied (outer try catches AccessDenied),
    stop_server should log an error and return False, and it should not remove state.

    Args:
        server_info (ServerInfo):
            An instance of `ServerInfo` for testing.
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()

    proc = MagicMock()
    proc.cmdline.return_value = ["python", "-m", server_info.module_path]
    proc.terminate.side_effect = psutil.AccessDenied(pid=server_info.pid)

    monkeypatch.setattr(psutil, "Process", lambda pid: proc)

    caplog.set_level(logging.ERROR)

    result = manager.stop_server("myserver", server_info, timeout=10)

    assert result is False
    manager.state_manager.remove_server.assert_not_called()

    errors = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert any("Permission denied when trying to stop server 'myserver'" in msg for msg in errors)


def test_stop_server_unexpected_exception_returns_false_no_cleanup(
    server_info: ServerInfo,
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
):
    """
    If an unexpected exception occurs during shutdown, stop_server should log an error,
    return False, and leave state untouched (per implementation).

    Args:
        server_info (ServerInfo):
            An instance of `ServerInfo` for testing.
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()

    proc = MagicMock()
    proc.cmdline.return_value = ["python", "-m", server_info.module_path]
    proc.terminate.side_effect = RuntimeError("unexpected")

    monkeypatch.setattr(psutil, "Process", lambda pid: proc)

    caplog.set_level(logging.ERROR)

    result = manager.stop_server("myserver", server_info, timeout=10)

    assert result is False
    manager.state_manager.remove_server.assert_not_called()

    errors = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert any("Error stopping server 'myserver': unexpected" in msg for msg in errors)


# -------------------------------------------
# ---------- restart_servers tests ----------
# -------------------------------------------


def test_restart_servers_restarts_all_configured_when_no_names():
    """
    If server_names is None, restart_servers should restart all servers returned by _load_servers,
    using the config order (dict insertion order).
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager._load_servers = MagicMock()
    manager.restart_server = MagicMock()

    cfg = Path("/tmp/servers.json")
    servers = {
        "a": types.SimpleNamespace(),
        "b": types.SimpleNamespace(),
    }
    manager._load_servers.return_value = servers

    manager.restart_servers(cfg, server_names=None)

    manager._load_servers.assert_called_once_with(cfg)

    expected_calls = [
        (cfg, "a", servers["a"]),
        (cfg, "b", servers["b"]),
    ]
    assert [c.args for c in manager.restart_server.call_args_list] == expected_calls


def test_restart_servers_restarts_only_requested_in_order():
    """
    If server_names is provided, restart_servers should restart only those servers,
    in the order given by server_names.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager._load_servers = MagicMock()
    manager.restart_server = MagicMock()

    cfg = Path("/tmp/servers.json")
    servers = {
        "a": types.SimpleNamespace(),
        "b": types.SimpleNamespace(),
        "c": types.SimpleNamespace(),
    }
    manager._load_servers.return_value = servers

    manager.restart_servers(cfg, server_names=["c", "a"])

    expected_calls = [
        (cfg, "c", servers["c"]),
        (cfg, "a", servers["a"]),
    ]
    assert [c.args for c in manager.restart_server.call_args_list] == expected_calls


def test_restart_servers_unknown_name_raises_value_error_and_does_not_restart_any():
    """
    If any requested server name is not present in the loaded config, restart_servers should
    raise ValueError and should not call restart_server at all.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager._load_servers = MagicMock()
    manager.restart_server = MagicMock()

    cfg = Path("/tmp/servers.json")
    servers = {"a": types.SimpleNamespace()}
    manager._load_servers.return_value = servers

    with pytest.raises(ValueError, match=r"Unknown server: b"):
        manager.restart_servers(cfg, server_names=["a", "b"])

    manager.restart_server.assert_not_called()


def test_restart_servers_logs_error_and_continues_on_restart_exception(
    caplog: LogCaptureFixture,
):
    """
    If restart_server raises for a server, restart_servers should log an error and continue
    restarting the remaining servers.

    Args:
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager._load_servers = MagicMock()
    manager.restart_server = MagicMock()

    cfg = Path("/tmp/servers.json")
    servers = {
        "a": types.SimpleNamespace(),
        "b": types.SimpleNamespace(),
    }
    manager._load_servers.return_value = servers

    def side_effect(config_file, name, info):
        if name == "a":
            raise RuntimeError("boom")
        return None

    manager.restart_server.side_effect = side_effect

    caplog.set_level(logging.ERROR)

    manager.restart_servers(cfg, server_names=None)

    # Both attempted
    assert manager.restart_server.call_count == 2
    assert [c.args[1] for c in manager.restart_server.call_args_list] == ["a", "b"]

    errors = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert any("Failed to restart server 'a': boom" in msg for msg in errors)


# ------------------------------------------
# ---------- restart_server tests ----------
# ------------------------------------------


def test_restart_server_stops_running_server_then_starts_with_config(
    caplog: LogCaptureFixture,
):
    """
    If the server is running (state_manager.get_server returns an object with a pid),
    restart_server should call stop_server with the running instance, then call start_server
    with the config-derived server_info.

    Args:
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager.stop_server = MagicMock()
    manager.start_server = MagicMock()

    cfg = Path("/tmp/servers.json")
    config_info = types.SimpleNamespace(pid=None, package="pkg.from.config")
    running_info = types.SimpleNamespace(pid=123, package="pkg.running")

    manager.state_manager.get_server.return_value = running_info
    manager.stop_server.return_value = True

    caplog.set_level(logging.INFO)

    manager.restart_server(cfg, "myserver", config_info)

    manager.state_manager.get_server.assert_called_once_with("myserver")
    manager.stop_server.assert_called_once_with("myserver", running_info)
    manager.start_server.assert_called_once_with(cfg, "myserver", config_info)

    infos = [r.message for r in caplog.records if r.levelno == logging.INFO]
    assert any("Restarting server 'myserver'" in msg for msg in infos)
    assert any("stopped, starting fresh" in msg for msg in infos)
    assert any("restarted successfully" in msg for msg in infos)


def test_restart_server_if_stop_returns_false_logs_warning_and_starts_anyway(
    caplog: LogCaptureFixture,
):
    """
    If stop_server returns False for a running server, restart_server should log a warning
    and still call start_server.

    Args:
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager.stop_server = MagicMock()
    manager.start_server = MagicMock()

    cfg = Path("/tmp/servers.json")
    config_info = types.SimpleNamespace(pid=None, package="pkg.from.config")
    running_info = types.SimpleNamespace(pid=123, package="pkg.running")

    manager.state_manager.get_server.return_value = running_info
    manager.stop_server.return_value = False

    caplog.set_level(logging.WARNING)

    manager.restart_server(cfg, "myserver", config_info)

    manager.stop_server.assert_called_once_with("myserver", running_info)
    manager.start_server.assert_called_once_with(cfg, "myserver", config_info)

    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Failed to stop server 'myserver', attempting to start anyway" in msg for msg in warnings)


def test_restart_server_when_not_running_starts_without_stopping(
    caplog: LogCaptureFixture,
):
    """
    If state_manager.get_server returns None, restart_server should not call stop_server,
    and should call start_server directly.

    Args:
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager.stop_server = MagicMock()
    manager.start_server = MagicMock()

    cfg = Path("/tmp/servers.json")
    config_info = types.SimpleNamespace(pid=None, package="pkg.from.config")

    manager.state_manager.get_server.return_value = None

    caplog.set_level(logging.INFO)

    manager.restart_server(cfg, "myserver", config_info)

    manager.stop_server.assert_not_called()
    manager.start_server.assert_called_once_with(cfg, "myserver", config_info)

    infos = [r.message for r in caplog.records if r.levelno == logging.INFO]
    assert any("is not running, starting fresh" in msg for msg in infos)


def test_restart_server_when_state_has_no_pid_starts_without_stopping(
    caplog: LogCaptureFixture,
):
    """
    If state_manager.get_server returns an object but pid is falsey, restart_server should
    treat it as not running, skip stop_server, and call start_server.

    Args:
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager.stop_server = MagicMock()
    manager.start_server = MagicMock()

    cfg = Path("/tmp/servers.json")
    config_info = types.SimpleNamespace(pid=None, package="pkg.from.config")
    running_info = types.SimpleNamespace(pid=None, package="pkg.running")

    manager.state_manager.get_server.return_value = running_info

    caplog.set_level(logging.INFO)

    manager.restart_server(cfg, "myserver", config_info)

    manager.stop_server.assert_not_called()
    manager.start_server.assert_called_once_with(cfg, "myserver", config_info)

    infos = [r.message for r in caplog.records if r.levelno == logging.INFO]
    assert any("is not running, starting fresh" in msg for msg in infos)


def test_restart_server_propagates_start_server_exception():
    """
    If start_server raises, restart_server should not swallow the exception.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager.stop_server = MagicMock()
    manager.start_server = MagicMock()

    cfg = Path("/tmp/servers.json")
    config_info = types.SimpleNamespace(pid=None, package="pkg.from.config")
    running_info = types.SimpleNamespace(pid=123, package="pkg.running")

    manager.state_manager.get_server.return_value = running_info
    manager.stop_server.return_value = True
    manager.start_server.side_effect = RuntimeError("start failed")

    with pytest.raises(RuntimeError, match="start failed"):
        manager.restart_server(cfg, "myserver", config_info)

    manager.stop_server.assert_called_once_with("myserver", running_info)
    manager.start_server.assert_called_once_with(cfg, "myserver", config_info)


def test_restart_server_propagates_stop_server_exception_and_does_not_start():
    """
    If stop_server raises, restart_server should propagate the exception and should not
    proceed to start_server.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager.stop_server = MagicMock()
    manager.start_server = MagicMock()

    cfg = Path("/tmp/servers.json")
    config_info = types.SimpleNamespace(pid=None, package="pkg.from.config")
    running_info = types.SimpleNamespace(pid=123, package="pkg.running")

    manager.state_manager.get_server.return_value = running_info
    manager.stop_server.side_effect = RuntimeError("stop failed")

    with pytest.raises(RuntimeError, match="stop failed"):
        manager.restart_server(cfg, "myserver", config_info)

    manager.start_server.assert_not_called()


# -----------------------------------------------
# ---------- get_server_statuses tests ----------
# -----------------------------------------------


def test_get_server_statuses_with_config_file_returns_all_config_servers_when_no_filter():
    """
    If config_file is provided and server_names is None/empty, get_server_statuses should load servers
    from config and return statuses for all keys from that config.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager._load_servers = MagicMock()

    cfg = Path("/tmp/servers.json")
    servers = {"a": types.SimpleNamespace(pid=1), "b": types.SimpleNamespace(pid=None)}
    manager._load_servers.return_value = servers

    result = manager.get_server_statuses(server_names=None, config_file=cfg)

    manager._load_servers.assert_called_once_with(cfg)
    manager.state_manager.get_servers.assert_not_called()
    assert result == servers


def test_get_server_statuses_without_config_uses_state_manager_validate_true():
    """
    If config_file is not provided, get_server_statuses should use state_manager.get_servers(validate=True)
    and return all servers when no filter is provided.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager._load_servers = MagicMock()

    servers = {"a": types.SimpleNamespace(pid=1), "b": types.SimpleNamespace(pid=None)}
    manager.state_manager.get_servers.return_value = servers

    result = manager.get_server_statuses(server_names=None, config_file=None)

    manager.state_manager.get_servers.assert_called_once_with(validate=True)
    manager._load_servers.assert_not_called()
    assert result == servers


def test_get_server_statuses_with_filter_keeps_only_present_names_config_file_warns_and_mutates_list(
    caplog: LogCaptureFixture,
):
    """
    If server_names is provided and some names are missing from the loaded config, get_server_statuses should:
      - log a warning for each missing name,
      - remove missing names from the provided server_names list (in-place),
      - return only statuses for the remaining names.

    Args:
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager._load_servers = MagicMock()

    cfg = Path("/tmp/servers.json")
    servers = {"a": types.SimpleNamespace(pid=1), "b": types.SimpleNamespace(pid=None)}
    manager._load_servers.return_value = servers

    names = ["a", "missing", "b"]

    caplog.set_level(logging.WARNING)
    result = manager.get_server_statuses(server_names=names, config_file=cfg)

    assert result == {"a": servers["a"], "b": servers["b"]}

    # The method removes missing names from the filter list in-place.
    assert names == ["a", "b"]

    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Server 'missing' not found in config" in msg for msg in warnings)
    assert any("Removing this server from the filter" in msg for msg in warnings)


def test_get_server_statuses_with_filter_keeps_only_present_names_state_warns_and_mutates_list(
    caplog: LogCaptureFixture,
):
    """
    If server_names is provided without config_file and some names are missing from state_manager.get_servers,
    get_server_statuses should warn, remove missing names from server_names in-place, and return only present ones.

    Args:
        caplog (LogCaptureFixture):
            Pytest caplog fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager._load_servers = MagicMock()

    servers = {"a": types.SimpleNamespace(pid=1)}
    manager.state_manager.get_servers.return_value = servers

    names = ["missing", "a"]

    caplog.set_level(logging.WARNING)
    result = manager.get_server_statuses(server_names=names, config_file=None)

    assert result == {"a": servers["a"]}
    assert names == ["a"]

    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Server 'missing' not found by state manager" in msg for msg in warnings)
    assert any("Removing this server from the filter" in msg for msg in warnings)


def test_get_server_statuses_empty_filter_treated_as_no_filter_returns_all():
    """
    If server_names is an empty list, it is falsey, so get_server_statuses should treat it like no filter
    and return all servers.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager._load_servers = MagicMock()

    servers = {"a": types.SimpleNamespace(pid=1), "b": types.SimpleNamespace(pid=2)}
    manager.state_manager.get_servers.return_value = servers

    result = manager.get_server_statuses(server_names=[], config_file=None)

    assert result == servers


def test_get_server_statuses_returns_dict_with_same_objects_not_copies():
    """
    get_server_statuses should return the exact ServerInfo objects stored in the underlying servers mapping,
    not copies.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager._load_servers = MagicMock()

    a = types.SimpleNamespace(pid=1)
    servers = {"a": a}
    manager.state_manager.get_servers.return_value = servers

    result = manager.get_server_statuses(server_names=["a"], config_file=None)

    assert result["a"] is a


# -------------------------------------------------
# ---------- print_server_statuses tests ----------
# -------------------------------------------------


def _fake_status(value: str):
    """
    Create a minimal status object with a .value attribute, compatible with the method.

    Args:
        value (str):
            Fake status arg.
    """
    return types.SimpleNamespace(value=value)


def test_print_server_statuses_prints_no_servers_found_and_returns_early(
    capsys: LogCaptureFixture,
):
    """
    If get_server_statuses returns an empty mapping, print_server_statuses should print
    the no servers message and return without creating a table.

    Args:
        capsys (LogCaptureFixture):
            Pytest capsys fixture.
    """
    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager.get_server_statuses = MagicMock()

    manager.get_server_statuses.return_value = {}

    manager.print_server_statuses(server_names=None, config_file=None)

    out = capsys.readouterr().out
    assert "\nNo servers found." in out
    manager.get_server_statuses.assert_called_once_with(server_names=None, config_file=None)


def test_print_server_statuses_calls_get_server_statuses_with_args(
    monkeypatch: MonkeyPatch,
):
    """
    print_server_statuses should pass through server_names and config_file to get_server_statuses.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
    """
    import mada_tools.server_management.server_manager as sm

    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager.get_server_statuses = MagicMock()

    class FakeConsole:
        def print(self, *args, **kwargs):
            pass

    class FakeTable:
        def __init__(self, *args, **kwargs):
            pass

        def add_column(self, *args, **kwargs):
            pass

        def add_row(self, *args, **kwargs):
            pass

    monkeypatch.setattr(sm, "Console", FakeConsole)
    monkeypatch.setattr(sm, "Table", FakeTable)

    manager.get_server_statuses.return_value = {
        "a": types.SimpleNamespace(pid=None, host="h", port=None, status=_fake_status("stopped"))
    }

    cfg = Path("/tmp/servers.json")
    names = ["a"]

    manager.print_server_statuses(server_names=names, config_file=cfg)

    manager.get_server_statuses.assert_called_once_with(server_names=names, config_file=cfg)


def test_print_server_statuses_builds_table_columns_and_rows_with_expected_fields(
    monkeypatch: MonkeyPatch,
):
    """
    print_server_statuses should create a table with the expected columns, then add one row per
    status entry using computed PID and Host:Port display values.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
    """
    from mada_tools.server_management import server_manager as sm

    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager.get_server_statuses = MagicMock()

    created = {}

    class FakeConsole:
        def __init__(self):
            created["console"] = self
            self.print_calls = []

        def print(self, *args, **kwargs):
            self.print_calls.append((args, kwargs))

    class FakeTable:
        def __init__(self, *args, **kwargs):
            created["table_args"] = (args, kwargs)
            created["columns"] = []
            created["rows"] = []

        def add_column(self, *args, **kwargs):
            created["columns"].append((args, kwargs))

        def add_row(self, *args, **kwargs):
            created["rows"].append((args, kwargs))

    monkeypatch.setattr(sm, "Console", FakeConsole)
    monkeypatch.setattr(sm, "Table", FakeTable)

    manager.get_server_statuses.return_value = {
        "srv1": types.SimpleNamespace(pid=123, host="127.0.0.1", port=8000, status=_fake_status("running")),
        "srv2": types.SimpleNamespace(pid=None, host="localhost", port=None, status=_fake_status("stopped")),
    }

    manager.print_server_statuses(server_names=None, config_file=None)

    # Table config
    _args, kwargs = created["table_args"]
    assert kwargs["title"] == "MCP Server Status"
    assert kwargs["show_header"] is True
    assert kwargs["header_style"] == "bold magenta"

    # Columns
    col_names = [c[0][0] for c in created["columns"]]
    assert col_names == ["Server Name", "Status", "PID", "Host:Port"]

    # Rows: pid and host:port formatting
    rows = [r[0] for r in created["rows"]]
    assert rows[0][0] == "srv1"
    assert rows[0][2] == "123"
    assert rows[0][3] == "127.0.0.1:8000"

    assert rows[1][0] == "srv2"
    assert rows[1][2] == "N/A"
    assert rows[1][3] == "N/A"

    # console.print called 3 times: blank line, table, blank line
    assert len(created["console"].print_calls) == 3
    assert created["console"].print_calls[1][0][0].__class__ is FakeTable


def test_print_server_statuses_applies_status_styles_for_known_states(
    monkeypatch: MonkeyPatch,
):
    """
    For known ServerStatus values, print_server_statuses should wrap the uppercased status
    in the expected rich markup.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
    """
    from mada_tools.server_management import server_manager as sm

    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager.get_server_statuses = MagicMock()

    # Provide a controllable ServerStatus object in the module namespace
    class _S:
        def __init__(self, value):
            self.value = value

    class FakeServerStatus:
        RUNNING = _S("running")
        STOPPED = _S("stopped")
        STARTING = _S("starting")
        UNHEALTHY = _S("unhealthy")
        FAILED = _S("failed")

    created = {"rows": []}

    class FakeConsole:
        def print(self, *args, **kwargs):
            pass

    class FakeTable:
        def __init__(self, *args, **kwargs):
            pass

        def add_column(self, *args, **kwargs):
            pass

        def add_row(self, *args, **kwargs):
            created["rows"].append(args)

    monkeypatch.setattr(sm, "Console", FakeConsole)
    monkeypatch.setattr(sm, "Table", FakeTable)
    monkeypatch.setattr(sm, "ServerStatus", FakeServerStatus)

    manager.get_server_statuses.return_value = {
        "r": types.SimpleNamespace(pid=1, host="h", port=1, status=FakeServerStatus.RUNNING),
        "s": types.SimpleNamespace(pid=None, host="h", port=None, status=FakeServerStatus.STOPPED),
        "st": types.SimpleNamespace(pid=None, host="h", port=None, status=FakeServerStatus.STARTING),
        "u": types.SimpleNamespace(pid=None, host="h", port=None, status=FakeServerStatus.UNHEALTHY),
        "f": types.SimpleNamespace(pid=None, host="h", port=None, status=FakeServerStatus.FAILED),
    }

    manager.print_server_statuses(server_names=None, config_file=None)

    # Extract the "Status" cell from each add_row call
    status_cells = {row[0]: row[1] for row in created["rows"]}

    assert status_cells["r"] == "[green]RUNNING[/green]"
    assert status_cells["s"] == "[dim]STOPPED[/dim]"
    assert status_cells["st"] == "[yellow]STARTING[/yellow]"
    assert status_cells["u"] == "[red]UNHEALTHY[/red]"
    assert status_cells["f"] == "[bold red]FAILED[/bold red]"


def test_print_server_statuses_unknown_status_has_no_markup(monkeypatch: MonkeyPatch):
    """
    If the status is not equal to any known ServerStatus constant, print_server_statuses should
    display the uppercased status value without markup.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
    """
    from mada_tools.server_management import server_manager as sm

    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager.get_server_statuses = MagicMock()

    class FakeConsole:
        def print(self, *args, **kwargs):
            pass

    created = {"rows": []}

    class FakeTable:
        def __init__(self, *args, **kwargs):
            pass

        def add_column(self, *args, **kwargs):
            pass

        def add_row(self, *args, **kwargs):
            created["rows"].append(args)

    # Make ServerStatus comparisons always fail by providing sentinel objects
    class FakeServerStatus:
        RUNNING = object()
        STOPPED = object()
        STARTING = object()
        UNHEALTHY = object()
        FAILED = object()

    monkeypatch.setattr(sm, "Console", FakeConsole)
    monkeypatch.setattr(sm, "Table", FakeTable)
    monkeypatch.setattr(sm, "ServerStatus", FakeServerStatus)

    manager.get_server_statuses.return_value = {
        "x": types.SimpleNamespace(pid=None, host="h", port=None, status=_fake_status("mystery")),
    }

    manager.print_server_statuses(server_names=None, config_file=None)

    assert created["rows"][0][1] == "MYSTERY"


def test_print_server_statuses_pid_zero_treated_as_na(monkeypatch: MonkeyPatch):
    """
    pid is checked as a truthy value, so pid=0 should be displayed as N/A.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
    """
    from mada_tools.server_management import server_manager as sm

    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager.get_server_statuses = MagicMock()

    created = {"rows": []}

    class FakeConsole:
        def print(self, *args, **kwargs):
            pass

    class FakeTable:
        def __init__(self, *args, **kwargs):
            pass

        def add_column(self, *args, **kwargs):
            pass

        def add_row(self, *args, **kwargs):
            created["rows"].append(args)

    monkeypatch.setattr(sm, "Console", FakeConsole)
    monkeypatch.setattr(sm, "Table", FakeTable)

    manager.get_server_statuses.return_value = {
        "srv": types.SimpleNamespace(pid=0, host="h", port=1234, status=_fake_status("running")),
    }

    manager.print_server_statuses(server_names=None, config_file=None)

    assert created["rows"][0][2] == "N/A"


def test_print_server_statuses_port_zero_treated_as_na(monkeypatch: MonkeyPatch):
    """
    port is checked as a truthy value, so port=0 should be displayed as N/A.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest monkeypatch fixture.
    """
    from mada_tools.server_management import server_manager as sm

    manager = ServerManager(state_file=None)
    manager.state_manager = MagicMock()
    manager.get_server_statuses = MagicMock()

    created = {"rows": []}

    class FakeConsole:
        def print(self, *args, **kwargs):
            pass

    class FakeTable:
        def __init__(self, *args, **kwargs):
            pass

        def add_column(self, *args, **kwargs):
            pass

        def add_row(self, *args, **kwargs):
            created["rows"].append(args)

    monkeypatch.setattr(sm, "Console", FakeConsole)
    monkeypatch.setattr(sm, "Table", FakeTable)

    manager.get_server_statuses.return_value = {
        "srv": types.SimpleNamespace(pid=1, host="h", port=0, status=_fake_status("running")),
    }

    manager.print_server_statuses(server_names=None, config_file=None)

    assert created["rows"][0][3] == "N/A"
