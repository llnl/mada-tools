# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
CLI command for starting MCP servers.

This module defines the `StartServersCmd` class, which implements a
command-line interface (CLI) command for starting one or more MCP
servers. It integrates with the main argument parser, allowing users
to specify a configuration file, an optional list of server names, and
an optional state file for tracking server status. The command invokes
server management logic to start the specified servers.
"""

from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser, Namespace
from pathlib import Path

from mada_tools.cli.commands.base_cmd import BaseCmd
from mada_tools.server_management import ServerManager


class StartServersCmd(BaseCmd):
    """
    Command to start one or more MCP servers via the CLI.

    This class adds the "start-servers" command to the main argument
    parser, allowing users to specify which servers to start and which
    configuration and state files to use. When executed, it invokes the
    server management logic to start the selected servers.

    Methods:
        add_parser:
            Adds the "start-servers" subcommand and its arguments to the CLI parser.
        process_command:
            Executes the start logic using the parsed CLI arguments.
    """

    def add_parser(self, subparsers: ArgumentParser):
        """
        Add the parser for this command to the main `ArgumentParser`.

        Args:
            subparsers (ArgumentParser): A subparser object to add this command to.
        """
        start_servers: ArgumentParser = subparsers.add_parser(
            "start-servers",
            help="Start MCP servers.",
            formatter_class=ArgumentDefaultsHelpFormatter,
        )
        start_servers.set_defaults(func=self.process_command)
        start_servers.add_argument(
            "config",
            action="store",
            type=Path,
            help="Path to a server configuration file.",
        )
        start_servers.add_argument(
            "-s",
            "--servers",
            action="store",
            nargs="+",
            type=str,
            help="An optional, space-delimited list of servers to start. "
            "If none are provided all servers will be started.",
        )
        start_servers.add_argument(
            "-f",
            "--state-file",
            action="store",
            type=Path,
            default=Path.home() / ".mada" / "server_statuses.json",
            help="Path to a file tracking server state.",
        )

    def process_command(self, args: Namespace):
        """
        Execute the logic for this CLI command.

        Args:
            args (Namespace): Parsed CLI arguments from the user.
        """
        # Create ServerManager
        manager = ServerManager(state_file=args.state_file)
        manager.start_servers(config_file=args.config, server_names=args.servers)
