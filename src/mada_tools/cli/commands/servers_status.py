# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
CLI command for checking MCP server statuses.

This module defines the `ServersStatusCmd` class, which implements a
command-line interface (CLI) command for displaying the status of one
or more MCP servers. It integrates with the main argument parser,
allowing users to specify an optional list of server names and an
optional state file for tracking server status. The command invokes
server management logic to print the status table.
"""

from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser, Namespace
from pathlib import Path

from mada_tools.cli.commands.base_cmd import BaseCmd
from mada_tools.server_management import ServerManager


class ServersStatusCmd(BaseCmd):
    """
    Command to display the status of MCP servers via the CLI.

    This class adds the "servers-status" command to the main argument
    parser, allowing users to specify which servers to check and which
    state file to use. When executed, it invokes the server management
    logic to print a status table for the selected servers.

    Methods:
        add_parser:
            Adds the "servers-status" subcommand and its arguments to the CLI parser.
        process_command:
            Executes the status-check logic using the parsed CLI arguments.
    """

    def add_parser(self, subparsers: ArgumentParser):
        """
        Add the parser for this command to the main `ArgumentParser`.

        Args:
            subparsers (ArgumentParser): A subparser object to add this command to.
        """
        servers_status: ArgumentParser = subparsers.add_parser(
            "servers-status",
            help="Check status of MCP servers.",
            formatter_class=ArgumentDefaultsHelpFormatter,
        )
        servers_status.set_defaults(func=self.process_command)
        servers_status.add_argument(
            "-c",
            "--config",
            action="store",
            type=Path,
            help="An optional path to a server configuration file. "
            "If provided, status is only checked for the servers defined "
            "in this file.",
        )
        servers_status.add_argument(
            "-s",
            "--servers",
            action="store",
            nargs="+",
            type=str,
            help="An optional, space-delimited list of servers to check. "
            "If none are provided all servers will be shown.",
        )
        servers_status.add_argument(
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
        # Create ServerManager (only needs state for status)
        manager = ServerManager(state_file=args.state_file)

        # Check status of the servers
        manager.print_server_statuses(server_names=args.servers, config_file=args.config)
