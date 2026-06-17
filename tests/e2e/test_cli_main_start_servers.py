# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
End-to-end tests for the mada-tools CLI start-servers flow.

These tests exercise the real CLI entrypoint through main(), including
argument parsing, command registration, command dispatch, and server
management interactions with persisted state.

Almost everything is unpatched here. The code that's still patched is:
- logging to avoid noisy output
- server discovery since we're not starting any real servers here
- subprocess.Popen to avoid launching real processes
- time.sleep to keep tests fast
- port checking since we're not actually starting anything
"""

import json
import sys
from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch

from mada_tools.main import main
from mada_tools.server_management import ServerStatus


class DummyProcess:
    """
    Fake subprocess process used to simulate a successfully running server
    during CLI end-to-end tests.
    """

    def __init__(self, pid=4321, poll_result=None):
        """
        Initialize the fake process.

        Args:
            pid: Fake process identifier.
            poll_result: Value returned by poll(), where None means running.
        """
        self.pid = pid
        self._poll_result = poll_result

    def poll(self):
        """
        Return the configured poll state.

        Returns:
            The configured poll result.
        """
        return self._poll_result


def test_main_start_servers_starts_configured_server_and_exits_successfully(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    config_file: Path,
    state_file: Path,
):
    """
    End-to-end test, verify the CLI start-servers command parses arguments,
    starts the configured server through the real command and manager flow,
    persists server state, and exits successfully.

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
        "mada_tools.server_management.server_manager.subprocess.Popen",
        lambda *args, **kwargs: DummyProcess(pid=4321, poll_result=None),
    )

    port_check_calls = {"count": 0}

    def fake_is_port_in_use(self, host, port):
        port_check_calls["count"] += 1
        if port_check_calls["count"] == 1:
            return False
        return True

    monkeypatch.setattr(
        "mada_tools.server_management.state_manager.ServerStateManager._is_port_in_use",
        fake_is_port_in_use,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "start-servers",
            str(config_file),
            "--state-file",
            str(state_file),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code in (None, 0)

    state = json.loads(state_file.read_text())
    assert "alpha" in state["servers"]
    assert state["servers"]["alpha"]["pid"] == 4321
    assert state["servers"]["alpha"]["status"] == ServerStatus.RUNNING.value


def test_main_start_servers_with_specific_server_name_only_starts_requested_server(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    config_file: Path,
    state_file: Path,
):
    """
    End-to-end test, verify the CLI start-servers command starts only the
    explicitly requested server when multiple servers exist in the config.

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

    launched = []

    def fake_popen(cmd, stdout, stderr, env, start_new_session):
        launched.append(cmd)
        return DummyProcess(pid=5001, poll_result=None)

    monkeypatch.setattr(
        "mada_tools.server_management.server_manager.subprocess.Popen",
        fake_popen,
    )

    port_check_calls = {"count": 0}

    def fake_is_port_in_use(self, host, port):
        port_check_calls["count"] += 1
        if port_check_calls["count"] == 1:
            return False
        return True

    monkeypatch.setattr(
        "mada_tools.server_management.state_manager.ServerStateManager._is_port_in_use",
        fake_is_port_in_use,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "start-servers",
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
    assert len(launched) == 1
    assert "fake_pkg.alpha.server" in launched[0]

    state = json.loads(state_file.read_text())
    assert set(state["servers"].keys()) == {"alpha"}


def test_main_start_servers_exits_with_error_for_unknown_server(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    config_file: Path,
    state_file: Path,
):
    """
    End-to-end test, verify the CLI exits with status code 1 when the user
    requests a server name that does not exist in the loaded configuration.

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
        sys,
        "argv",
        [
            "mada-tools",
            "start-servers",
            str(config_file),
            "--servers",
            "does-not-exist",
            "--state-file",
            str(state_file),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1


def test_main_start_servers_exits_with_error_when_port_is_already_in_use(
    monkeypatch: MonkeyPatch,
    patch_cli_dependencies: None,  # This fixture just patches logging and sleep commands
    config_file: Path,
    state_file: Path,
):
    """
    End-to-end test, verify the CLI exits with status code 1 when a configured
    server cannot start because its target port is already in use.

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
        "mada_tools.server_management.state_manager.ServerStateManager._is_port_in_use",
        lambda self, host, port: True,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mada-tools",
            "start-servers",
            str(config_file),
            "--state-file",
            str(state_file),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
