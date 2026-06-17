# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Tests for the `servers_status.py` module.
"""

from argparse import Namespace
from pathlib import Path
from typing import Callable

import pytest
from _pytest.monkeypatch import MonkeyPatch

from mada_tools.cli.commands.servers_status import ServersStatusCmd


@pytest.fixture
def status_cmd() -> ServersStatusCmd:
    """
    Fixture that returns an instance of ServersStatusCmd.

    Returns:
        An instance of the `ServersStatusCmd` class.
    """
    return ServersStatusCmd()


def test_add_parser_registers_subcommand(create_parser: Callable, status_cmd: ServersStatusCmd):
    """
    Verify that the `servers-status` subcommand is correctly registered
    and that the arguments are wired as expected.

    Args:
        create_parser (Callable):
            A function that creates a parser.
        status_cmd (ServersStatusCmd):
            The class used for setting up the command to check the status of the servers.
    """
    parser = create_parser(status_cmd)

    # No options, just the subcommand
    args = parser.parse_args(["servers-status"])

    # Main command name
    assert args.main_command == "servers-status"

    # func should be set to process_command
    assert hasattr(args, "func")
    assert callable(args.func)

    # config is optional, should default to None
    assert args.config is None

    # servers is optional, should default to None
    assert args.servers is None

    # state_file should be a Path, with the default from the command
    assert isinstance(args.state_file, Path)


def test_add_parser_parses_servers_and_state_file(
    create_parser: Callable,
    status_cmd: ServersStatusCmd,
    cli_testing_dir: Path,
):
    """
    Verify that the optional servers, config, and state-file arguments are parsed correctly.

    Args:
        create_parser (Callable):
            A function that creates a parser.
        status_cmd (ServersStatusCmd):
            The class used for setting up the command to check the status of the servers.
        cli_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the `cli` directory.
    """
    parser = create_parser(status_cmd)
    state_file_path = Path(cli_testing_dir) / "custom_state.json"
    config_path = Path(cli_testing_dir) / "config.json"

    args = parser.parse_args(
        [
            "servers-status",
            "-c",
            str(config_path),
            "-s",
            "server1",
            "server2",
            "-f",
            str(state_file_path),
        ]
    )

    assert args.main_command == "servers-status"

    # config should be converted to Path
    assert isinstance(args.config, Path)
    assert args.config == config_path

    # servers should be a list of strings
    assert args.servers == ["server1", "server2"]

    # state_file should match the provided path
    assert args.state_file == state_file_path


def test_process_command_calls_server_manager_with_all_defaults(monkeypatch: MonkeyPatch, cli_testing_dir: Path):
    """
    Verify that `process_command` creates `ServerManager` with the given `state_file`
    and calls `print_server_statuses` with `config=None` and `servers=None` when
    no options are supplied.

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
            self.print_called_with = None
            created_instances.append(self)

        def print_server_statuses(self, server_names, config_file):
            self.print_called_with = (server_names, config_file)

    # Patch the ServerManager symbol used inside ServersStatusCmd
    import mada_tools.cli.commands.servers_status as status_mod

    monkeypatch.setattr(status_mod, "ServerManager", FakeServerManager)

    cmd = ServersStatusCmd()

    # Simulate parsed args with only the default state_file
    default_state_file = Path.home() / ".mada" / "server_statuses.json"
    args = Namespace(
        config=None,
        servers=None,
        state_file=default_state_file,
    )

    cmd.process_command(args)

    # One ServerManager instance should have been created
    assert len(created_instances) == 1
    mgr = created_instances[0]

    # Constructor argument
    assert mgr.state_file == default_state_file

    # print_server_statuses should have been called with the expected arguments
    assert mgr.print_called_with is not None
    called_servers, called_config = mgr.print_called_with
    assert called_servers is None
    assert called_config is None


def test_process_command_with_servers_and_config(monkeypatch: MonkeyPatch, cli_testing_dir: Path):
    """
    Verify that `process_command` passes through servers and config when provided.

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
            self.print_called_with = None
            created_instances.append(self)

        def print_server_statuses(self, server_names, config_file):
            self.print_called_with = (server_names, config_file)

    import mada_tools.cli.commands.servers_status as status_mod

    monkeypatch.setattr(status_mod, "ServerManager", FakeServerManager)

    cmd = ServersStatusCmd()

    config_path = Path(cli_testing_dir) / "config.json"
    state_file_path = Path(cli_testing_dir) / "state.json"
    servers = ["one", "two"]

    args = Namespace(
        config=config_path,
        servers=servers,
        state_file=state_file_path,
    )

    cmd.process_command(args)

    assert len(created_instances) == 1
    mgr = created_instances[0]

    # Constructor arg
    assert mgr.state_file == state_file_path

    # print_server_statuses args
    assert mgr.print_called_with is not None
    called_servers, called_config = mgr.print_called_with
    assert called_servers == servers
    assert called_config == config_path
