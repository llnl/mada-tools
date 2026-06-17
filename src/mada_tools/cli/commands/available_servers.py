# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
CLI command for viewing available MCP servers.

This module defines the `AvailableServersCmd` class, which implements a
command-line interface (CLI) command for viewing the available MCP servers.
The output will include both built-in servers and plugin servers.
"""

from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser, Namespace

from mada_tools.cli.commands.base_cmd import BaseCmd
from mada_tools.server_management import ServerManager


class AvailableServersCmd(BaseCmd):
    """
    CLI command for viewing available MCP servers.

    This class adds the "available-servers" command to the main argument
    parser, allowing users to view available built-in and plugin MCP servers
    for MADA.

    Methods:
        add_parser:
            Adds the "available-servers" subcommand and its arguments to the
            CLI parser.
        process_command:
            Executes the logic for retrieving available servers using the
            parsed CLI arguments.
    """

    def add_parser(self, subparsers: ArgumentParser):
        """
        Add the parser for this command to the main `ArgumentParser`.

        Args:
            subparsers (ArgumentParser): A subparser object to add this command to.
        """
        available_servers: ArgumentParser = subparsers.add_parser(
            "available-servers",
            help="View available servers.",
            formatter_class=ArgumentDefaultsHelpFormatter,
        )
        available_servers.set_defaults(func=self.process_command)

    def process_command(self, args: Namespace):
        """
        Execute the logic for this CLI command.

        Args:
            args (Namespace): Parsed CLI arguments from the user.
        """
        # Create ServerManager (only needs state for stopping)
        manager = ServerManager()

        # Retrieve the available servers and print them out
        manager.print_available_servers()
