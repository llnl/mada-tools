# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
CLI command for restarting MCP servers.

This module defines the `RestartServersCmd` class, which implements a
command-line interface (CLI) command for restarting one or more MCP
servers. It integrates with the main argument parser, allowing users
to specify a configuration file, an optional list of server names, and
an optional state file for tracking server status. The command invokes
the server management logic to perform the restart operation.
"""

from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser, Namespace
from pathlib import Path

from mada_tools.cli.commands.base_cmd import BaseCmd
from mada_tools.server_management.server_manager import ServerManager


class RestartServersCmd(BaseCmd):
    """
    Command to restart one or more MCP servers via the CLI.

    This class adds the "restart-servers" command to the main argument
    parser, allowing users to specify which servers to restart and which
    configuration and state files to use. When executed, it invokes the
    server management logic to perform the restart operation.

    Methods:
        add_parser:
            Adds the "restart-servers" subcommand and its arguments to the CLI parser.
        process_command:
            Executes the restart logic using the parsed CLI arguments.
    """

    def add_parser(self, subparsers: ArgumentParser):
        """
        Add the parser for this command to the main `ArgumentParser`.

        Args:
            subparsers (ArgumentParser): A subparser object to add this command to.
        """
        restart_servers: ArgumentParser = subparsers.add_parser(
            "restart-servers",
            help="Restart MCP servers.",
            formatter_class=ArgumentDefaultsHelpFormatter,
        )
        restart_servers.set_defaults(func=self.process_command)
        restart_servers.add_argument(
            "config",
            action="store",
            type=Path,
            help="Path to a server configuration file.",
        )
        restart_servers.add_argument(
            "-s",
            "--servers",
            action="store",
            nargs="+",
            type=str,
            help="An optional, space-delimited list of servers to restart. "
            "If none are provided all servers will be restarted.",
        )
        restart_servers.add_argument(
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
        manager = ServerManager(state_file=args.state_file)
        manager.restart_servers(config_file=args.config, server_names=args.servers)
