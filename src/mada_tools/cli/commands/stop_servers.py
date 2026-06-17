# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
CLI command for stopping MCP servers.

This module defines the `StopServersCmd` class, which implements a
command-line interface (CLI) command for stopping one or more running
MCP servers. It integrates with the main argument parser, allowing
users to specify an optional list of server names to stop and an
optional state file for tracking server status. The command invokes
server management logic to stop the specified servers.
"""

from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser, Namespace
from pathlib import Path

from mada_tools.cli.commands.base_cmd import BaseCmd
from mada_tools.server_management import ServerManager


class StopServersCmd(BaseCmd):
    """
    CLI command for stopping MCP servers.

    This class adds the "stop-servers" command to the main argument
    parser, allowing users to specify which servers to stop and which
    state file to use. When executed, it invokes the server management
    logic to stop the specified servers.

    Methods:
        add_parser:
            Adds the "stop-servers" subcommand and its arguments to the CLI parser.
        process_command:
            Executes the stop logic using the parsed CLI arguments.
    """

    def add_parser(self, subparsers: ArgumentParser):
        """
        Add the parser for this command to the main `ArgumentParser`.

        Args:
            subparsers (ArgumentParser): A subparser object to add this command to.
        """
        stop_servers: ArgumentParser = subparsers.add_parser(
            "stop-servers",
            help="Stop running MCP servers.",
            formatter_class=ArgumentDefaultsHelpFormatter,
        )
        stop_servers.set_defaults(func=self.process_command)
        stop_servers.add_argument(
            "-c",
            "--config",
            action="store",
            type=Path,
            help="An optional path to a server configuration file. "
            "If provided, only the servers defined in this file will be stopped.",
        )
        stop_servers.add_argument(
            "-s",
            "--servers",
            action="store",
            nargs="+",
            type=str,
            help="An optional, space-delimited list of servers to stop. "
            "If none are provided all running servers will be stopped.",
        )
        stop_servers.add_argument(
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
        # Create ServerManager (only needs state for stopping)
        manager = ServerManager(state_file=args.state_file)

        # Stop the servers
        manager.stop_servers(server_names=args.servers, config_file=args.config)
