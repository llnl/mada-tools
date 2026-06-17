# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Tests for the `start_servers.py` module.
"""

from argparse import Namespace
from pathlib import Path
from typing import Callable

import pytest
from _pytest.monkeypatch import MonkeyPatch

from mada_tools.cli.commands.start_servers import StartServersCmd


@pytest.fixture
def start_cmd() -> StartServersCmd:
    """
    Fixture that returns an instance of `StartServersCmd`.

    Returns:
        An instance of the `ServersStatusCmd` class.
    """
    return StartServersCmd()


def test_add_parser_registers_subcommand(create_parser: Callable, start_cmd: StartServersCmd):
    """
    Verify that the `start-servers` subcommand is correctly registered
    and that the arguments are wired as expected.

    Args:
        create_parser (Callable):
            A function that creates a parser.
        start_cmd (StartServersCmd):
            The class used for setting up the command to start the servers.
    """
    parser = create_parser(start_cmd)

    # Required positional config only
    args = parser.parse_args(["start-servers", "config.json"])

    # Main command name
    assert args.main_command == "start-servers"

    # func should be set to process_command
    assert hasattr(args, "func")
    assert callable(args.func)

    # config should be converted to Path
    assert isinstance(args.config, Path)
    assert args.config.name == "config.json"

    # servers is optional, should default to None
    assert args.servers is None

    # state_file should be a Path, with the default from the command
    assert isinstance(args.state_file, Path)


def test_add_parser_parses_servers_and_state_file(
    create_parser: Callable,
    start_cmd: StartServersCmd,
    cli_testing_dir: Path,
):
    """
    Verify that the optional servers and state-file arguments are parsed correctly.

    Args:
        create_parser (Callable):
            A function that creates a parser.
        start_cmd (StartServersCmd):
            The class used for setting up the command to start the servers.
        cli_testing_dir (Path):
            The path to the temporary testing directory for tests of files in the `cli` directory.
    """
    parser = create_parser(start_cmd)
    state_file_path = Path(cli_testing_dir) / "custom_state.json"
    config_path = Path(cli_testing_dir) / "config.json"

    args = parser.parse_args(
        [
            "start-servers",
            str(config_path),
            "-s",
            "server1",
            "server2",
            "-f",
            str(state_file_path),
        ]
    )

    assert args.main_command == "start-servers"

    # config should be converted to Path
    assert isinstance(args.config, Path)
    assert args.config == config_path

    # servers should be a list of strings
    assert args.servers == ["server1", "server2"]

    # state_file should match the provided path
    assert args.state_file == state_file_path


def test_process_command_calls_server_manager(monkeypatch: MonkeyPatch, cli_testing_dir: Path):
    """
    Verify that `process_command` creates `ServerManager` with the given `state_file`
    and calls `start_servers` with the correct arguments when servers are provided.

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
            self.start_called_with = None
            created_instances.append(self)

        def start_servers(self, config_file: Path, server_names):
            self.start_called_with = (config_file, server_names)

    # Patch the ServerManager symbol used inside StartServersCmd
    import mada_tools.cli.commands.start_servers as start_mod

    monkeypatch.setattr(start_mod, "ServerManager", FakeServerManager)

    cmd = StartServersCmd()

    config_path = Path(cli_testing_dir) / "config.json"
    state_file_path = Path(cli_testing_dir) / "state.json"
    servers = ["one", "two"]

    args = Namespace(
        config=config_path,
        servers=servers,
        state_file=state_file_path,
    )

    cmd.process_command(args)

    # One ServerManager instance should have been created
    assert len(created_instances) == 1
    mgr = created_instances[0]

    # Constructor argument
    assert mgr.state_file == state_file_path

    # start_servers should have been called with the expected arguments
    assert mgr.start_called_with is not None
    called_config, called_servers = mgr.start_called_with
    assert called_config == config_path
    assert called_servers == servers


def test_process_command_all_servers(monkeypatch: MonkeyPatch, cli_testing_dir: Path):
    """
    Verify that when servers is None, `process_command` passes None through
    to `ServerManager.start_servers` (meaning start all servers).

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
            self.start_called_with = None
            created_instances.append(self)

        def start_servers(self, config_file: Path, server_names):
            self.start_called_with = (config_file, server_names)

    import mada_tools.cli.commands.start_servers as start_mod

    monkeypatch.setattr(start_mod, "ServerManager", FakeServerManager)

    cmd = StartServersCmd()

    config_path = Path(cli_testing_dir) / "config.json"
    state_file_path = Path(cli_testing_dir) / "state.json"

    args = Namespace(
        config=config_path,
        servers=None,
        state_file=state_file_path,
    )

    cmd.process_command(args)

    assert len(created_instances) == 1
    mgr = created_instances[0]

    called_config, called_servers = mgr.start_called_with
    assert called_config == config_path
    assert called_servers is None
