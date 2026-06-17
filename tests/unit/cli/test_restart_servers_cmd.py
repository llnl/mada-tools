# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Tests for the `restart_servers.py` module.
"""

from argparse import Namespace
from pathlib import Path
from typing import Callable

import pytest
from _pytest.monkeypatch import MonkeyPatch

from mada_tools.cli.commands.restart_servers import RestartServersCmd


@pytest.fixture
def restart_cmd() -> RestartServersCmd:
    """
    Fixture to provide an instance of the RestartServersCmd for tests.

    Returns:
        An instance of the `RestartServersCmd` class.
    """
    return RestartServersCmd()


def test_add_parser_registers_subcommand(create_parser: Callable, restart_cmd: RestartServersCmd):
    """
    Verify that the `restart-servers` subcommand is correctly registered
    and that the arguments are wired as expected.

    Args:
        create_parser (Callable):
            A function that creates a parser.
        restart_cmd (RestartServersCmd):
            The class used for setting up the command to restart the servers.
    """
    parser = create_parser(restart_cmd)

    # Minimal required arg: config
    args = parser.parse_args(["restart-servers", "config.json"])

    assert args.main_command == "restart-servers"
    # ensure the handler function is set
    assert hasattr(args, "func")
    assert callable(args.func)
    # config should be converted to Path
    assert isinstance(args.config, Path)
    assert args.config.name == "config.json"
    # servers is optional; should default to None if not provided
    assert args.servers is None
    # state_file should have a default
    assert isinstance(args.state_file, Path)


def test_add_parser_parses_servers_and_state_file(
    create_parser: Callable,
    restart_cmd: RestartServersCmd,
    cli_testing_dir: Path,
):
    """
    Verify that the optional servers and state-file arguments are parsed correctly.

    Args:
        create_parser (Callable):
            A function that creates a parser.
        restart_cmd (RestartServersCmd):
            The class used for setting up the command to restart the servers.
        cli_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the `cli` directory.
    """
    parser = create_parser(restart_cmd)
    state_file_path = Path(cli_testing_dir) / "custom_state.json"

    args = parser.parse_args(
        [
            "restart-servers",
            "config.json",
            "-s",
            "server1",
            "server2",
            "--state-file",
            str(state_file_path),
        ]
    )

    assert args.main_command == "restart-servers"
    assert args.servers == ["server1", "server2"]
    assert args.state_file == state_file_path


def test_process_command_calls_server_manager(monkeypatch: MonkeyPatch, cli_testing_dir: Path):
    """
    Verify that `process_command` instantiates `ServerManager` with the expected
    `state_file` and calls `restart_servers` with the correct arguments.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest's monkeypatch fixture.
        cli_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the `cli` directory.
    """

    created_instances = []

    class FakeServerManager:
        def __init__(self, state_file: Path):
            self.state_file = state_file
            self.restart_called_with = None
            created_instances.append(self)

        def restart_servers(self, config_file: Path, server_names):
            self.restart_called_with = (config_file, server_names)

    # Patch the symbol that RestartServersCmd actually uses
    import mada_tools.cli.commands.restart_servers as restart_mod

    monkeypatch.setattr(restart_mod, "ServerManager", FakeServerManager)

    cmd = RestartServersCmd()

    config_path = Path(cli_testing_dir) / "config.json"
    state_file_path = Path(cli_testing_dir) / "state.json"
    servers = ["one", "two"]

    args = Namespace(
        config=config_path,
        state_file=state_file_path,
        servers=servers,
    )

    cmd.process_command(args)

    # Exactly one ServerManager instance created
    assert len(created_instances) == 1
    mgr = created_instances[0]

    # Check constructor argument
    assert mgr.state_file == state_file_path

    # Check restart_servers call
    assert mgr.restart_called_with is not None
    called_config, called_servers = mgr.restart_called_with
    assert called_config == config_path
    assert called_servers == servers


def test_process_command_all_servers(monkeypatch: MonkeyPatch, cli_testing_dir: Path):
    """
    Verify that when servers is None, `process_command` passes None through
    to `ServerManager.restart_servers` (indicating restart all servers).

    Args:
        monkeypatch (MonkeyPatch):
            Pytest's monkeypatch fixture.
        cli_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the `cli` directory.
    """
    created_instances = []

    class FakeServerManager:
        def __init__(self, state_file: Path):
            self.state_file = state_file
            self.restart_called_with = None
            created_instances.append(self)

        def restart_servers(self, config_file: Path, server_names):
            self.restart_called_with = (config_file, server_names)

    # Patch the symbol that RestartServersCmd actually uses
    import mada_tools.cli.commands.restart_servers as restart_mod

    monkeypatch.setattr(restart_mod, "ServerManager", FakeServerManager)

    cmd = RestartServersCmd()

    config_path = Path(cli_testing_dir) / "config.json"
    state_file_path = Path(cli_testing_dir) / "state.json"

    args = Namespace(
        config=config_path,
        state_file=state_file_path,
        servers=None,  # no specific servers provided
    )

    cmd.process_command(args)

    assert len(created_instances) == 1
    mgr = created_instances[0]

    called_config, called_servers = mgr.restart_called_with
    assert called_config == config_path
    # None indicates all servers
    assert called_servers is None
