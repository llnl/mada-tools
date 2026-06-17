# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Tests for the `stop_servers.py` module.
"""

from argparse import Namespace
from pathlib import Path
from typing import Callable

import pytest
from _pytest.monkeypatch import MonkeyPatch

from mada_tools.cli.commands.stop_servers import StopServersCmd


@pytest.fixture
def stop_cmd() -> StopServersCmd:
    """
    Fixture that returns an instance of StopServersCmd.
    """
    return StopServersCmd()


def test_add_parser_registers_subcommand(create_parser: Callable, stop_cmd: StopServersCmd):
    """
    Verify that the `stop-servers` subcommand is correctly registered
    and that the arguments are wired as expected.

    Args:
        create_parser (Callable):
            A function that creates a parser.
        start_cmd (StartServersCmd):
            The class used for setting up the command to start the servers.
    """
    parser = create_parser(stop_cmd)

    # No options, just the subcommand
    args = parser.parse_args(["stop-servers"])

    # Main command name
    assert args.main_command == "stop-servers"

    # func should be set to process_command
    assert hasattr(args, "func")
    assert callable(args.func)

    # config is optional, should default to None
    assert args.config is None

    # servers is optional, should default to None
    assert args.servers is None

    # state_file should be a Path, with the default from the command
    assert isinstance(args.state_file, Path)


def test_add_parser_parses_servers_config_and_state_file(
    create_parser: Callable,
    stop_cmd: StopServersCmd,
    cli_testing_dir: Path,
):
    """
    Verify that the optional servers, config, and state-file arguments are parsed correctly.

    Args:
        create_parser (Callable):
            A function that creates a parser.
        start_cmd (StopServersCmd):
            The class used for setting up the command to stop the servers.
        cli_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the `cli` directory.
    """
    parser = create_parser(stop_cmd)
    state_file_path = Path(cli_testing_dir) / "custom_state.json"
    config_path = Path(cli_testing_dir) / "config.json"

    args = parser.parse_args(
        [
            "stop-servers",
            "-c",
            str(config_path),
            "-s",
            "server1",
            "server2",
            "-f",
            str(state_file_path),
        ]
    )

    assert args.main_command == "stop-servers"

    # config should be converted to Path
    assert isinstance(args.config, Path)
    assert args.config == config_path

    # servers should be a list of strings
    assert args.servers == ["server1", "server2"]

    # state_file should match the provided path
    assert args.state_file == state_file_path


def test_process_command_calls_server_manager_with_defaults(monkeypatch: MonkeyPatch):
    """
    Verify that `process_command` creates `ServerManager` with the given state_file
    and calls `stop_servers` with `config=None` and `servers=None` when no options are supplied.

    Args:
        monkeypatch (MonkeyPatch):
            Pytest's monkeypatch fixture.
    """
    created_instances = []

    class FakeServerManager:
        def __init__(self, state_file: Path):
            self.state_file = state_file
            self.stop_called_with = None
            created_instances.append(self)

        def stop_servers(self, server_names, config_file):
            self.stop_called_with = (server_names, config_file)

    # Patch the ServerManager symbol used inside StopServersCmd
    import mada_tools.cli.commands.stop_servers as stop_mod

    monkeypatch.setattr(stop_mod, "ServerManager", FakeServerManager)

    cmd = StopServersCmd()

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

    # stop_servers should have been called with the expected arguments
    assert mgr.stop_called_with is not None
    called_servers, called_config = mgr.stop_called_with
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
            self.stop_called_with = None
            created_instances.append(self)

        def stop_servers(self, server_names, config_file):
            self.stop_called_with = (server_names, config_file)

    import mada_tools.cli.commands.stop_servers as stop_mod

    monkeypatch.setattr(stop_mod, "ServerManager", FakeServerManager)

    cmd = StopServersCmd()

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

    # stop_servers args
    assert mgr.stop_called_with is not None
    called_servers, called_config = mgr.stop_called_with
    assert called_servers == servers
    assert called_config == config_path
